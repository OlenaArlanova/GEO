import json
from datetime import datetime
from pathlib import Path


_BRAND_DISPLAY = {
    "Warmy":            "Warmy",
    "Mailreach":        "Mailreach",
    "Instantly":        "Instantly.ai",
    "Folderly":         "Folderly",
    "Validity":         "Validity",
    "Mailwarm":         "Mailwarm",
    "InboxAlly":        "InboxAlly",
    "WarmUpInbox":      "WarmUpInbox",
    "LemWarm":          "LemWarm",
    "Trulyinbox":       "Trulyinbox",
    "SmartLead":        "SmartLead",
    "Warmbox":          "Warmbox",
    "GoogleAIMode":     "Google AI Mode",
    "GoogleAIOverview": "Google AI Overview",
}

_TREND_COLORS = {
    "Warmy":     {"color": "#378ADD", "dash": False,  "fill": True,  "width": 2},
    "Mailreach": {"color": "#5F5E5A", "dash": True,   "fill": False, "width": 1.5},
    "Instantly": {"color": "#B4B2A9", "dash": False,  "fill": False, "width": 1.5},
    "Folderly":  {"color": "#D3D1C7", "dash": False,  "fill": False, "width": 1.5},
}

_LLM_LIST = ["GoogleAIOverview", "GoogleAIMode", "ChatGPT", "Gemini", "Perplexity"]
_LLM_CHART_LABELS = ["Google AI Overview", "Google AI Mode", "ChatGPT", "Gemini", "Perplexity"]
_TOPIC_ORDER = ["Email Warmup", "Email Deliverability", "B2B outreach", "Marketing Tools", "Business Solutions"]


def _fmt_date(date_str):
    return datetime.strptime(date_str, "%Y-%m-%d").strftime("%b %-d, %Y")


def _rank_badge(rank):
    if rank == 1:
        bg, fg = "#1D9E75", "#04342C"
    elif rank == 2:
        bg, fg = "#9FE1CB", "#04342C"
    elif rank <= 4:
        bg, fg = "#FAEEDA", "#412402"
    elif rank <= 7:
        bg, fg = "#F09595", "#501313"
    else:
        bg, fg = "#A32D2D", "#FCEBEB"
    return (
        f'<div style="background:{bg};color:{fg};font-weight:500;'
        f'border-radius:3px;padding:4px 0;text-align:center;">#{rank}</div>'
    )


def _delta_span(delta, reverse=False, unit=""):
    """Green when good (positive normally, negative when reverse=True)."""
    if delta is None or delta == 0:
        return '<span style="font-size:12px;color:var(--ct);font-weight:400;">—</span>'
    good = (delta < 0) if reverse else (delta > 0)
    color = "var(--cs)" if good else "var(--cd)"
    sign = "+" if delta > 0 else ""
    arrow = "↑" if delta > 0 else "↓"
    label = f"{arrow}{abs(delta):.2f}{unit}"
    return f'<span style="font-size:12px;color:{color};font-weight:400;">{label}</span>'


def _prev_val(val, unit=""):
    if val is None:
        return '<p style="font-size:11px;color:var(--ct);margin:4px 0 0;">—</p>'
    return f'<p style="font-size:11px;color:var(--ct);margin:4px 0 0;">was {val}{unit}</p>'


def _recommendations(metrics):
    recs = []

    llm_data = metrics["by_llm"]
    ranked = sorted(llm_data.items(), key=lambda x: x[1]["rank"], reverse=True)
    worst_llm, w = ranked[0]
    best_llm, b = ranked[-1]
    recs.append({
        "title": f"Fix {worst_llm} — Warmy is #{w['rank']} there, dragging the average down",
        "body": (
            f"{w['sov']:.2f}% SoV on {worst_llm} vs {b['sov']:.2f}% on {best_llm}. "
            f"{worst_llm} leans on different sources — audit its citations and pursue "
            f"placement on the domains it prefers."
        ),
    })

    topic_data = metrics["by_topic"]
    if topic_data:
        worst_topic, td = max(topic_data.items(), key=lambda x: x[1]["rank"])
        recs.append({
            "title": f"Reclaim {worst_topic} — Warmy #{td['rank']}, {_BRAND_DISPLAY.get(td['leader'], td['leader'])} leads",
            "body": (
                f"Warmy SoV {td['sov']:.2f}% on {worst_topic} queries. "
                f"Build comparison content and pursue review-site placements (G2, Capterra)."
            ),
        })

    return recs[:3]


def _trend_datasets_js(trend):
    parts = []
    for brand in trend["brands"]:
        cfg = _TREND_COLORS.get(brand, {"color": "#999", "dash": False, "fill": False, "width": 1.5})
        data_json = json.dumps(trend["series"][brand])
        display = _BRAND_DISPLAY.get(brand, brand)
        dash = "[4,3]" if cfg["dash"] else "[]"
        fill = "true" if cfg["fill"] else "false"
        bg = f"rgba(55,138,221,0.08)" if brand == "Warmy" else "transparent"
        parts.append(
            f"{{label:{json.dumps(display)},data:{data_json},"
            f"borderColor:{json.dumps(cfg['color'])},borderWidth:{cfg['width']},"
            f"borderDash:{dash},pointRadius:0,tension:0.25,fill:{fill},"
            f"backgroundColor:{json.dumps(bg)}}}"
        )
    return "[" + ",".join(parts) + "]"


def generate_dashboard_html(metrics):
    ov = metrics["overall"]
    trend = metrics["trend"]
    leaderboard = metrics["leaderboard"]
    by_llm = metrics["by_llm"]
    by_topic = metrics["by_topic"]

    today_label = _fmt_date(metrics["date"])
    yest_label = _fmt_date(metrics["yesterday"])

    # --- KPI cards ---
    rank_delta = ov["delta_rank"]
    rank_delta_html = (
        '<span style="font-size:12px;color:var(--ct);font-weight:400;">—</span>'
        if rank_delta is None or rank_delta == 0
        else _delta_span(-rank_delta)  # negate: rank went down = number up = bad
    )
    kpi_cards = f"""
<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:18px;">
  <div style="background:var(--bg2);border-radius:var(--rmd);padding:12px;">
    <p style="font-size:11px;color:var(--cs2);margin:0 0 4px;">Rank in pack</p>
    <p style="font-size:22px;font-weight:500;margin:0;">#{ov['rank']} {rank_delta_html}</p>
    {_prev_val(f"#{ov['yest_rank']}" if ov['yest_rank'] else None)}
  </div>
  <div style="background:var(--bg2);border-radius:var(--rmd);padding:12px;">
    <p style="font-size:11px;color:var(--cs2);margin:0 0 4px;">Share of voice</p>
    <p style="font-size:22px;font-weight:500;margin:0;">{ov['sov']:.2f}% {_delta_span(ov['delta_sov'])}</p>
    {_prev_val(f"{ov['yest_sov']:.2f}%" if ov['yest_sov'] is not None else None)}
  </div>
  <div style="background:var(--bg2);border-radius:var(--rmd);padding:12px;">
    <p style="font-size:11px;color:var(--cs2);margin:0 0 4px;">Mention rate</p>
    <p style="font-size:22px;font-weight:500;margin:0;">{ov['mention_rate']:.1f}% {_delta_span(ov['delta_mention_rate'])}</p>
    {_prev_val(f"{ov['yest_mention_rate']:.1f}%" if ov['yest_mention_rate'] is not None else None)}
  </div>
  <div style="background:var(--bg2);border-radius:var(--rmd);padding:12px;">
    <p style="font-size:11px;color:var(--cs2);margin:0 0 4px;">Avg position</p>
    <p style="font-size:22px;font-weight:500;margin:0;">{"#"+str(ov['avg_position']) if ov['avg_position'] else "—"} {_delta_span(ov['delta_avg_pos'], reverse=True)}</p>
    {_prev_val(f"#{ov['yest_avg_pos']}" if ov['yest_avg_pos'] else None)}
  </div>
</div>"""

    # --- Trend legend ---
    legend_items = []
    for brand in trend["brands"]:
        cfg = _TREND_COLORS.get(brand, {"color": "#999", "dash": False, "width": 1.5})
        current_sov = trend["series"][brand][-1] if trend["series"][brand] else 0.0
        display = _BRAND_DISPLAY.get(brand, brand)
        color = cfg["color"]
        stroke_w = cfg.get("width", 1.5)
        dasharray = "4,3" if cfg.get("dash") else "none"
        svg = (
            f'<svg width="18" height="10" style="flex-shrink:0;" viewBox="0 0 18 10">'
            f'<line x1="0" y1="5" x2="18" y2="5" stroke="{color}" stroke-width="{stroke_w}" stroke-dasharray="{dasharray}"/>'
            f'</svg>'
        )
        legend_items.append(
            f'<span style="display:flex;align-items:center;gap:5px;">'
            f'{svg}{display} {current_sov:.2f}%</span>'
        )
    trend_legend = (
        f'<div style="display:flex;flex-wrap:wrap;gap:14px;margin-bottom:8px;'
        f'font-size:11px;color:var(--cs2);">' + "".join(legend_items) + "</div>"
    )

    # --- LLM table rows ---
    llm_rows = ""
    for llm in _LLM_LIST:
        d = by_llm[llm]
        top = _BRAND_DISPLAY.get(d["top_competitor"], d["top_competitor"])
        display_name = _BRAND_DISPLAY.get(llm, llm)
        llm_rows += f"""<tr style="border-top:0.5px solid var(--brd);">
  <td style="padding:5px 8px;">{display_name}</td>
  <td style="padding:5px 4px;">{_rank_badge(d['rank'])}</td>
  <td style="padding:5px 4px;text-align:center;">{d['sov']:.2f}%</td>
  <td style="padding:5px 4px;text-align:center;">{d['mention_rate']:.0f}%</td>
  <td style="padding:5px 4px;text-align:center;">{_delta_span(d['delta_sov'])}</td>
  <td style="padding:5px 6px;color:var(--cs2);">{top} {d['top_competitor_sov']:.2f}%</td>
</tr>"""

    # LLM chart data (5 LLMs)
    llm_warmy = json.dumps([by_llm[l]["sov"] for l in _LLM_LIST])
    llm_comp = json.dumps([by_llm[l]["top_competitor_sov"] for l in _LLM_LIST])
    llm_max = max(
        max(by_llm[l]["sov"] for l in by_llm),
        max(by_llm[l]["top_competitor_sov"] for l in by_llm),
        1.0,
    ) * 1.15

    # --- Leaderboard chart ---
    leader_labels = json.dumps([_BRAND_DISPLAY.get(b, b) for b, _ in leaderboard])
    leader_values = json.dumps([v for _, v in leaderboard])
    leader_colors = json.dumps(
        ["#378ADD" if b == "Warmy" else "#888780" if leaderboard.index((b, v)) < 3 else "#B4B2A9"
         for b, v in leaderboard]
    )
    leader_max = max((v for _, v in leaderboard), default=1.0) * 1.15

    # --- Recommendations ---
    recs = _recommendations(metrics)
    rec_items = ""
    for i, rec in enumerate(recs, 1):
        rec_items += f"""<div style="display:flex;gap:10px;{'margin-bottom:8px;' if i < len(recs) else ''}">
  <span style="flex-shrink:0;width:20px;height:20px;background:#A32D2D;color:#FCEBEB;border-radius:50%;
    display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:500;">{i}</span>
  <div style="flex:1;">
    <p style="font-size:12px;font-weight:500;color:#501313;margin:0 0 2px;">{rec['title']}</p>
    <p style="font-size:11px;color:#791F1F;margin:0;line-height:1.5;">{rec['body']}</p>
  </div>
</div>"""

    # --- Topic table rows ---
    topic_rows = ""
    ordered_topics = sorted(by_topic.items(), key=lambda x: _TOPIC_ORDER.index(x[0]) if x[0] in _TOPIC_ORDER else 999)
    for topic, d in ordered_topics:
        leader_disp = _BRAND_DISPLAY.get(d["leader"], d["leader"])
        topic_rows += f"""<tr style="border-top:0.5px solid var(--brd);">
  <td style="padding:5px 8px;">{topic}</td>
  <td style="padding:5px 4px;">{_rank_badge(d['rank'])}</td>
  <td style="padding:5px 4px;text-align:center;">{d['sov']:.2f}%</td>
  <td style="padding:5px 4px;text-align:center;">{_delta_span(d['delta_sov'])}</td>
  <td style="padding:5px 6px;color:var(--cs2);">{leader_disp}</td>
</tr>"""

    trend_dates_js = json.dumps(trend["dates"])
    trend_datasets_js = _trend_datasets_js(trend)
    _positive_vals = [v for s in trend["series"].values() for v in s if v > 0]
    trend_y_min = round(min(_positive_vals) * 0.85, 1) if _positive_vals else 0
    _all_vals = [v for s in trend["series"].values() for v in s]
    trend_y_max = round(max(_all_vals) * 1.1, 1) if _all_vals else 1

    n_topics = len(by_topic)
    n_competitors = sum(1 for b, v in leaderboard if b != "Warmy" and v > 0)

    llm_chart_labels_js = json.dumps(_LLM_CHART_LABELS)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=1200">
<style>
  :root {{
    --bg1: #FFFFFF;
    --bg2: #F7F6F3;
    --brd: #E8E7E2;
    --bgi: #EBF3FB;
    --cti: #1A6BB5;
    --ct:  #9B9A96;
    --cs2: #6B6A66;
    --cp:  #1A1A1A;
    --cs:  #1D9E75;
    --cd:  #E24B4A;
    --rlg: 8px;
    --rmd: 5px;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          background: var(--bg2); padding: 16px; }}
  table {{ border-collapse: collapse; }}
</style>
</head>
<body>
<div style="max-width:780px;margin:0 auto;background:var(--bg2);border-radius:var(--rlg);padding:1.25rem;">
  <div style="background:var(--bg1);border-radius:var(--rlg);border:0.5px solid var(--brd);overflow:hidden;">

    <!-- Header -->
    <div style="display:flex;align-items:center;gap:10px;padding:12px 16px;border-bottom:0.5px solid var(--brd);">
      <div style="width:32px;height:32px;border-radius:var(--rmd);background:var(--bgi);display:flex;
          align-items:center;justify-content:center;font-weight:500;font-size:13px;color:var(--cti);">GEO</div>
      <div style="flex:1;">
        <p style="font-weight:500;font-size:14px;margin:0;">Warmy GEO bot <span style="font-size:11px;color:var(--ct);font-weight:400;margin-left:4px;">APP</span></p>
        <p style="font-size:12px;color:var(--cs2);margin:0;">#geo-daily · 9:00 AM</p>
      </div>
      <span style="font-size:11px;color:var(--ct);">{today_label} · vs {yest_label}</span>
    </div>

    <div style="padding:16px;">
      <p style="font-size:15px;font-weight:500;margin:0 0 4px;">Daily GEO standup — Warmy</p>
      <p style="font-size:13px;color:var(--cs2);margin:0 0 16px;">100 prompts · 5 LLMs · US only · {n_competitors} competitors · {n_topics} topics</p>

      <p style="font-size:11px;color:var(--cs2);margin:0 0 6px;">Today vs yesterday</p>
      {kpi_cards}

      <p style="font-size:13px;font-weight:500;margin:0 0 8px;">Share of voice — last 14 days</p>
      {trend_legend}
      <div style="position:relative;width:100%;height:200px;margin-bottom:18px;">
        <canvas id="trendChart"></canvas>
      </div>

      <p style="font-size:13px;font-weight:500;margin:0 0 8px;">Rank by LLM</p>
      <div style="border:0.5px solid var(--brd);border-radius:var(--rmd);overflow:hidden;margin-bottom:12px;">
        <table style="width:100%;font-size:11px;table-layout:fixed;">
          <thead>
            <tr style="background:var(--bg2);">
              <th style="text-align:left;padding:6px 8px;font-weight:500;color:var(--cs2);width:28%;">LLM</th>
              <th style="text-align:center;padding:6px 4px;font-weight:500;color:var(--cs2);width:11%;">Rank</th>
              <th style="text-align:center;padding:6px 4px;font-weight:500;color:var(--cs2);width:13%;">SoV</th>
              <th style="text-align:center;padding:6px 4px;font-weight:500;color:var(--cs2);width:13%;">Mention %</th>
              <th style="text-align:center;padding:6px 4px;font-weight:500;color:var(--cs2);width:12%;">Δ SoV</th>
              <th style="text-align:left;padding:6px 6px;font-weight:500;color:var(--cs2);">Top competitor</th>
            </tr>
          </thead>
          <tbody>{llm_rows}</tbody>
        </table>
      </div>
      <div style="position:relative;width:100%;height:180px;margin-bottom:18px;">
        <canvas id="llmChart"></canvas>
      </div>

      <p style="font-size:13px;font-weight:500;margin:0 0 8px;">Competitor leaderboard</p>
      <div style="position:relative;width:100%;height:{max(200, len(leaderboard) * 28)}px;margin-bottom:18px;">
        <canvas id="leaderChart"></canvas>
      </div>

      <div style="background:#FCEBEB;border:0.5px solid #E24B4A;border-radius:var(--rmd);padding:12px 14px;margin-bottom:18px;">
        <p style="font-size:12px;font-weight:500;color:#501313;margin:0 0 8px;">Top recommendations to focus on</p>
        {rec_items}
      </div>

      <p style="font-size:13px;font-weight:500;margin:0 0 8px;">Warmy's rank by topic</p>
      <div style="border:0.5px solid var(--brd);border-radius:var(--rmd);overflow:hidden;margin-bottom:16px;">
        <table style="width:100%;font-size:11px;table-layout:fixed;">
          <thead>
            <tr style="background:var(--bg2);">
              <th style="text-align:left;padding:6px 8px;font-weight:500;color:var(--cs2);width:34%;">Topic</th>
              <th style="text-align:center;padding:6px 4px;font-weight:500;color:var(--cs2);width:12%;">Rank</th>
              <th style="text-align:center;padding:6px 4px;font-weight:500;color:var(--cs2);width:15%;">Warmy SoV</th>
              <th style="text-align:center;padding:6px 4px;font-weight:500;color:var(--cs2);width:12%;">Δ</th>
              <th style="text-align:left;padding:6px 6px;font-weight:500;color:var(--cs2);">Leader</th>
            </tr>
          </thead>
          <tbody>{topic_rows}</tbody>
        </table>
      </div>

    </div><!-- /padding -->
  </div><!-- /card -->
</div><!-- /outer -->

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>
(function(){{
  const grid = 'rgba(0,0,0,0.06)';
  const tick  = 'rgba(0,0,0,0.6)';

  new Chart(document.getElementById('trendChart'), {{
    type:'line',
    data:{{ labels:{trend_dates_js}, datasets:{trend_datasets_js} }},
    options:{{
      responsive:true, maintainAspectRatio:false,
      plugins:{{ legend:{{display:false}}, tooltip:{{callbacks:{{label:(c)=>` ${{c.dataset.label}}: ${{c.parsed.y.toFixed(2)}}%`}}}} }},
      scales:{{
        x:{{grid:{{display:false}},ticks:{{color:tick,font:{{size:10}},maxRotation:0,autoSkip:true,maxTicksLimit:7}}}},
        y:{{min:{trend_y_min},max:{trend_y_max},grid:{{color:grid,drawBorder:false}},ticks:{{color:tick,font:{{size:10}},callback:(v)=>v.toFixed(1)+'%'}}}}
      }}
    }}
  }});

  new Chart(document.getElementById('llmChart'), {{
    type:'bar',
    data:{{
      labels:{llm_chart_labels_js},
      datasets:[
        {{label:'Warmy',      data:{llm_warmy}, backgroundColor:'#378ADD',borderRadius:3,barThickness:18}},
        {{label:'Top competitor',data:{llm_comp},backgroundColor:'#B4B2A9',borderRadius:3,barThickness:18}}
      ]
    }},
    options:{{
      responsive:true,maintainAspectRatio:false,
      plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:(c)=>` ${{c.dataset.label}}: ${{c.parsed.y.toFixed(2)}}%`}}}}}},
      scales:{{
        x:{{grid:{{display:false}},ticks:{{color:tick,font:{{size:10}}}}}},
        y:{{grid:{{color:grid,drawBorder:false}},ticks:{{color:tick,font:{{size:10}},callback:(v)=>v.toFixed(1)+'%'}},max:{round(llm_max,1)}}}
      }}
    }}
  }});

  new Chart(document.getElementById('leaderChart'), {{
    type:'bar',
    data:{{
      labels:{leader_labels},
      datasets:[{{label:'SoV %',data:{leader_values},backgroundColor:{leader_colors},borderRadius:3,barThickness:18}}]
    }},
    options:{{
      indexAxis:'y',responsive:true,maintainAspectRatio:false,
      plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:(c)=>` ${{c.parsed.x.toFixed(2)}}%`}}}}}},
      scales:{{
        x:{{grid:{{color:grid,drawBorder:false}},ticks:{{color:tick,font:{{size:10}},callback:(v)=>v.toFixed(1)+'%'}},max:{round(leader_max,1)}}},
        y:{{grid:{{display:false}},ticks:{{color:tick,font:{{size:11}}}}}}
      }}
    }}
  }});
}})();
</script>
</body>
</html>"""


def render_to_png(metrics, output_path="dashboard_v2.png"):
    from playwright.sync_api import sync_playwright

    html = generate_dashboard_html(metrics)
    tmp = Path(output_path).with_suffix(".html")
    tmp.write_text(html, encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        page.goto(f"file://{tmp.resolve()}")
        page.wait_for_timeout(800)  # let Chart.js finish rendering
        page.locator("div").first.screenshot(path=output_path)
        browser.close()

    tmp.unlink()
    return output_path
