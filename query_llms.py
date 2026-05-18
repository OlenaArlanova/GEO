import csv
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import anthropic
import requests
from openai import OpenAI

from log_to_sheets import fetch_done_today, append_single_result

BRANDS = {
    "Warmy":       ["warmy", "warmy.io"],
    "Mailreach":   ["mailreach"],
    "Instantly":   ["instantly", "instantly.ai"],
    "Folderly":    ["folderly"],
    "Validity":    ["validity"],
    "Mailwarm":    ["mailwarm"],
    "InboxAlly":   ["inboxally"],
    "WarmUpInbox": ["warmupinbox"],
    "LemWarm":     ["lemwarm"],
    "Trulyinbox":  ["trulyinbox"],
    "SmartLead":   ["smartlead", "smartlead.ai"],
    "Warmbox":     ["warmbox"],
}


def detect_brands(text):
    """Returns (mentioned_list_ordered_by_position, warmy_rank_or_None)."""
    text_lower = text.lower()
    first_pos = {}
    for brand, aliases in BRANDS.items():
        for alias in aliases:
            idx = text_lower.find(alias)
            if idx != -1 and (brand not in first_pos or idx < first_pos[brand]):
                first_pos[brand] = idx
    ordered = sorted(first_pos, key=first_pos.__getitem__)
    warmy_pos = (ordered.index("Warmy") + 1) if "Warmy" in ordered else None
    return ordered, warmy_pos


def _load_prompts():
    with open(Path(__file__).parent / "prompts.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ── Bright Data shared helpers ────────────────────────────────────────────────

_CHATGPT_DATASET_ID = "gd_m7aof0k82r803d5bjm"
_GEMINI_DATASET_ID  = "gd_mbz66arm2mf9cu856y"


def _bd_resolve_snapshot_id(resp_json, dataset_id):
    """Extract snapshot_id from trigger/scrape response, falling back to the snapshots list."""
    sid = (
        resp_json.get("snapshot_id")
        or resp_json.get("id")
        or resp_json.get("snapshotId")
    )
    if sid:
        return sid
    time.sleep(3)
    raw = requests.get(
        "https://api.brightdata.com/datasets/v3/snapshots",
        headers={"Authorization": f"Bearer {os.environ['BRIGHTDATA_API_KEY']}"},
        timeout=30,
    ).json()
    snapshots = raw.get("snapshots", raw) if isinstance(raw, dict) else raw
    dataset_snaps = [s for s in snapshots if s.get("dataset_id") == dataset_id]
    if not dataset_snaps:
        return None
    latest = sorted(
        dataset_snaps,
        key=lambda s: s.get("created") or s.get("created_at") or "",
        reverse=True,
    )[0]
    return latest.get("snapshot_id") or latest.get("id")


def _bd_poll(snapshot_id, min_items=1, label=""):
    """Poll snapshot until at least min_items results arrive (up to 30 min).
    Returns partial results if timeout is reached."""
    api_key = os.environ["BRIGHTDATA_API_KEY"]
    data = None
    for i in range(360):  # up to 30 minutes
        time.sleep(5)
        snap = requests.get(
            f"https://api.brightdata.com/datasets/v3/snapshot/{snapshot_id}",
            params={"format": "json"},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=180,
        )
        snap.raise_for_status()
        data = snap.json()
        got = len(data) if isinstance(data, list) else 0
        if got >= min_items:
            return data
        if i % 12 == 11:  # every ~60s
            print(f"  {label}still waiting… {got}/{min_items} results after {(i + 1) * 5}s")
    return data if isinstance(data, list) and data else None


def _make_result(text, urls, prompt, llm_name):
    brands_mentioned, warmy_position = detect_brands(text)
    return {
        "prompt_id":        prompt["id"],
        "prompt":           prompt["prompt"],
        "country":          prompt.get("country", ""),
        "topic":            prompt.get("topic", ""),
        "llm":              llm_name,
        "response_text":    text,
        "brands_mentioned": ",".join(brands_mentioned),
        "warmy_mentioned":  "Warmy" in brands_mentioned,
        "warmy_position":   warmy_position,
        "source_urls":      urls,
    }


# ── Bright Data batch scrapers (one request per LLM for all prompts) ──────────

def _match_prompt(item, tasks, prompt_lookup):
    """Match a result item to a prompt by text, checking common field locations."""
    candidates = [
        item.get("prompt"),
        (item.get("input") or {}).get("prompt") if isinstance(item.get("input"), dict) else item.get("input"),
    ]
    for candidate in candidates:
        if candidate and candidate in prompt_lookup:
            return prompt_lookup[candidate]
    return None


def _extract_chatgpt_urls(item):
    """Extract source URLs from a ChatGPT scraper result item."""
    seen = set()
    urls = []

    def add(u):
        # strip chatgpt tracking suffix for dedup, but keep original
        if u and u not in seen:
            seen.add(u)
            urls.append(u)

    # Flat citation/source fields (may be present in some responses)
    for c in item.get("citations") or []:
        add(c.get("url") if isinstance(c, dict) else c)
    for s in item.get("search_sources") or []:
        add(s.get("url") if isinstance(s, dict) else s)

    # search_result_groups buried in metadata dicts or lists
    for val in item.values():
        groups = []
        if isinstance(val, dict):
            groups = val.get("search_result_groups") or []
        elif isinstance(val, list):
            for el in val:
                if isinstance(el, dict):
                    groups += el.get("search_result_groups") or []
        for group in groups:
            for entry in group.get("entries") or []:
                add(entry.get("url"))

    return urls


def _run_chatgpt_batch(prompts, done_today):
    tasks = [p for p in prompts if (p["prompt"], "ChatGPT") not in done_today]
    if not tasks:
        print("ChatGPT: all prompts already done today, skipping.")
        return 0
    print(f"ChatGPT: sending batch of {len(tasks)} prompts…")
    prompt_lookup = {p["prompt"]: p for p in tasks}
    api_key = os.environ["BRIGHTDATA_API_KEY"]
    trigger = requests.post(
        "https://api.brightdata.com/datasets/v3/scrape",
        params={"dataset_id": _CHATGPT_DATASET_ID, "notify": "false", "include_errors": "true"},
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"input": [
            {"url": "https://chatgpt.com/", "prompt": p["prompt"], "web_search": True, "country": p.get("country", "") or ""}
            for p in tasks
        ]},
        timeout=180,
    )
    trigger.raise_for_status()
    snapshot_id = _bd_resolve_snapshot_id(trigger.json(), _CHATGPT_DATASET_ID)
    if not snapshot_id:
        print("ChatGPT: could not resolve snapshot_id.")
        return 0
    print(f"ChatGPT: polling snapshot {snapshot_id}…")
    data = _bd_poll(snapshot_id, min_items=len(tasks), label="ChatGPT: ")
    if not data:
        print("ChatGPT: no data returned.")
        return 0
    written = set()
    count = 0
    for i, item in enumerate(data):
        text = item.get("answer_text_raw") or item.get("answer_text") or ""
        if not text:
            continue
        matched = _match_prompt(item, tasks, prompt_lookup)
        if matched is None and i < len(tasks):
            matched = tasks[i]  # positional fallback
        if matched is None:
            continue
        if (matched["prompt"], "ChatGPT") in done_today or matched["id"] in written:
            continue
        urls = _extract_chatgpt_urls(item)
        append_single_result(_make_result(text, urls, matched, "ChatGPT"))
        written.add(matched["id"])
        count += 1
    print(f"ChatGPT: logged {count} rows.")
    return count


def _run_gemini_batch(prompts, done_today):
    tasks = [p for p in prompts if (p["prompt"], "Gemini") not in done_today]
    if not tasks:
        print("Gemini: all prompts already done today, skipping.")
        return 0
    print(f"Gemini: sending batch of {len(tasks)} prompts…")
    prompt_lookup = {p["prompt"]: p for p in tasks}
    api_key = os.environ["BRIGHTDATA_API_KEY"]
    trigger = requests.post(
        "https://api.brightdata.com/datasets/v3/scrape",
        params={"dataset_id": _GEMINI_DATASET_ID, "notify": "false", "include_errors": "true"},
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"input": [
            {"url": "https://gemini.google.com/", "prompt": p["prompt"]}
            for p in tasks
        ]},
        timeout=180,
    )
    trigger.raise_for_status()
    snapshot_id = _bd_resolve_snapshot_id(trigger.json(), _GEMINI_DATASET_ID)
    if not snapshot_id:
        print("Gemini: could not resolve snapshot_id.")
        return 0
    print(f"Gemini: polling snapshot {snapshot_id}…")
    data = _bd_poll(snapshot_id, min_items=len(tasks), label="Gemini: ")
    if not data:
        print("Gemini: no data returned.")
        return 0
    written = set()
    count = 0
    for i, item in enumerate(data):
        text = item.get("answer_text") or ""
        if not text:
            continue
        matched = _match_prompt(item, tasks, prompt_lookup)
        if matched is None and i < len(tasks):
            matched = tasks[i]  # positional fallback
        if matched is None:
            continue
        if (matched["prompt"], "Gemini") in done_today or matched["id"] in written:
            continue
        urls = [c["url"] for c in item.get("citations", []) if c.get("url")]
        urls += [lnk if isinstance(lnk, str) else lnk.get("url", "") for lnk in item.get("links_attached", [])]
        urls = [u for u in urls if u]
        append_single_result(_make_result(text, urls, matched, "Gemini"))
        written.add(matched["id"])
        count += 1
    print(f"Gemini: logged {count} rows.")
    return count


# ── Per-prompt queriers (Claude, Perplexity, GoogleAIOverview) ────────────────

def _query_anthropic(prompt_text):
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=8096,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": prompt_text}],
    )
    text = "\n".join(b.text for b in resp.content if hasattr(b, "text"))
    urls = []
    for block in resp.content:
        if getattr(block, "type", None) == "tool_result":
            for item in getattr(block, "content", []) or []:
                url = item.get("url") if isinstance(item, dict) else getattr(item, "url", None)
                if url:
                    urls.append(url)
    return text, urls


def _query_perplexity(prompt_text):
    client = OpenAI(
        api_key=os.environ["PERPLEXITY_API_KEY"],
        base_url="https://api.perplexity.ai",
    )
    resp = client.chat.completions.create(
        model="sonar",
        messages=[{"role": "user", "content": prompt_text}],
    )
    urls = list(getattr(resp, "citations", None) or [])
    return resp.choices[0].message.content, urls


def _query_google_ai_overview(prompt_text):
    resp = requests.get(
        "https://api.brightdata.com/serp/google",
        params={"q": prompt_text, "brd_ai_overview": 2},
        headers={"Authorization": f"Bearer {os.environ['BRIGHTDATA_API_KEY']}"},
        timeout=180,
    )
    resp.raise_for_status()
    data = resp.json()
    ai_overview = data.get("ai_overview") or {}
    text = ai_overview.get("text") or ai_overview.get("snippet") or ""
    if not text:
        return None, []
    sources = ai_overview.get("sources") or ai_overview.get("references") or []
    urls = [s.get("url") or s.get("link") for s in sources if isinstance(s, dict)]
    urls = [u for u in urls if u]
    return text, urls


def _query_google_ai_mode(prompt_text):
    api_key = os.environ["BRIGHTDATA_API_KEY"]
    dataset_id = os.environ["BRIGHTDATA_GOOGLE_AI_DATASET_ID"]
    trigger = requests.post(
        "https://api.brightdata.com/datasets/v3/trigger",
        params={"dataset_id": dataset_id, "include_errors": "true"},
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=[{"query": prompt_text}],
        timeout=180,
    )
    trigger.raise_for_status()
    snapshot_id = _bd_resolve_snapshot_id(trigger.json(), dataset_id)
    if not snapshot_id:
        return None, []
    data = _bd_poll(snapshot_id)
    if not data:
        return None, []
    item = data[0]
    text = next((item.get(f) for f in ["answer", "response", "text", "content"] if item.get(f)), None) or ""
    if not text:
        return None, []
    sources = next((item.get(f) for f in ["sources", "citations", "links", "references"] if item.get(f)), []) or []
    urls = []
    for s in sources:
        if isinstance(s, str):
            urls.append(s)
        elif isinstance(s, dict):
            u = s.get("url") or s.get("link") or s.get("href")
            if u:
                urls.append(u)
    return text, urls


# ── Per-prompt runner (for non-batch LLMs) ────────────────────────────────────

_PER_PROMPT_QUERIERS = {
    # "Claude":           _query_anthropic,
    # "Perplexity":       _query_perplexity,
    # "GoogleAIOverview": _query_google_ai_overview,
    # "GoogleAIMode":     _query_google_ai_mode,
}

_WORKERS = {
    "GoogleAIOverview": 3,
    "GoogleAIMode":     1,  # sequential — one snapshot at a time
}


def _with_retry(fn, *args, retries=5, base_delay=10):
    for attempt in range(retries):
        try:
            return fn(*args)
        except Exception as e:
            if attempt == retries - 1:
                raise
            delay = base_delay * (2 ** attempt)
            print(f"  [retry {attempt + 1}/{retries}] {e} — waiting {delay}s")
            time.sleep(delay)


def _run_and_save(prompt, llm_name, querier):
    response_text, source_urls = _with_retry(querier, prompt["prompt"])
    if response_text is None:
        return None
    brands_mentioned, warmy_position = detect_brands(response_text)
    result = {
        "prompt_id":        prompt["id"],
        "prompt":           prompt["prompt"],
        "country":          prompt["country"],
        "topic":            prompt["topic"],
        "llm":              llm_name,
        "response_text":    response_text,
        "brands_mentioned": ",".join(brands_mentioned),
        "warmy_mentioned":  "Warmy" in brands_mentioned,
        "warmy_position":   warmy_position,
        "source_urls":      source_urls,
    }
    append_single_result(result)
    return result


def _run_llm(llm_name, querier, prompts, done_today):
    tasks = [p for p in prompts if (p["prompt"], llm_name) not in done_today]
    if not tasks:
        print(f"{llm_name}: all prompts already done today, skipping.")
        return 0
    count = 0
    with ThreadPoolExecutor(max_workers=_WORKERS.get(llm_name, 10)) as executor:
        futures = {executor.submit(_run_and_save, p, llm_name, querier): p for p in tasks}
        for future in as_completed(futures):
            if future.result() is not None:
                count += 1
    return count


# ── Entry point ───────────────────────────────────────────────────────────────

def run_all_queries():
    prompts = _load_prompts()
    done_today = fetch_done_today()
    total = 0

    # Batch Bright Data scrapers — one request each, no duplicate snapshots
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(_run_chatgpt_batch, prompts, done_today),
            executor.submit(_run_gemini_batch, prompts, done_today),
        ]
        for future in as_completed(futures):
            total += future.result()

    # Per-prompt LLMs (concurrent across LLMs)
    if _PER_PROMPT_QUERIERS:
        with ThreadPoolExecutor(max_workers=len(_PER_PROMPT_QUERIERS)) as executor:
            futures = {
                executor.submit(_run_llm, name, querier, prompts, done_today): name
                for name, querier in _PER_PROMPT_QUERIERS.items()
            }
            for future in as_completed(futures):
                total += future.result()

    return total
