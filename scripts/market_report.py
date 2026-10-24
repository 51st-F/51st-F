"""抓台股與美股盤後資料，輸出台股看板 tw.svg 和美股清單 us.svg。

圖寬刻意做窄（440px），讓手機上幾乎不用縮小就看得清楚。
每張卡片各自獨立，某一張抓不到資料就跳過，其他卡片照常顯示；只要有任何一張失敗，最後以非零狀態結束。
"""

import datetime
import json
import os
import sys
import traceback
import urllib.request

TWSE_HISTORY_API = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?response=json&date={date}"
TPEX_INDEX_API = "https://www.tpex.org.tw/openapi/v1/tpex_index"
INSTITUTIONAL_API = "https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json"
YAHOO_CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1mo&interval=1d"

# 看板上的美股，(代號, 顯示名稱)
WATCHLIST = [("TSLA", "特斯拉"), ("NVDA", "輝達"), ("SPCX", "SpaceX")]

# 台股慣例：紅漲綠跌
UP, DOWN, FLAT = "#e5534b", "#3fb950", "#8b949e"
FONT = "font-family='-apple-system,Segoe UI,Noto Sans TC,sans-serif'"

WIDTH, GAP, TOP = 440, 10, 34
CARD_W, CARD_H = (WIDTH - GAP) // 2, 104
ROW_H = 58


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def num(s):
    return float(s.replace(",", ""))


def color_of(value):
    return UP if value > 0 else DOWN if value < 0 else FLAT


def arrow_of(value):
    return "▲" if value > 0 else "▼" if value < 0 else "－"


# 以下 *_history 都回傳 (最後一筆的日期 "MM/DD", 收盤序列)
def twse_history(days=22):
    today = datetime.date.today()
    last_month = today.replace(day=1) - datetime.timedelta(days=1)
    rows = []
    for d in (last_month, today):
        data = fetch_json(TWSE_HISTORY_API.format(date=d.strftime("%Y%m01")))
        if data.get("stat") == "OK":
            rows += data["data"]
    return rows[-1][0][-5:], [num(r[4]) for r in rows[-days:]]  # 日期是民國年 "115/10/22"


def tpex_history():
    # 只提供當月資料，月初點數會比較少
    rows = fetch_json(TPEX_INDEX_API)
    date = rows[-1]["Date"]  # "20261022"
    return f"{date[4:6]}/{date[6:]}", [num(r["Close"]) for r in rows]


def us_history(symbol):
    result = fetch_json(YAHOO_CHART_API.format(symbol=symbol))["chart"]["result"][0]
    points = [(t, c) for t, c in zip(result["timestamp"], result["indicators"]["quote"][0]["close"]) if c is not None]
    # 換算成交易所當地日期
    tz = datetime.timezone(datetime.timedelta(seconds=result["meta"]["gmtoffset"]))
    date = datetime.datetime.fromtimestamp(points[-1][0], tz).strftime("%m/%d")
    return date, [c for _, c in points]


def institutional():
    data = fetch_json(INSTITUTIONAL_API)
    net = {r[0]: num(r[3]) / 1e8 for r in data["data"]}  # 換算成億
    return [
        ("外資", net["外資及陸資(不含外資自營商)"] + net["外資自營商"]),
        ("投信", net["投信"]),
        ("自營", net["自營商(自行買賣)"] + net["自營商(避險)"]),
    ]


def mood(pct):
    if pct <= -3:
        return "盤後看完，今晚吃泡麵 🍜"
    if pct <= -1:
        return "還好我盤中沒看 🫠"
    if pct < 0:
        return "小跌，假裝沒看到 🙈"
    if pct == 0:
        return "平盤，跟我的 commit 一樣平 😐"
    if pct < 1:
        return "小漲，穩穩的 🙂"
    if pct < 3:
        return "今天可以加個滷蛋 🥚"
    return "盤後才知道錯過了什麼 🚀"


def text(x, y, s, size, weight=400, fill=FLAT, anchor="start"):
    return f'<text x="{x}" y="{y}" {FONT} font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">{s}</text>'


def card_frame(title, sub, w=CARD_W, h=CARD_H):
    return (
        f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="10" fill="none" stroke="{FLAT}" stroke-opacity="0.35"/>'
        f'<text x="12" y="22" {FONT} font-size="14" font-weight="700" fill="{FLAT}">{title}'
        f'<tspan font-size="11" font-weight="400" dx="5">{sub}</tspan></text>'
    )


def sparkline(values, x, y, w, h, color):
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    xs = [x + i * w / (len(values) - 1) for i in range(len(values))]
    ys = [y + (hi - v) / span * h for v in values]
    line = " ".join(f"{px:.1f},{py:.1f}" for px, py in zip(xs, ys))
    area = f"{xs[0]:.1f},{y + h} {line} {xs[-1]:.1f},{y + h}"
    return (
        f'<polygon points="{area}" fill="{color}" fill-opacity="0.12"/>'
        f'<polyline points="{line}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>'
        f'<circle cx="{xs[-1]:.1f}" cy="{ys[-1]:.1f}" r="3" fill="{color}"/>'
    )


def price_card(title, sub, values, fmt):
    day_pct = (values[-1] / values[-2] - 1) * 100
    month_pct = (values[-1] / values[0] - 1) * 100
    color = color_of(day_pct)
    svg = (
        card_frame(title, sub)
        + text(CARD_W - 12, 22, f"近一月 {month_pct:+.1f}%", 11, anchor="end")
        + f'<text x="12" y="48" {FONT} font-size="19" font-weight="700" fill="{color}">{fmt.format(values[-1])}'
        f'<tspan font-size="13" font-weight="600" dx="6">{arrow_of(day_pct)}{abs(day_pct):.2f}%</tspan></text>'
        + sparkline(values, 12, 60, CARD_W - 24, 32, color_of(month_pct))
    )
    return svg, day_pct


def institutional_card(rows):
    total = sum(v for _, v in rows)
    biggest = max(abs(v) for _, v in rows) or 1
    mid, half = WIDTH / 2, WIDTH / 2 - 100
    parts = [card_frame("三大法人", "買賣超", WIDTH), text(WIDTH - 12, 22, f"合計 {total:+,.0f}億", 11, anchor="end")]
    for i, (name, value) in enumerate(rows):
        y = 44 + i * 22
        bar = abs(value) / biggest * half
        x = mid if value >= 0 else mid - bar
        parts.append(text(12, y + 4, name, 12, 600))
        parts.append(f'<line x1="{mid}" y1="{y - 8}" x2="{mid}" y2="{y + 8}" stroke="{FLAT}" stroke-opacity="0.5"/>')
        parts.append(f'<rect x="{x:.1f}" y="{y - 6}" width="{max(bar, 1):.1f}" height="12" rx="2" fill="{color_of(value)}"/>')
        parts.append(text(WIDTH - 12, y + 4, f"{value:+,.0f}億", 12, 600, color_of(value), "end"))
    return "".join(parts)


def us_row(symbol, name, values):
    day_pct = (values[-1] / values[-2] - 1) * 100
    month_pct = (values[-1] / values[0] - 1) * 100
    color = color_of(day_pct)
    svg = (
        card_frame(symbol, name, WIDTH, ROW_H)
        + text(12, 42, f"近一月 {month_pct:+.1f}%", 11)
        + sparkline(values, 150, 12, 140, ROW_H - 24, color_of(month_pct))
        + text(WIDTH - 12, 28, f"{values[-1]:,.2f}", 17, 700, color, "end")
        + text(WIDTH - 12, 46, f"{arrow_of(day_pct)}{abs(day_pct):.2f}%", 12, 600, color, "end")
    )
    return svg, day_pct


def write_svg(path, headline, date, blocks):
    """blocks 是 (svg, 寬, 高) 的清單，依序由左到右、由上到下排，放不下就換行。"""
    body, x, y, row_h = [text(0, 20, headline, 14, 600)], 0, TOP, 0
    if date:
        body.append(text(WIDTH, 20, f"{date} 收盤", 12, anchor="end"))
    for svg, w, h in blocks:
        if x and x + w > WIDTH:
            x, y, row_h = 0, y + row_h + GAP, 0
        body.append(f'<g transform="translate({x},{y})">{svg}</g>')
        x, row_h = x + w + GAP, max(row_h, h)
    height = y + row_h
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" viewBox="0 0 {WIDTH} {height}">\n' + "\n".join(body) + "\n</svg>\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)
    print(headline)


def run(fetch, failures):
    try:
        return fetch()
    except Exception:
        failures.append(1)
        traceback.print_exc()
        return None


def tw_board(out_dir, failures):
    blocks, headline, date = [], "今天資料抓不到，跟我一樣休息 💤", None
    for title, sub, fetch, fmt in (
        ("台股加權", "TAIEX", twse_history, "{:,.0f}"),
        ("櫃買指數", "TPEx", tpex_history, "{:,.2f}"),
    ):
        result = run(fetch, failures)
        if result:
            date = date or result[0]
            svg, pct = price_card(title, sub, result[1], fmt)
            blocks.append((svg, CARD_W, CARD_H))
            if title == "台股加權":
                headline = f"台股加權 {pct:+.2f}%・{mood(pct)}"
    rows = run(institutional, failures)
    if rows:
        blocks.append((institutional_card(rows), WIDTH, CARD_H))
    write_svg(os.path.join(out_dir, "tw.svg"), headline, date, blocks)


def us_board(out_dir, failures):
    blocks, day_pct, date = [], {}, None
    for symbol, name in WATCHLIST:
        result = run(lambda: us_history(symbol), failures)
        if result:
            date = date or result[0]
            svg, day_pct[symbol] = us_row(symbol, name, result[1])
            blocks.append((svg, WIDTH, ROW_H))
    if day_pct:
        best = max(day_pct, key=day_pct.get)
        worst = min(day_pct, key=day_pct.get)
        headline = f"最會漲 {best} {day_pct[best]:+.2f}% 🚀 最拖 {worst} {day_pct[worst]:+.2f}% 🐢"
    else:
        headline = "美股資料抓不到，昨晚大概也在睡 💤"
    write_svg(os.path.join(out_dir, "us.svg"), headline, date, blocks)


def main(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    failures = []
    tw_board(out_dir, failures)
    us_board(out_dir, failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main(sys.argv[1])
