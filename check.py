import os
import re
import sys
import json
import time
import urllib.request
import urllib.parse
import urllib.error

# ====== EDIT ONLY THIS LIST ======
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
# =================================

CHAT_ID = "7027061012"

M15 = 15 * 60 * 1000
M45 = 45 * 60 * 1000
FRESH_MS = 12 * 60 * 1000  # alert only within 12 min after 45m close

BINANCE_URL = "https://data-api.binance.vision/api/v3/klines"
OKX_URL = "https://www.okx.com/api/v5/market/candles"


def http_get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "candle-alert"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_binance(symbol, now_ms):
    q = urllib.parse.urlencode(
        {"symbol": symbol, "interval": "15m", "limit": 30}
    )
    rows = http_get_json(BINANCE_URL + "?" + q)
    out = []
    for r in rows:
        open_ms = int(r[0])
        close_ms = int(r[6])
        if close_ms >= now_ms:  # still-open candle, drop
            continue
        out.append((open_ms, float(r[1]), float(r[4])))
    return out


def get_okx(symbol, now_ms):
    base = symbol[:-4] if symbol.endswith("USDT") else symbol
    q = urllib.parse.urlencode(
        {"instId": base + "-USDT", "bar": "15m", "limit": 30}
    )
    data = http_get_json(OKX_URL + "?" + q)
    out = []
    for r in data.get("data", []):
        open_ms = int(r[0])
        if r[8] != "1":  # not confirmed/closed
            continue
        if open_ms + M15 > now_ms:
            continue
        out.append((open_ms, float(r[1]), float(r[4])))
    return out


def get_candles(symbol, now_ms):
    try:
        c = get_binance(symbol, now_ms)
        if c:
            return sorted(c)
    except Exception:
        pass
    try:
        c = get_okx(symbol, now_ms)
        if c:
            return sorted(c)
    except Exception:
        pass
    return []


def build_45m(candles):
    """Return list of complete 45m candles: (start_ms, open, close)."""
    buckets = {}
    for open_ms, o, c in candles:
        start = (open_ms // M45) * M45  # aligned to 00:00 UTC
        buckets.setdefault(start, []).append((open_ms, o, c))
    result = []
    for start in sorted(buckets):
        items = sorted(buckets[start])
        expected = [start, start + M15, start + 2 * M15]
        if [i[0] for i in items] != expected:
            continue  # incomplete 45m candle
        result.append((start, items[0][1], items[-1][2]))
    return result


def evaluate(symbol, now_ms):
    candles = get_candles(symbol, now_ms)
    if not candles:
        return None
    c45 = build_45m(candles)
    if len(c45) < 3:
        return None
    last3 = c45[-3:]
    if last3[1][0] - last3[0][0] != M45 or last3[2][0] - last3[1][0] != M45:
        return None
    close_time = last3[2][0] + M45
    age = now_ms - close_time
    if age < 0 or age > FRESH_MS:
        return None
    if all(c[2] > c[1] for c in last3):
        return "\U0001F7E2 " + symbol + ": 3 green candles (45m)"
    if all(c[2] < c[1] for c in last3):
        return "\U0001F534 " + symbol + ": 3 red candles (45m)"
    return None


def get_token():
    raw = os.environ.get("TG_TOKEN", "")
    m = re.search(r"\d{8,12}:[A-Za-z0-9_-]{30,}", raw)
    return m.group(0) if m else None


def send_telegram(token, text):
    url = "https://api.telegram.org/bot" + token + "/sendMessage"
    body = urllib.parse.urlencode(
        {"chat_id": CHAT_ID, "text": text}
    ).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"User-Agent": "candle-alert"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception:
        print("Telegram send failed")
        return False


def main():
    token = get_token()
    if not token:
        print("TG_TOKEN missing or invalid format")
        sys.exit(1)
    now_ms = int(time.time() * 1000)
    for symbol in SYMBOLS:
        try:
            msg = evaluate(symbol, now_ms)
            if msg:
                send_telegram(token, msg)
        except Exception:
            print("Error while checking " + symbol)


if __name__ == "__main__":
    main()
