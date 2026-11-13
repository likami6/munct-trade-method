"""EMA 9/20 cross alerts to Telegram (free, no TradingView plan needed).

Same signal as the Pine strategy: EMA 9 crosses above EMA 20 on a closed candle -> BUY,
crosses below -> SELL. Markets and timeframes are listed in bot/markets.json.

Price sources (prices can differ slightly from your TradingView feed):
  gate        Gate.io USDT perpetuals, no key needed (crypto)
  mexc        MEXC USDT perpetuals, no key needed (crypto; used if Gate fails)
  twelvedata  Twelve Data, free key in TWELVEDATA_API_KEY (XAU/USD)
  yahoo       Yahoo Finance, no key (NQ=F Nasdaq 100 futures for NAS100)

Environment: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TWELVEDATA_API_KEY,
FAST_LEN / SLOW_LEN (default 9 / 20), STATE_FILE (default bot/state.json),
MARKETS_FILE (default bot/markets.json). Run with --test to send a test message.
"""
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

TF_MIN = {"15m": 15, "1h": 60, "4h": 240}
TF_LABEL = {"15m": "15m", "1h": "1H", "4h": "4H"}
WIB = timezone(timedelta(hours=7))
RETRY_GAP = timedelta(minutes=10)  # min time between fetches of one market/timeframe
UA = "Mozilla/5.0 (X11; Linux x86_64) ema-cross-bot"


def env(name, default=None):
    v = os.environ.get(name, "").strip()
    return v if v else default


def http_json(url, data=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def send_telegram(text):
    token, chat = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    res = http_json(f"https://api.telegram.org/bot{token}/sendMessage", data)
    if not res.get("ok"):
        raise RuntimeError(f"Telegram error: {res}")


def utc(ts):
    return datetime.fromtimestamp(int(ts), tz=timezone.utc)


# ---- price sources: each returns [(open_time_utc, close), ...] oldest first, may include the forming candle

def src_gate(symbol, tf):
    q = urllib.parse.urlencode({"contract": symbol, "interval": tf, "limit": 500})
    rows = http_json(f"https://api.gateio.ws/api/v4/futures/usdt/candlesticks?{q}")
    if not isinstance(rows, list):
        raise RuntimeError(f"Gate error: {rows}")
    return [(utc(r["t"]), float(r["c"])) for r in rows]


def src_mexc(symbol, tf):
    iv = {"15m": "Min15", "1h": "Min60", "4h": "Hour4"}[tf]
    end = int(datetime.now(timezone.utc).timestamp())
    q = urllib.parse.urlencode({"interval": iv, "start": end - 500 * TF_MIN[tf] * 60, "end": end})
    res = http_json(f"https://contract.mexc.com/api/v1/contract/kline/{symbol}?{q}")
    if not res.get("success"):
        raise RuntimeError(f"MEXC error: {res}")
    d = res["data"]
    return [(utc(t), float(c)) for t, c in zip(d["time"], d["close"])]


def src_twelvedata(symbol, tf):
    iv = {"15m": "15min", "1h": "1h", "4h": "4h"}[tf]
    q = urllib.parse.urlencode({"symbol": symbol, "interval": iv, "outputsize": 500,
                                "timezone": "UTC", "apikey": env("TWELVEDATA_API_KEY", "")})
    res = http_json(f"https://api.twelvedata.com/time_series?{q}")
    if res.get("status") != "ok":
        raise RuntimeError(f"Twelve Data error: {res.get('message', res)}")
    out = []
    for v in reversed(res["values"]):
        t = datetime.strptime(v["datetime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        out.append((t, float(v["close"])))
    return out


def src_yahoo(symbol, tf):
    # Yahoo has no 4h candles, so 4h is built from 1h candles (UTC 00/04/08/12/16/20).
    iv, rng = ("15m", "30d") if tf == "15m" else ("60m", "180d")
    q = urllib.parse.urlencode({"interval": iv, "range": rng})
    res = http_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?{q}")
    r = res["chart"]["result"][0]
    bars = [(utc(t), c) for t, c in zip(r["timestamp"], r["indicators"]["quote"][0]["close"]) if c is not None]
    if tf != "4h":
        return bars
    groups = {}
    for t, c in bars:
        start = t.replace(minute=0, second=0, microsecond=0, hour=t.hour - t.hour % 4)
        groups[start] = c  # last close in the 4h block
    return sorted(groups.items())


SOURCES = {"gate": src_gate, "mexc": src_mexc, "twelvedata": src_twelvedata, "yahoo": src_yahoo}


def fetch_closed(market, tf, now):
    src = market["source"]
    try:
        bars = SOURCES[src](market["symbol"], tf)
    except Exception:
        if src != "gate":
            raise
        bars = src_mexc(market["symbol"], tf)  # same symbol format on MEXC
    step = timedelta(minutes=TF_MIN[tf])
    mult = market.get("multiplier", 1)
    closed = [(t, c * mult) for t, c in bars if t + step <= now]
    if len(closed) < 60:
        raise RuntimeError(f"only {len(closed)} candles returned")
    return closed


# ---- signal

def ema(values, length):
    """Same as Pine's ta.ema: seeded with the SMA of the first `length` values."""
    out, alpha, prev = [], 2 / (length + 1), None
    for i, x in enumerate(values):
        if i < length - 1:
            out.append(None)
            continue
        prev = sum(values[:length]) / length if prev is None else alpha * x + (1 - alpha) * prev
        out.append(prev)
    return out


def find_crosses(bars, fast_len, slow_len):
    closes = [c for _, c in bars]
    fast, slow = ema(closes, fast_len), ema(closes, slow_len)
    crosses = []
    for i in range(1, len(bars)):
        if None in (fast[i], slow[i], fast[i - 1], slow[i - 1]):
            continue
        if fast[i] > slow[i] and fast[i - 1] <= slow[i - 1]:
            crosses.append((i, 1))
        elif fast[i] < slow[i] and fast[i - 1] >= slow[i - 1]:
            crosses.append((i, -1))
    return crosses


def fmt(price):
    """Enough decimals for both BTC (73561.07) and PEPE (0.0044782)."""
    if price <= 0:
        return str(price)
    return f"{price:.{max(2, 4 - math.floor(math.log10(price)))}f}"


def tp_level(market, price, d):
    if market.get("tp_pips"):
        return price + d * market["tp_pips"] * market.get("pip_size", 0.1)
    if market.get("tp_pct"):
        return price * (1 + d * market["tp_pct"] / 100)
    return None


def tp_note(market, d):
    if market.get("tp_pips"):
        return f" ({market['tp_pips']:g} pips)"
    if market.get("tp_pct"):
        return f" ({'+' if d == 1 else '-'}{market['tp_pct']:g}%)"
    return ""


def format_alert(market, tf_label, d, price, tp, when):
    lines = [f"{'🟢 BUY' if d == 1 else '🔴 SELL'} {market['name']} · {tf_label}",
             "━━━━━━━━━━━━",
             f"💰 Entry: {fmt(price)}"]
    if tp:
        lines.append(f"🎯 TP: {fmt(tp)}{tp_note(market, d)}")
    lines.append(f"🕖 {when}")
    return "\n".join(lines)


def main():
    fast_len, slow_len = int(env("FAST_LEN", 9)), int(env("SLOW_LEN", 20))
    state_file = env("STATE_FILE", "bot/state.json")
    with open(env("MARKETS_FILE", "bot/markets.json")) as f:
        cfg = json.load(f)
    tfs = [tf for tf in cfg.get("timeframes", ["15m"]) if tf in TF_MIN]

    if "--test" in sys.argv:
        names = ", ".join(m["name"] for m in cfg["markets"])
        send_telegram(f"TEST: EMA {fast_len}/{slow_len} bot is connected.\n"
                      f"Timeframes: {', '.join(TF_LABEL[t] for t in tfs)}\nMarkets: {names}")
        print("Test message sent.")
        return

    try:
        with open(state_file) as f:
            state = json.load(f)
        if not isinstance(state.get("markets"), dict):
            state = {"markets": {}}
    except (OSError, ValueError):
        state = {"markets": {}}

    now = datetime.now(timezone.utc)
    for m in cfg["markets"]:
        for tf in tfs:
            key = f"{m['name']}|{tf}"
            st = state["markets"].setdefault(key, {})
            step = timedelta(minutes=TF_MIN[tf])
            seen = datetime.fromisoformat(st["last_bar"]) if st.get("last_bar") else None
            if seen is not None and now < seen + 2 * step:
                continue  # no new candle has closed since the last check
            last_fetch = datetime.fromisoformat(st["last_fetch"]) if st.get("last_fetch") else None
            if last_fetch is not None and now < last_fetch + RETRY_GAP:
                continue  # market closed (weekend, daily break) or data late: don't ask again yet
            st["last_fetch"] = now.isoformat()
            try:
                bars = fetch_closed(m, tf, now)
            except Exception as e:  # one bad market must not stop the others
                print(f"{key}: ERROR {e}")
                if not st.get("error"):
                    send_telegram(f"Bot can't read {m['name']} {TF_LABEL[tf]} prices: {e}")
                st["error"] = True
                continue
            if st.get("error"):
                send_telegram(f"{m['name']} {TF_LABEL[tf]} prices are working again.")
            st["error"] = False
            if seen is not None:
                for i, d in find_crosses(bars, fast_len, slow_len):
                    t, price = bars[i]
                    if t <= seen or t < bars[-1][0] - step:
                        continue  # already sent, or too old to still be useful
                    tp = tp_level(m, price, d)
                    closed_at = (t + step).astimezone(WIB).strftime("%d %b %H:%M")
                    late = " (late)" if t < bars[-1][0] else ""
                    msg = format_alert(m, TF_LABEL[tf], d, price, tp, closed_at + " WIB" + late)
                    send_telegram(msg)
                    print("Sent:", msg.replace("\n", " | "))
            st["last_bar"] = bars[-1][0].isoformat()
            print(f"{key}: checked up to {st['last_bar']} close {fmt(bars[-1][1])}")

    os.makedirs(os.path.dirname(state_file) or ".", exist_ok=True)
    with open(state_file, "w") as f:
        json.dump(state, f, indent=1)


if __name__ == "__main__":
    main()
