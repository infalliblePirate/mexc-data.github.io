import json, os, time, requests, pandas as pd

# US jobs report release days (report month); release is at 15:30 Kyiv time
DATES = {"2026-09-04": "Aug", "2026-08-07": "Jul", "2026-07-02": "Jun", "2026-06-05": "May"}
# MEXC perpetuals with 500x-1000x max leverage: name -> (CoinAPI id, MEXC tick size, price decimals, max leverage)
COINS = {"Gold": ("MEXCFTS_PERP_XAU_USDT", 0.01, 2, 1000),
         "Gold XAUT": ("MEXCFTS_PERP_XAUT_USDT", 0.1, 1, 1000),
         "Silver": ("MEXCFTS_PERP_SILVER_USDT", 0.01, 2, 1000),
         "Bitcoin": ("MEXCFTS_PERP_BTC_USDT", 0.1, 1, 500),
         "Ether": ("MEXCFTS_PERP_ETH_USDT", 0.01, 2, 500)}
FROM, TO = "15:28:00", "15:35:00"            # window around the release, Kyiv time
TZ = "Europe/Kyiv"
KEY = os.environ.get("COINAPI_KEY")          # CoinAPI / APIBricks key
CACHE = "cache"


def load(coin, date):
    # MEXC 1s bars via CoinAPI, cached per coin + date so each is only downloaded once
    path = f"{CACHE}/{coin}_{date}_{FROM[:5].replace(':', '')}-{TO[:5].replace(':', '')}.json"
    if not os.path.exists(path):
        if not KEY: raise SystemExit("Set COINAPI_KEY to download data")
        start = pd.Timestamp(f"{date} {FROM}", tz=TZ).tz_convert("UTC")
        end = pd.Timestamp(f"{date} {TO}", tz=TZ).tz_convert("UTC")
        for wait in (1, 2, 5, 10, 20, 0):     # retry when CoinAPI rate-limits (429)
            r = requests.get(f"https://rest.coinapi.io/v1/ohlcv/{COINS[coin][0]}/history", headers={"X-CoinAPI-Key": KEY},
                             timeout=60, params=dict(period_id="1SEC", limit=10000,
                                                     time_start=start.strftime("%Y-%m-%dT%H:%M:%S"),
                                                     time_end=end.strftime("%Y-%m-%dT%H:%M:%S")))
            if r.status_code != 429 or not wait: break
            time.sleep(wait)
        r.raise_for_status()
        os.makedirs(CACHE, exist_ok=True)
        json.dump(r.json(), open(path, "w"))
        print(f"{coin} {date}: downloaded {len(r.json())} bars")
    # MEXC's chart shows volume as USDT turnover; CoinAPI gives coins (oz), so multiply by the
    # second's typical price (H+L+C)/3 -- matches MEXC's official minute turnover within 0.02%
    rows = {int(pd.Timestamp(x["time_period_start"]).timestamp() * 1000):
            [x["price_open"], x["price_high"], x["price_low"], x["price_close"],
             round(x["volume_traded"] * (x["price_high"] + x["price_low"] + x["price_close"]) / 3)]
            for x in json.load(open(path))}
    # rebuild the way MEXC draws 1s candles: every candle opens at the previous close
    # (so high/low include it), and a second with no trades is flat at that close
    end = int(pd.Timestamp(f"{date} {TO}", tz=TZ).timestamp() * 1000)
    bars = []
    for t in range(min(rows), end, 1000):
        if not bars:
            bars.append([t, *rows[t]])
            continue
        prev = bars[-1][4]
        if t in rows:
            _, h, l, c, v = rows[t]
            bars.append([t, prev, max(h, prev), min(l, prev), c, v])
        else:
            bars.append([t, prev, prev, prev, prev, 0])
    return bars


data = {"dates": [{"date": d, "month": m, "release": int(pd.Timestamp(f"{d} 15:30", tz=TZ).timestamp() * 1000)}
                  for d, m in DATES.items()],
        "coins": [{"name": c, "symbol": s.split("_")[2] + "/USDT", "tick": tick, "decimals": dec, "leverage": lev,
                   "days": {d: load(c, d) for d in DATES}}
                  for c, (s, tick, dec, lev) in COINS.items()]}
# data.js is loaded by index.html with a plain <script> tag, so the page needs no server
open("data.js", "w").write("window.DATA = " + json.dumps(data, separators=(",", ":")) + ";\n")
print(f"wrote data.js ({os.path.getsize('data.js') // 1024} KB)")
