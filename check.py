import os
import re
import json
import time
import urllib.request
import urllib.parse
import urllib.error

# ==========================================
# CONFIGURATION
# ==========================================

SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
]

CHAT_ID = "7027061012"

BINANCE_URL = "https://data-api.binance.vision/api/v3/klines"
OKX_URL = "https://www.okx.com/api/v5/market/candles"

FRESHNESS_SECONDS = 12 * 60

INTERVAL_15M = 15 * 60 * 1000
INTERVAL_45M = 45 * 60 * 1000

# ==========================================
# TELEGRAM TOKEN
# ==========================================

def get_telegram_token():
    raw = os.environ.get("TG_TOKEN", "")

    match = re.search(
        r"\d{8,12}:[A-Za-z0-9_-]{30,}",
        raw
    )

    if not match:
        return None

    return match.group(0)


# ==========================================
# HTTP REQUEST
# ==========================================

def http_get(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "CandleAlert/1.0",
            "Accept": "application/json"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=15
    ) as response:
        return json.loads(response.read().decode("utf-8"))


def http_post(url, payload):
    data = urllib.parse.urlencode(payload).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "CandleAlert/1.0"
        },
        method="POST"
    )

    with urllib.request.urlopen(
        request,
        timeout=15
    ) as response:
        return response.status


# ==========================================
# BINANCE DATA
# ==========================================

def get_binance_candles(symbol):

    params = urllib.parse.urlencode({
        "symbol": symbol,
        "interval": "15m",
        "limit": 30
    })

    url = f"{BINANCE_URL}?{params}"

    data = http_get(url)

    if not isinstance(data, list):
        raise ValueError("Invalid Binance response")

    now_ms = int(time.time() * 1000)

    candles = []

    for item in data:

        if not isinstance(item, list) or len(item) < 7:
            continue

        open_time = int(item[0])
        open_price = float(item[1])
        close_price = float(item[4])
        close_time = int(item[6])

        # Ignore incomplete 15m candles
        if close_time >= now_ms:
            continue

        candles.append({
            "time": open_time,
            "open": open_price,
            "close": close_price,
            "confirmed": True
        })

    return candles


# ==========================================
# OKX FALLBACK DATA
# ==========================================

def get_okx_candles(symbol):

    if not symbol.endswith("USDT"):
        raise ValueError("Unsupported symbol")

    base = symbol[:-4]
    inst_id = f"{base}-USDT"

    params = urllib.parse.urlencode({
        "instId": inst_id,
        "bar": "15m",
        "limit": 30
    })

    url = f"{OKX_URL}?{params}"

    data = http_get(url)

    if data.get("code") != "0":
        raise ValueError("OKX API error")

    candles = []

    for item in data.get("data", []):

        if len(item) < 9:
            continue

        # OKX confirmation flag:
        # 1 = completed candle
        if str(item[8]) != "1":
            continue

        candles.append({
            "time": int(item[0]),
            "open": float(item[1]),
            "close": float(item[4]),
            "confirmed": True
        })

    return candles


# ==========================================
# DATA SOURCE WITH FALLBACK
# ==========================================

def get_market_data(symbol):

    try:
        candles = get_binance_candles(symbol)

        if len(candles) >= 9:
            return candles

    except Exception:
        pass

    try:
        candles = get_okx_candles(symbol)

        if len(candles) >= 9:
            return candles

    except Exception:
        pass

    return []


# ==========================================
# BUILD UTC-ALIGNED 45M CANDLES
# ==========================================

def build_45m_candles(candles):

    now_ms = int(time.time() * 1000)

    grouped = {}

    for candle in candles:

        if not candle["confirmed"]:
            continue

        open_time = candle["time"]

        # UTC-aligned 45-minute bucket
        bucket = (
            open_time // INTERVAL_45M
        ) * INTERVAL_45M

        expected_time = bucket + (
            (open_time - bucket) // INTERVAL_15M
        ) * INTERVAL_15M

        # Accept only exact 15m boundaries
        if open_time != expected_time:
            continue

        if open_time not in (
            bucket,
            bucket + INTERVAL_15M,
            bucket + 2 * INTERVAL_15M
        ):
            continue

        if bucket not in grouped:
            grouped[bucket] = {}

        grouped[bucket][open_time] = candle

    result = []

    for bucket, parts in grouped.items():

        expected = [
            bucket,
            bucket + INTERVAL_15M,
            bucket + 2 * INTERVAL_15M
        ]

        # All three 15m candles must exist
        if not all(t in parts for t in expected):
            continue

        # The entire 45m candle must be closed
        candle_end = bucket + INTERVAL_45M

        if now_ms < candle_end:
            continue

        first = parts[expected[0]]
        last = parts[expected[2]]

        result.append({
            "time": bucket,
            "end": candle_end,
            "open": first["open"],
            "close": last["close"]
        })

    result.sort(key=lambda x: x["time"])

    return result


# ==========================================
# SIGNAL DETECTION
# ==========================================

def detect_signal(candles):

    if len(candles) < 3:
        return None

    last_three = candles[-3:]

    # All three must be consecutive 45m candles
    for i in range(1, 3):

        difference = (
            last_three[i]["time"] -
            last_three[i - 1]["time"]
        )

        if difference != INTERVAL_45M:
            return None

    now_ms = int(time.time() * 1000)

    latest = last_three[-1]

    # Freshness validation
    age_ms = now_ms - latest["end"]

    if age_ms < 0:
        return None

    if age_ms > FRESHNESS_SECONDS * 1000:
        return None

    # Green signal
    if all(
        c["close"] > c["open"]
        for c in last_three
    ):
        return "green"

    # Red signal
    if all(
        c["close"] < c["open"]
        for c in last_three
    ):
        return "red"

    return None


# ==========================================
# TELEGRAM NOTIFICATION
# ==========================================

def send_telegram(message, token):

    url = (
        f"https://api.telegram.org/bot{token}/sendMessage"
    )

    try:
        status = http_post(
            url,
            {
                "chat_id": CHAT_ID,
                "text": message
            }
        )

        return status == 200

    except Exception:
        return False


# ==========================================
# MAIN EXECUTION
# ==========================================

def main():

    token = get_telegram_token()

    if not token:
        return

    for symbol in SYMBOLS:

        try:

            market_data = get_market_data(symbol)

            if not market_data:
                continue

            candles_45m = build_45m_candles(
                market_data
            )

            signal = detect_signal(
                candles_45m
            )

            if signal == "green":

                message = (
                    f"🟢 {symbol}: "
                    "3 green candles (45m)"
                )

                send_telegram(message, token)

            elif signal == "red":

                message = (
                    f"🔴 {symbol}: "
                    "3 red candles (45m)"
                )

                send_telegram(message, token)

        except Exception:
            continue


if __name__ == "__main__":
    main()
