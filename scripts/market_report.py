"""抓台股盤後資料，輸出 shields.io endpoint badge 用的 JSON 和自選看板 SVG。

每一項各自獨立，某一項抓不到不影響其他項目；只要有任何一項失敗，最後以非零狀態結束。
"""

import datetime
import json
import os
import sys
import traceback
import urllib.request

TWSE_INDEX_API = "https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX"
TWSE_HISTORY_API = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?response=json&date={date}"
TPEX_INDEX_API = "https://www.tpex.org.tw/openapi/v1/tpex_index"
INSTITUTIONAL_API = "https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json"
YAHOO_CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1mo&interval=1d"

# 看板上的美股，(代號, 顯示名稱)
WATCHLIST = [("TSLA", "特斯拉"), ("NVDA", "輝達"), ("SPCX", "SpaceX")]

# 台股慣例：紅漲綠跌
UP, DOWN, FLAT = "#e5534b", "#3fb950", "#8b949e"


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


def write_badge(path, label, message, value):
    badge = {"schemaVersion": 1, "label": label, "message": message, "color": color_of(value)[1:]}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(badge, f, ensure_ascii=False)
    print(badge)


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


def twse_badge(out_dir):
    rows = fetch_json(TWSE_INDEX_API)
    row = next(r for r in rows if r["指數"] == "發行量加權股價指數")
    # 日期是民國年，例如 1151022
    month, day = row["日期"][-4:-2], row["日期"][-2:]
    change = (-1 if row["漲跌"] == "-" else 1) * num(row["漲跌點數"])
    pct = float(row["漲跌百分比"])
    message = f"{num(row['收盤指數']):,.2f} {arrow_of(change)}{abs(change):,.2f} ({pct:+.2f}%)・{mood(pct)}"
    write_badge(os.path.join(out_dir, "twse.json"), f"台股加權 {month}/{day}", message, change)


def tpex_badge(out_dir):
    row = fetch_json(TPEX_INDEX_API)[-1]
    close, change = num(row["Close"]), num(row["Change"])
    pct = change / (close - change) * 100
    message = f"{close:,.2f} {arrow_of(change)}{abs(change):,.2f} ({pct:+.2f}%)"
    write_badge(os.path.join(out_dir, "tpex.json"), f"櫃買指數 {row['Date'][4:6]}/{row['Date'][6:]}", message, change)


def institutional_badge(out_dir):
    data = fetch_json(INSTITUTIONAL_API)
    net = {r[0]: num(r[3]) / 1e8 for r in data["data"]}  # 換算成億
    foreign = net["外資及陸資(不含外資自營商)"] + net["外資自營商"]
    trust = net["投信"]
    dealer = net["自營商(自行買賣)"] + net["自營商(避險)"]
    total = net["合計"]
    quip = "外資又在提款了 🏧" if foreign < 0 else "外資進場，我還在睡 😴"
    message = f"外資 {foreign:+,.1f}億｜投信 {trust:+,.1f}億｜自營 {dealer:+,.1f}億・{quip}"
    date = data["date"]
    write_badge(os.path.join(out_dir, "institutional.json"), f"三大法人 {date[4:6]}/{date[6:]}", message, total)


def twse_history(days=22):
    today = datetime.date.today()
    last_month = today.replace(day=1) - datetime.timedelta(days=1)
    rows = []
    for d in (last_month, today):
        data = fetch_json(TWSE_HISTORY_API.format(date=d.strftime("%Y%m01")))
        if data.get("stat") == "OK":
            rows += [(r[0][4:], num(r[4])) for r in data["data"]]  # ("10/22", 46041.43)
    return rows[-days:]


def us_history(symbol):
    result = fetch_json(YAHOO_CHART_API.format(symbol=symbol))["chart"]["result"][0]
    closes = result["indicators"]["quote"][0]["close"]
    return [c for c in closes if c is not None]


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


def watchlist_chart(out_dir):
    # (名稱, 副標, 收盤序列, 價格格式)
    cards = [("台股加權", "TAIEX", [v for _, v in twse_history()], "{:,.0f}")]
    for symbol, name in WATCHLIST:
        cards.append((symbol, name, us_history(symbol), "{:,.2f}"))

    day_pct = {c[0]: (c[2][-1] / c[2][-2] - 1) * 100 for c in cards}
    best = max(day_pct, key=day_pct.get)
    worst = min(day_pct, key=day_pct.get)
    headline = f"今天最會漲：{best} {day_pct[best]:+.2f}% 🚀　最拖：{worst} {day_pct[worst]:+.2f}% 🐢"

    card_w, card_h, gap, top = 290, 112, 12, 34
    w, h = card_w * 2 + gap, top + card_h * 2 + gap
    font = "font-family='-apple-system,Segoe UI,Noto Sans TC,sans-serif'"
    parts = [f'<text x="0" y="20" {font} font-size="14" font-weight="600" fill="{FLAT}">{headline}</text>']

    for i, (name, sub, values, fmt) in enumerate(cards):
        cx = (i % 2) * (card_w + gap)
        cy = top + (i // 2) * (card_h + gap)
        pct = day_pct[name]
        month_pct = (values[-1] / values[0] - 1) * 100
        color = color_of(pct)
        parts.append(
            f'<g transform="translate({cx},{cy})">'
            f'<rect x="0.5" y="0.5" width="{card_w - 1}" height="{card_h - 1}" rx="10" fill="none" stroke="{FLAT}" stroke-opacity="0.35"/>'
            f'<text x="14" y="24" {font} font-size="14" font-weight="700" fill="{FLAT}">{name}'
            f'<tspan font-size="11" font-weight="400" dx="6">{sub}</tspan></text>'
            f'<text x="{card_w - 14}" y="24" {font} font-size="11" fill="{FLAT}" text-anchor="end">近一月 {month_pct:+.1f}%</text>'
            f'<text x="14" y="52" {font} font-size="20" font-weight="700" fill="{color}">{fmt.format(values[-1])}'
            f'<tspan font-size="13" font-weight="600" dx="8">{arrow_of(pct)}{abs(pct):.2f}%</tspan></text>'
            + sparkline(values, 14, 64, card_w - 28, 36, color_of(month_pct))
            + "</g>"
        )

    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">\n' + "\n".join(parts) + "\n</svg>\n"
    with open(os.path.join(out_dir, "watchlist.svg"), "w", encoding="utf-8") as f:
        f.write(svg)
    print(headline)


def main(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    failed = False
    for job in (twse_badge, tpex_badge, institutional_badge, watchlist_chart):
        try:
            job(out_dir)
        except Exception:
            failed = True
            print(f"{job.__name__} 失敗：", file=sys.stderr)
            traceback.print_exc()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main(sys.argv[1])
