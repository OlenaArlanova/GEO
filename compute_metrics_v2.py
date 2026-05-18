import json
import os
from collections import defaultdict
from datetime import date, timedelta

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

ALL_BRANDS = [
    "Warmy", "Mailreach", "Instantly", "Folderly", "Validity",
    "Mailwarm", "InboxAlly", "WarmUpInbox", "LemWarm", "Trulyinbox",
    "SmartLead", "Warmbox",
]


def _service():
    creds = Credentials.from_service_account_info(
        json.loads(os.environ["GOOGLE_SHEETS_CREDENTIALS_JSON"]),
        scopes=_SCOPES,
    )
    return build("sheets", "v4", credentials=creds)


def _fetch_all_rows():
    svc = _service()
    result = svc.spreadsheets().values().get(
        spreadsheetId=os.environ["GOOGLE_SHEETS_ID"],
        range="Logs",
    ).execute()
    values = result.get("values", [])
    if len(values) < 2:
        return []
    headers = values[0]
    return [
        dict(zip(headers, row + [""] * max(0, len(headers) - len(row))))
        for row in values[1:]
    ]


def _parse(raw_rows):
    rows = []
    for r in raw_rows:
        rows.append({
            "date":             r.get("date", ""),
            "llm":              r.get("llm", ""),
            "prompt_id":        r.get("prompt_id", ""),
            "country":          r.get("country", ""),
            "topic":            r.get("topic", ""),
            "brands_mentioned": [b for b in r.get("brands_mentioned", "").split(",") if b],
            "warmy_mentioned":  r.get("warmy_mentioned", "").lower() == "true",
            "warmy_position":   int(r["warmy_position"]) if r.get("warmy_position") else None,
        })
    return rows


def _sov(rows):
    """Brand mentions / total brand mentions across all brands (%)."""
    counts = defaultdict(int)
    for row in rows:
        for brand in row["brands_mentioned"]:
            counts[brand] += 1
    total = sum(counts.values()) or 1
    return {b: counts.get(b, 0) / total * 100 for b in ALL_BRANDS}


def _mention_rate(rows):
    if not rows:
        return 0.0
    return sum(1 for r in rows if r["warmy_mentioned"]) / len(rows) * 100


def _avg_position(rows):
    positions = [r["warmy_position"] for r in rows if r["warmy_position"] is not None]
    return sum(positions) / len(positions) if positions else None


def _rank_in_pack(sov_dict):
    sorted_brands = sorted(sov_dict.items(), key=lambda x: x[1], reverse=True)
    for i, (brand, _) in enumerate(sorted_brands):
        if brand == "Warmy":
            return i + 1
    return len(ALL_BRANDS)


def _top_competitor(rows):
    """(brand_name, sov_pct) for the non-Warmy brand with highest SoV in rows."""
    counts = defaultdict(int)
    for row in rows:
        for brand in row["brands_mentioned"]:
            counts[brand] += 1
    total = sum(counts.values()) or 1
    competitors = {b: c / total * 100 for b, c in counts.items() if b != "Warmy"}
    if not competitors:
        return "—", 0.0
    top = max(competitors, key=competitors.get)
    return top, round(competitors[top], 2)


def _delta(a, b):
    if a is None or b is None:
        return None
    return round(a - b, 2)


def _group_by(rows, key):
    groups = defaultdict(list)
    for row in rows:
        groups[row[key]].append(row)
    return groups


def _llm_metrics(today_rows, yest_rows):
    metrics = {}
    for llm in ["ChatGPT", "Gemini", "Perplexity", "GoogleAIMode", "GoogleAIOverview"]:
        t = [r for r in today_rows if r["llm"] == llm]
        y = [r for r in yest_rows if r["llm"] == llm]
        t_sov = _sov(t)
        y_sov = _sov(y)
        top_comp, top_comp_sov = _top_competitor(t)
        rank = _rank_in_pack(t_sov)
        metrics[llm] = {
            "rank":             rank,
            "sov":              round(t_sov.get("Warmy", 0.0), 2),
            "mention_rate":     round(_mention_rate(t), 1),
            "delta_sov":        _delta(t_sov.get("Warmy"), y_sov.get("Warmy")),
            "top_competitor":   top_comp,
            "top_competitor_sov": top_comp_sov,
        }
    return metrics


def _topic_metrics(today_rows, yest_rows):
    today_by_topic = _group_by(today_rows, "topic")
    yest_by_topic = _group_by(yest_rows, "topic")
    metrics = {}
    for topic, t in today_by_topic.items():
        if not topic:
            continue
        y = yest_by_topic.get(topic, [])
        t_sov = _sov(t)
        y_sov = _sov(y)
        rank = _rank_in_pack(t_sov)
        sorted_sov = sorted(t_sov.items(), key=lambda x: x[1], reverse=True)
        leader = sorted_sov[0][0] if sorted_sov and sorted_sov[0][1] > 0 else "—"
        metrics[topic] = {
            "rank":      rank,
            "sov":       round(t_sov.get("Warmy", 0.0), 2),
            "delta_sov": _delta(t_sov.get("Warmy"), y_sov.get("Warmy")),
            "leader":    leader,
        }
    return dict(sorted(metrics.items(), key=lambda x: x[1]["rank"]))


def compute_metrics():
    all_rows = _parse(_fetch_all_rows())
    today_str = date.today().isoformat()
    yest_str = (date.today() - timedelta(days=1)).isoformat()

    today_rows = [r for r in all_rows if r["date"] == today_str]
    yest_rows = [r for r in all_rows if r["date"] == yest_str]

    t_sov = _sov(today_rows)
    y_sov = _sov(yest_rows)
    t_mention = _mention_rate(today_rows)
    y_mention = _mention_rate(yest_rows)
    t_pos = _avg_position(today_rows)
    y_pos = _avg_position(yest_rows)
    t_rank = _rank_in_pack(t_sov)
    y_rank = _rank_in_pack(y_sov)

    # 14-day SoV trend for Warmy + top 3 competitors by recent SoV (US only)
    trend_days = [date.today() - timedelta(days=13 - i) for i in range(14)]
    trend_series = {}
    for brand in ALL_BRANDS:
        series = []
        for d in trend_days:
            d_rows = [r for r in all_rows if r["date"] == d.isoformat()]
            series.append(round(_sov(d_rows).get(brand, 0.0), 2) if d_rows else 0.0)
        trend_series[brand] = series

    # Pick top 3 non-Warmy brands by their latest day SoV
    competitors_today = sorted(
        [(b, t_sov.get(b, 0)) for b in ALL_BRANDS if b != "Warmy"],
        key=lambda x: x[1], reverse=True,
    )
    trend_brands = ["Warmy"] + [b for b, _ in competitors_today[:3]]

    leaderboard = sorted(
        [(b, round(t_sov.get(b, 0.0), 2)) for b in ALL_BRANDS],
        key=lambda x: x[1], reverse=True,
    )

    return {
        "date":      today_str,
        "yesterday": yest_str,
        "overall": {
            "rank":               t_rank,
            "sov":                round(t_sov.get("Warmy", 0.0), 2),
            "mention_rate":       round(t_mention, 1),
            "avg_position":       round(t_pos, 1) if t_pos is not None else None,
            "delta_rank":         _delta(t_rank, y_rank),
            "delta_sov":          _delta(t_sov.get("Warmy"), y_sov.get("Warmy")),
            "delta_mention_rate": _delta(t_mention, y_mention),
            "delta_avg_pos":      _delta(t_pos, y_pos),
            "yest_rank":          y_rank,
            "yest_sov":           round(y_sov.get("Warmy", 0.0), 2),
            "yest_mention_rate":  round(y_mention, 1),
            "yest_avg_pos":       round(y_pos, 1) if y_pos is not None else None,
        },
        "trend": {
            "dates":   [d.strftime("%b %-d") for d in trend_days],
            "brands":  trend_brands,
            "series":  {b: trend_series[b] for b in trend_brands},
        },
        "by_llm":    _llm_metrics(today_rows, yest_rows),
        "by_topic":  _topic_metrics(today_rows, yest_rows),
        "leaderboard": leaderboard,
    }
