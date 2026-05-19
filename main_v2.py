from datetime import date
from dotenv import load_dotenv
load_dotenv()

from download_snapshot import process_snapshot as _process_chatgpt, get_todays_chatgpt_snapshot
from download_snapshot_gemini import process_snapshot as _process_gemini, get_todays_gemini_snapshot
from download_snapshot_perplexity import process_snapshot as _process_perplexity, get_todays_perplexity_snapshot
from download_snapshot_googleaimode import process_snapshot as _process_googleaimode, get_todays_googleaimode_snapshot
from query_aioverview import run as run_aioverview
from compute_metrics_v2 import compute_metrics
from render_dashboard_v2 import render_to_png
from post_to_slack import post_image

OUTPUT_PNG = "dashboard_v2.png"

def _run_snapshot(label, get_snap_fn, process_fn):
    snap = get_snap_fn()
    if not snap:
        print(f"{label}: no snapshot found for today, skipping.")
        return 0
    sid = snap.get("snapshot_id") or snap.get("id")
    status = snap.get("status", "unknown")
    print(f"{label}: found snapshot {sid} (status={status})")
    return process_fn(sid)

def main():
    total = 0

    # print("--- Downloading snapshots ---")
    # total += _run_snapshot("ChatGPT", get_todays_chatgpt_snapshot, _process_chatgpt)
    # total += _run_snapshot("Gemini", get_todays_gemini_snapshot, _process_gemini)
    # total += _run_snapshot("Perplexity", get_todays_perplexity_snapshot, _process_perplexity)
    # total += _run_snapshot("GoogleAIMode", get_todays_googleaimode_snapshot, _process_googleaimode)

    # print("--- Querying Google AI Overview ---")
    # run_aioverview()

    print(f"Total snapshot rows written: {total}")

    print("Computing metrics...")
    metrics = compute_metrics()

    print("Rendering dashboard...")
    render_to_png(metrics, OUTPUT_PNG)

    today = date.today().strftime("%B %-d, %Y")
    print(f"Posting to Slack ({today})...")
    post_image(OUTPUT_PNG, today)

    print("Done.")

if __name__ == "__main__":
    main()
