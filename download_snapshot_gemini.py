"""
Download today's Gemini snapshot from Brightdata and log results to Google Sheets.

Usage:
    python download_snapshot_gemini.py                  # auto-pick today's latest snapshot
    python download_snapshot_gemini.py <snapshot_id>    # use a specific snapshot
"""

import csv
import os
import sys
import time
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

from query_llms import detect_brands
from log_to_sheets import append_single_result, fetch_done_today, flush_pending

_GEMINI_DATASET_ID = "gd_mbz66arm2mf9cu856y"
_LLM_NAME = "Gemini"
TODAY = date.today().isoformat()


def _headers():
    return {
        "Authorization": f"Bearer {os.environ['BRIGHTDATA_API_KEY']}",
        "Content-Type": "application/json",
    }


def load_prompts():
    with open(Path(__file__).parent / "prompts.csv", newline="", encoding="utf-8") as f:
        return {row["prompt"]: row for row in csv.DictReader(f)}


def get_todays_gemini_snapshot():
    """Return the most recent Gemini snapshot created today, or None."""
    resp = requests.get(
        "https://api.brightdata.com/datasets/v3/snapshots",
        headers=_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    raw = resp.json()
    snapshots = raw.get("snapshots", raw) if isinstance(raw, dict) else raw

    candidates = []
    for snap in snapshots:
        if snap.get("dataset_id") != _GEMINI_DATASET_ID:
            continue
        created = snap.get("created") or snap.get("created_at") or ""
        if TODAY in str(created):
            candidates.append(snap)

    if not candidates:
        return None

    return sorted(
        candidates,
        key=lambda s: s.get("created") or s.get("created_at") or "",
        reverse=True,
    )[0]


def poll_snapshot(snapshot_id, timeout_minutes=30):
    """Poll until snapshot is ready. Returns list of items or None on timeout."""
    deadline = time.time() + timeout_minutes * 60
    attempt = 0
    while time.time() < deadline:
        time.sleep(5)
        resp = requests.get(
            f"https://api.brightdata.com/datasets/v3/snapshot/{snapshot_id}",
            params={"format": "json"},
            headers=_headers(),
            timeout=180,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and data:
            print(f"  Snapshot ready: {len(data)} item(s).")
            return data
        attempt += 1
        if attempt % 12 == 0:
            elapsed = int(time.time() - (deadline - timeout_minutes * 60))
            print(f"  Still waiting… {elapsed}s elapsed")
    print("  Timed out waiting for snapshot.")
    return None


def _extract_gemini_urls(item):
    urls = [c["url"] for c in (item.get("citations") or []) if isinstance(c, dict) and c.get("url")]
    urls += [
        lnk if isinstance(lnk, str) else lnk.get("url", "")
        for lnk in (item.get("links_attached") or [])
    ]
    return [u for u in urls if u]


def process_snapshot(snapshot_id):
    prompt_lookup = load_prompts()
    done_today = fetch_done_today()

    print(f"Fetching snapshot {snapshot_id}…")
    data = poll_snapshot(snapshot_id)
    if not data:
        print("No data returned.")
        return 0

    written = 0
    skipped_no_text = 0
    skipped_duplicate = 0

    for i, item in enumerate(data):
        text = item.get("answer_text") or ""
        if not text:
            skipped_no_text += 1
            continue

        prompt_text = item.get("prompt") or (
            item.get("input", {}).get("prompt")
            if isinstance(item.get("input"), dict)
            else item.get("input") or ""
        )
        prompt_row = prompt_lookup.get(prompt_text)

        if (prompt_text, _LLM_NAME) in done_today:
            skipped_duplicate += 1
            continue

        urls = _extract_gemini_urls(item)
        brands_mentioned, warmy_position = detect_brands(text)

        result = {
            "prompt_id":        prompt_row["id"] if prompt_row else f"{snapshot_id}_{i + 1}",
            "prompt":           prompt_text,
            "country":          prompt_row.get("country", "") if prompt_row else "",
            "topic":            prompt_row.get("topic", "") if prompt_row else "",
            "llm":              _LLM_NAME,
            "response_text":    text,
            "brands_mentioned": ",".join(brands_mentioned),
            "warmy_mentioned":  "Warmy" in brands_mentioned,
            "warmy_position":   warmy_position,
            "source_urls":      urls,
        }

        append_single_result(result)
        written += 1
        print(
            f"  [{written}] prompt_id={result['prompt_id']} "
            f"warmy_pos={warmy_position} urls={len(urls)}"
        )
        time.sleep(1)

    flush_pending()
    print(
        f"\nDone. written={written}  "
        f"skipped_duplicate={skipped_duplicate}  "
        f"skipped_no_text={skipped_no_text}"
    )
    return written


if __name__ == "__main__":
    if len(sys.argv) > 1:
        snapshot_id = sys.argv[1]
        print(f"Using provided snapshot_id: {snapshot_id}")
    else:
        print(f"Looking for today's Gemini snapshot ({TODAY})…")
        snap = get_todays_gemini_snapshot()
        if not snap:
            print("No Gemini snapshot found for today. Run the curl first.")
            sys.exit(1)
        snapshot_id = snap.get("snapshot_id") or snap.get("id")
        status = snap.get("status", "unknown")
        print(f"Found snapshot {snapshot_id} (status={status})")

    process_snapshot(snapshot_id)
