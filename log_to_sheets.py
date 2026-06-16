import json
import os
import threading
import time
from datetime import date

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_write_lock = threading.Lock()
_COLUMNS = [
    "date", "llm", "prompt_id", "prompt", "country", "topic",
    "response_text", "brands_mentioned", "warmy_mentioned", "warmy_position",
    "source_urls",
]
_SOURCES_GID = 1200576464
_SHEETS_CELL_LIMIT = 49000
_BATCH_SIZE = 50
_MAX_RETRIES = 5
_RETRY_STATUSES = {429, 503}


def _trunc(value, limit=_SHEETS_CELL_LIMIT):
    s = str(value) if value is not None else ""
    return s[:limit] if len(s) > limit else s


_RETRY_DELAYS = [30, 60, 60, 60]  # waits between attempts 1-2, 2-3, 3-4, 4-5


def _execute_with_retry(request):
    for attempt in range(_MAX_RETRIES):
        try:
            return request.execute()
        except HttpError as exc:
            if exc.resp.status in _RETRY_STATUSES and attempt < _MAX_RETRIES - 1:
                delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                print(f"  [sheets] HTTP {exc.resp.status}, retrying in {delay}s (attempt {attempt + 1}/{_MAX_RETRIES})…")
                time.sleep(delay)
            else:
                raise


def _service():
    creds = Credentials.from_service_account_info(
        json.loads(os.environ["GOOGLE_SHEETS_CREDENTIALS_JSON"]),
        scopes=_SCOPES,
    )
    return build("sheets", "v4", credentials=creds)


def _ensure_header(svc, sheet_id):
    existing = _execute_with_retry(
        svc.spreadsheets().values().get(spreadsheetId=sheet_id, range="Logs!A1:K1")
    ).get("values")
    if not existing:
        _execute_with_retry(
            svc.spreadsheets().values().update(
                spreadsheetId=sheet_id,
                range="Logs!A1",
                valueInputOption="RAW",
                body={"values": [_COLUMNS]},
            )
        )


def _get_sheet_title_by_gid(svc, spreadsheet_id, gid):
    meta = _execute_with_retry(svc.spreadsheets().get(spreadsheetId=spreadsheet_id))
    for sheet in meta.get("sheets", []):
        if sheet["properties"]["sheetId"] == gid:
            return sheet["properties"]["title"]
    return None


def _ensure_sources_header(svc, sheet_id, sheet_title):
    existing = _execute_with_retry(
        svc.spreadsheets().values().get(spreadsheetId=sheet_id, range=f"{sheet_title}!A1:C1")
    ).get("values")
    if not existing:
        _execute_with_retry(
            svc.spreadsheets().values().update(
                spreadsheetId=sheet_id,
                range=f"{sheet_title}!A1",
                valueInputOption="RAW",
                body={"values": [["URL", "Date", "LLM"]]},
            )
        )


def _append_sources(svc, sheet_id, llm_name, urls):
    if not urls:
        return
    sheet_title = _get_sheet_title_by_gid(svc, sheet_id, _SOURCES_GID)
    if not sheet_title:
        return
    _ensure_sources_header(svc, sheet_id, sheet_title)
    today = date.today().isoformat()
    rows = [[url, today, llm_name] for url in urls]
    _execute_with_retry(
        svc.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range=f"{sheet_title}!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": rows},
        )
    )


def fetch_done_today():
    """Returns set of (prompt_text, llm) already logged today."""
    svc = _service()
    result = _execute_with_retry(
        svc.spreadsheets().values().get(
            spreadsheetId=os.environ["GOOGLE_SHEETS_ID"],
            range="Logs",
        )
    )
    values = result.get("values", [])
    if len(values) < 2:
        return set()
    headers = values[0]
    today_str = date.today().isoformat()
    try:
        date_idx   = headers.index("date")
        llm_idx    = headers.index("llm")
        prompt_idx = headers.index("prompt")
    except ValueError:
        return set()
    done = set()
    for row in values[1:]:
        if len(row) > max(date_idx, llm_idx, prompt_idx) and row[date_idx] == today_str:
            done.add((row[prompt_idx], row[llm_idx]))
    return done


_pending = []


def _flush_locked():
    """Flush _pending to Sheets. Must be called with _write_lock held."""
    if not _pending:
        return
    batch = _pending[:]
    _pending.clear()
    today = date.today().isoformat()
    rows = [
        [
            today,
            r["llm"],
            r["prompt_id"],
            _trunc(r["prompt"]),
            r["country"],
            _trunc(r.get("topic") or ""),
            _trunc(r["response_text"]),
            _trunc(r["brands_mentioned"]),
            str(r["warmy_mentioned"]),
            str(r["warmy_position"]) if r["warmy_position"] is not None else "",
            _trunc(",".join(r.get("source_urls") or [])),
        ]
        for r in batch
    ]
    svc = _service()
    sheet_id = os.environ["GOOGLE_SHEETS_ID"]
    _execute_with_retry(
        svc.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range="Logs!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": rows},
        )
    )
    for r in batch:
        _append_sources(svc, sheet_id, r["llm"], r.get("source_urls") or [])


def append_single_result(result):
    with _write_lock:
        _pending.append(result)
        if len(_pending) >= _BATCH_SIZE:
            _flush_locked()


def flush_pending():
    with _write_lock:
        _flush_locked()


def append_results(results):
    svc = _service()
    sheet_id = os.environ["GOOGLE_SHEETS_ID"]
    _ensure_header(svc, sheet_id)
    today = date.today().isoformat()
    rows = [
        [
            today,
            r["llm"],
            r["prompt_id"],
            _trunc(r["prompt"]),
            r["country"],
            _trunc(r["topic"]),
            _trunc(r["response_text"]),
            _trunc(r["brands_mentioned"]),
            str(r["warmy_mentioned"]),
            str(r["warmy_position"]) if r["warmy_position"] is not None else "",
            _trunc(",".join(r.get("source_urls") or [])),
        ]
        for r in results
    ]
    for i in range(0, len(rows), _BATCH_SIZE):
        _execute_with_retry(
            svc.spreadsheets().values().append(
                spreadsheetId=sheet_id,
                range="Logs!A1",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": rows[i:i + _BATCH_SIZE]},
            )
        )
    for r in results:
        _append_sources(svc, sheet_id, r["llm"], r.get("source_urls") or [])
