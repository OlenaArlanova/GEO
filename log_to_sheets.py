import json
import os
import threading
from datetime import date

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_write_lock = threading.Lock()
_COLUMNS = [
    "date", "llm", "prompt_id", "prompt", "country", "topic",
    "response_text", "brands_mentioned", "warmy_mentioned", "warmy_position",
    "source_urls",
]
_SOURCES_GID = 1200576464


def _service():
    creds = Credentials.from_service_account_info(
        json.loads(os.environ["GOOGLE_SHEETS_CREDENTIALS_JSON"]),
        scopes=_SCOPES,
    )
    return build("sheets", "v4", credentials=creds)


def _ensure_header(svc, sheet_id):
    existing = svc.spreadsheets().values().get(
        spreadsheetId=sheet_id, range="Logs!A1:K1"
    ).execute().get("values")
    if not existing:
        svc.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range="Logs!A1",
            valueInputOption="RAW",
            body={"values": [_COLUMNS]},
        ).execute()


def _get_sheet_title_by_gid(svc, spreadsheet_id, gid):
    meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    for sheet in meta.get("sheets", []):
        if sheet["properties"]["sheetId"] == gid:
            return sheet["properties"]["title"]
    return None


def _ensure_sources_header(svc, sheet_id, sheet_title):
    existing = svc.spreadsheets().values().get(
        spreadsheetId=sheet_id, range=f"{sheet_title}!A1:C1"
    ).execute().get("values")
    if not existing:
        svc.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range=f"{sheet_title}!A1",
            valueInputOption="RAW",
            body={"values": [["URL", "Date", "LLM"]]},
        ).execute()


def _append_sources(svc, sheet_id, llm_name, urls):
    if not urls:
        return
    sheet_title = _get_sheet_title_by_gid(svc, sheet_id, _SOURCES_GID)
    if not sheet_title:
        return
    _ensure_sources_header(svc, sheet_id, sheet_title)
    today = date.today().isoformat()
    rows = [[url, today, llm_name] for url in urls]
    svc.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range=f"{sheet_title}!A1",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": rows},
    ).execute()


def fetch_done_today():
    """Returns set of (prompt_text, llm) already logged today."""
    svc = _service()
    result = svc.spreadsheets().values().get(
        spreadsheetId=os.environ["GOOGLE_SHEETS_ID"],
        range="Logs",
    ).execute()
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


def append_single_result(result):
    source_urls = result.get("source_urls") or []
    row = [
        date.today().isoformat(),
        result["llm"],
        result["prompt_id"],
        result["prompt"],
        result["country"],
        result["topic"],
        result["response_text"],
        result["brands_mentioned"],
        str(result["warmy_mentioned"]),
        str(result["warmy_position"]) if result["warmy_position"] is not None else "",
        ",".join(source_urls),
    ]
    with _write_lock:
        svc = _service()
        sheet_id = os.environ["GOOGLE_SHEETS_ID"]
        svc.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range="Logs!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()
        _append_sources(svc, sheet_id, result["llm"], source_urls)


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
            r["prompt"],
            r["country"],
            r["topic"],
            r["response_text"],
            r["brands_mentioned"],
            str(r["warmy_mentioned"]),
            str(r["warmy_position"]) if r["warmy_position"] is not None else "",
            ",".join(r.get("source_urls") or []),
        ]
        for r in results
    ]
    svc.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range="Logs!A1",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": rows},
    ).execute()
    for r in results:
        _append_sources(svc, sheet_id, r["llm"], r.get("source_urls") or [])
