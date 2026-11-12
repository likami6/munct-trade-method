"""EMA 9/20 cross alerts to Telegram (free, no TradingView plan needed).

Same signal as the Pine strategy: EMA 9 crosses above EMA 20 on a closed candle -> BUY,
crosses below -> SELL. Prices come from Twelve Data (free API key), so they can differ
by a few cents from your TradingView broker feed.

Settings come from environment variables (GitHub secrets / variables):
  TELEGRAM_BOT_TOKEN  (required) token from @BotFather
  TELEGRAM_CHAT_ID    (required) your chat id
  TWELVEDATA_API_KEY  (required) free key from twelvedata.com
  SYMBOL              default XAU/USD
  INTERVAL            default 15min  (1min 5min 15min 30min 45min 1h 2h 4h 1day)
  FAST_LEN / SLOW_LEN default 9 / 20
  TP_PIPS / PIP_SIZE  default 100 / 0.1  (0 pips = no TP in the message)
  STATE_FILE          default bot/state.json
Run with --test to just send a test message.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

INTERVAL_MIN = {"1min": 1, "5min": 5, "15min": 15, "30min": 30, "45min": 45,
                "1h": 60, "2h": 120, "4h": 240, "1day": 1440}


def env(name, default=None):
    v = os.environ.get(name, "").strip()
    return v if v else default


def http_json(url, data=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "ema-cross-bot"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def send_telegram(text):
    token, chat = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    res = http_json(f"https://api.telegram.org/bot{token}/sendMessage", data)
    if not res.get("ok"):
        raise RuntimeError(f"Telegram error: {res}")


def fetch_closed_bars(symbol, interval, now):
    """Closed candles, oldest first, as (open_time_utc, close)."""
    q = urllib.parse.urlencode({"symbol": symbol, "interval": interval, "outputsize": 500,
                                "timezone": "UTC", "apikey": env("TWELVEDATA_API_KEY")})
    res = http_json(f"https://api.twelvedata.com/time_series?{q}")
    if res.get("status") != "ok":
        raise RuntimeError(f"Twelve Data error: {res.get('message', res)}")
    step = timedelta(minutes=INTERVAL_MIN[interval])
    bars = []
    for v in reversed(res["values"]):
        fmt = "%Y-%m-%d %H:%M:%S" if " " in v["datetime"] else "%Y-%m-%d"
        t = datetime.strptime(v["datetime"], fmt).replace(tzinfo=timezone.utc)
        if t + step <= now:  # drop the candle that is still forming
            bars.append((t, float(v["close"])))
    return bars


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
    return crosses, fast, slow


def main():
    symbol = env("SYMBOL", "XAU/USD")
    interval = env("INTERVAL", "15min")
    fast_len, slow_len = int(env("FAST_LEN", 9)), int(env("SLOW_LEN", 20))
    tp_pips, pip_size = float(env("TP_PIPS", 100)), float(env("PIP_SIZE", 0.1))
    state_file = env("STATE_FILE", "bot/state.json")

    if "--test" in sys.argv:
        send_telegram(f"TEST: EMA {fast_len}/{slow_len} bot is connected ({symbol}, {interval}).")
        print("Test message sent.")
        return

    now = datetime.now(timezone.utc)
    bars = fetch_closed_bars(symbol, interval, now)
    crosses, fast, slow = find_crosses(bars, fast_len, slow_len)
    last_t = bars[-1][0]

    try:
        with open(state_file) as f:
            seen = datetime.fromisoformat(json.load(f)["last_bar"])
    except (OSError, ValueError, KeyError):
        seen = None  # first run: remember where we are, don't replay old crosses

    step = timedelta(minutes=INTERVAL_MIN[interval])
    if seen is not None:
        for i, d in crosses:
            t, price = bars[i]
            if t <= seen:
                continue
            side = "BUY" if d == 1 else "SELL"
            tp = f" | TP {price + d * tp_pips * pip_size:.2f}" if tp_pips > 0 else ""
            local = (t + step).astimezone(timezone(timedelta(hours=7))).strftime("%d %b %H:%M")
            late = " (late)" if t < last_t else ""
            msg = (f"{side} {symbol} ~{price:.2f}{tp} (EMA {fast_len}/{slow_len} cross, {interval}, "
                   f"candle closed {local} WIB){late}")
            send_telegram(msg)
            print("Sent:", msg)

    os.makedirs(os.path.dirname(state_file) or ".", exist_ok=True)
    with open(state_file, "w") as f:
        json.dump({"last_bar": last_t.isoformat()}, f)
    print(f"Checked up to {last_t.isoformat()} | close {bars[-1][1]} | "
          f"EMA{fast_len} {fast[-1]:.2f} EMA{slow_len} {slow[-1]:.2f}")


if __name__ == "__main__":
    main()
