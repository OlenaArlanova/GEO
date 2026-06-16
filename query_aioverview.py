"""
Query Google AI Overview via Brightdata SERP API for all prompts in prompts.csv
and log results to Google Sheets. Results are NOT stored in Brightdata snapshots.

Usage:
    python query_aioverview.py
"""

import csv
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote_plus

import requests
from dotenv import load_dotenv

load_dotenv()

from query_llms import detect_brands
from log_to_sheets import append_single_result, fetch_done_today, flush_pending

_LLM_NAME = "GoogleAIOverview"
_API_URL = "https://api.brightdata.com/request"
_MAX_WORKERS = 3


def _headers():
    return {
        "Authorization": f"Bearer {os.environ['BRIGHTDATA_API_KEY']}",
        "Content-Type": "application/json",
    }


def load_prompts():
    with open(Path(__file__).parent / "prompts.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _query_one(prompt_row):
    zone = os.environ["BRIGHTDATA_SERP_ZONE"]
    search_url = f"https://www.google.com/search?q={quote_plus(prompt_row['prompt'])}&brd_ai_overview=2"
    for attempt in range(2):
        try:
            resp = requests.post(
                _API_URL,
                headers=_headers(),
                json={"zone": zone, "url": search_url, "format": "raw"},
                timeout=120,
            )
            resp.raise_for_status()
            if not resp.text.strip():
                raise ValueError(f"Empty response (HTTP {resp.status_code})")
            try:
                return resp.json()
            except Exception:
                raise ValueError(f"Non-JSON response (HTTP {resp.status_code}): {resp.text[:300]}")
        except Exception as e:
            if attempt == 1:
                raise
            time.sleep(5)



def _extract_text(ai_overview):
    # flat format (serp/google endpoint)
    flat = ai_overview.get("text") or ai_overview.get("snippet") or ""
    if flat:
        return flat
    # array format (request endpoint)
    snippets = []
    for item in (ai_overview.get("texts") or []):
        if item.get("type") == "paragraph":
            s = item.get("snippet", "").strip()
            if s:
                snippets.append(s)
        elif item.get("type") == "list":
            title = item.get("title", "").strip()
            if title:
                snippets.append(title)
            for li in (item.get("list") or []):
                s = li.get("snippet", "").strip()
                if s:
                    snippets.append(s)
    return "\n\n".join(snippets)


def _extract_urls(ai_overview):
    sources = (
        ai_overview.get("sources")
        or ai_overview.get("references")
        or []
    )
    urls = []
    for s in sources:
        if isinstance(s, dict):
            u = s.get("url") or s.get("href") or s.get("link")
            if u:
                urls.append(u)
    return urls


def _process_prompt(prompt_row, done_today):
    prompt_text = prompt_row["prompt"]

    if (prompt_text, _LLM_NAME) in done_today:
        return "skipped_duplicate"

    try:
        data = _query_one(prompt_row)
    except Exception as e:
        print(f"  [error] prompt_id={prompt_row['id']}: {e}")
        return "error"

    ai_overview = data.get("ai_overview")
    if not ai_overview:
        return "no_overview"

    text = _extract_text(ai_overview)
    if not text:
        return "no_overview"

    urls = _extract_urls(ai_overview)
    brands_mentioned, warmy_position = detect_brands(text)

    result = {
        "prompt_id":        prompt_row["id"],
        "prompt":           prompt_text,
        "country":          prompt_row.get("country", ""),
        "topic":            prompt_row.get("topic", ""),
        "llm":              _LLM_NAME,
        "response_text":    text,
        "brands_mentioned": ",".join(brands_mentioned),
        "warmy_mentioned":  "Warmy" in brands_mentioned,
        "warmy_position":   warmy_position,
        "source_urls":      urls,
    }

    time.sleep(1)  # stay under Sheets write quota
    append_single_result(result)
    print(
        f"  [written] prompt_id={prompt_row['id']} "
        f"warmy_pos={warmy_position} urls={len(urls)}"
    )
    return "written"


def run():
    prompts = load_prompts()
    done_today = fetch_done_today()
    tasks = [p for p in prompts if (p["prompt"], _LLM_NAME) not in done_today]

    print(f"Total prompts: {len(prompts)}  |  Already done today: {len(prompts) - len(tasks)}  |  To query: {len(tasks)}")

    counts = {"written": 0, "no_overview": 0, "skipped_duplicate": 0, "error": 0}

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        futures = {executor.submit(_process_prompt, p, done_today): p for p in tasks}
        for future in as_completed(futures):
            outcome = future.result()
            counts[outcome] = counts.get(outcome, 0) + 1

    flush_pending()
    print(
        f"\nDone.  written={counts['written']}  "
        f"no_overview={counts['no_overview']}  "
        f"errors={counts['error']}  "
        f"skipped_duplicate={counts['skipped_duplicate']}"
    )


if __name__ == "__main__":
    run()
