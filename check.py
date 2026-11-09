import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request


# ====== EDIT HERE ======
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
CHAT_ID = "7027061012"
# =======================

MS15 = 15 * 60 * 1000
MS45 = 45 * 60 * 1000
FRESH_MS = 12 * 60 * 1000  # alert only if the 45m candle closed within last 12 min


def http_get_json(url, params):
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"User-Agent": "candle-alert"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def candles_binance(symbol):
    rows = http_get_json(
        "https://data-api.binance.vision/api/v3/klines",
        {"symbol": symbol, "interval": "15m", "limit": 30},
    )
    return [(int(r[0]), float(r[1]), float(r[4]), int(r[6])) for r in rows]


def candles_okx(symbol):
    inst = symbol[:-4] + "-USDT"
    data = http_get_json(
        "https://www.okx.com/api/v5/market/candles",
        {"instId": inst, "bar": "15m", "limit": 30},
    )
    out = []
    for r in data["data"]:
        if r[8] == "1":
            t = int(r[0])
            out.append((t, float(r[1]), float(r[4]), t + MS15 - 1))
    out.sort()
    return out


def get_candles(symbol):
    for fetch in (candles_binance, candles_okx):
        try:
            rows = fetch(symbol)
            if rows:
                return rows
        except Exception as e:
            print("ERROR", symbol, fetch.__name__, type(e).__name__, file=sys.stderr)
    return None


def check_symbol(symbol, now_ms):
    rows = get_candles(symbol)
    if not rows:
        return None
    groups = {}
    for open_ms, o, c, close_ms in rows:
        if close_ms < now_ms:  # drops the still-open candle
            groups.setdefault(open_ms // MS45, []).append((open_ms, o, c))
    full = sorted(b for b, g in groups.items() if len(g) == 3)
    if len(full) < 3:
        return None
    last3 = full[-3:]
    if last3[2] - last3[0] != 2:
        return None
    age = now_ms - (last3[2] + 1) * MS45
    if age < 0 or age > FRESH_MS:
        return None
    bars = []
    for b in last3:
        g = sorted(groups[b])
        bars.append((g[0][1], g[-1][2]))  # (open of first, close of last)
    if all(c > o for o, c in bars):
        return "green"
    if all(c < o for o, c in bars):
        return "red"
    return None


def send_telegram(token, text):
    url = "https://api.telegram.org/bot" + token + "/sendMessage"
    data = urllib.parse.urlencode({"chat_id": CHAT_ID, "text": text}).encode()
    try:
        req = urllib.request.Request(url, data=data, method="POST")
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        print("ERROR telegram send failed:", type(e).__name__, file=sys.stderr)


def main():
    m = re.search(r"\d{8,12}:[A-Za-z0-9_-]{30,}", os.environ.get("TG_TOKEN", ""))
    if not m:
        print("ERROR: TG_TOKEN missing or wrong format", file=sys.stderr)
        sys.exit(1)
    token = m.group(0)
    now_ms = int(time.time() * 1000)
    for symbol in SYMBOLS:
        result = check_symbol(symbol, now_ms)
        if result == "green":
            send_telegram(token, "🟢 " + symbol + ": 3 green candles (45m)")
        elif result == "red":
            send_telegram(token, "🔴 " + symbol + ": 3 red candles (45m)")


if __name__ == "__main__":
    main()
