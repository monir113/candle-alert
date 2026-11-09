import os, requests

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TOKEN = os.environ["TG_TOKEN"].strip().strip("<>").strip()
if TOKEN.lower().startswith("bot"):
    TOKEN = TOKEN[3:]
CHAT = os.environ["TG_CHAT"].strip()
M15 = 15 * 60 * 1000
M45 = 45 * 60 * 1000

# diagnostic (token dekhay na)
print("token length:", len(TOKEN), "| colons:", TOKEN.count(":"), "| starts with digit:", TOKEN[:1].isdigit())
print("chat id is number:", CHAT.lstrip("-").isdigit(), "| chat length:", len(CHAT))
print("getMe:", requests.get(f"https://api.telegram.org/bot{TOKEN}/getMe").status_code)

def tg(msg):
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      data={"chat_id": CHAT, "text": msg})
    print(r.status_code, r.text)

tg("test ok")

for s in SYMBOLS:
    r = requests.get("https://data-api.binance.vision/api/v3/klines",
                     params={"symbol": s, "interval": "15m", "limit": 30}).json()
    now = r[-1][6]
    r = [k for k in r if k[6] < now]
    if (r[-1][0] + M15) % M45 != 0:
        continue

    buckets = {}
    for k in r:
        buckets.setdefault(k[0] // M45, []).append(k)
    last3 = [b for b in list(buckets.values())[-3:] if len(b) == 3]
    if len(last3) < 3:
        continue

    colors = [float(b[-1][4]) > float(b[0][1]) for b in last3]
    if all(colors):
        tg(f"🟢 {s}: 3 green candles (45m)")
    elif not any(colors):
        tg(f"🔴 {s}: 3 red candles (45m)")
