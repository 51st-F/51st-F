"""抓台股加權指數盤後資料，輸出 shields.io endpoint badge 用的 JSON。"""

import json
import sys
import urllib.request

API = "https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX"
INDEX_NAME = "發行量加權股價指數"


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


def main(out_path):
    with urllib.request.urlopen(API, timeout=30) as resp:
        rows = json.load(resp)
    row = next(r for r in rows if r["指數"] == INDEX_NAME)

    # 日期是民國年，例如 1151022
    roc_date = row["日期"]
    month, day = roc_date[-4:-2], roc_date[-2:]
    sign = -1 if row["漲跌"] == "-" else 1
    change = sign * float(row["漲跌點數"].replace(",", ""))
    pct = float(row["漲跌百分比"])
    close = float(row["收盤指數"].replace(",", ""))

    # 台股慣例：紅漲綠跌
    arrow, color = ("▲", "red") if change > 0 else ("▼", "green") if change < 0 else ("－", "lightgrey")
    badge = {
        "schemaVersion": 1,
        "label": f"台股加權 {month}/{day}",
        "message": f"{close:,.2f} {arrow}{abs(change):,.2f} ({pct:+.2f}%)・{mood(pct)}",
        "color": color,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(badge, f, ensure_ascii=False)
    print(badge)


if __name__ == "__main__":
    main(sys.argv[1])
