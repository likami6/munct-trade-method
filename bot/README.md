# EMA 9/20 Telegram alerts

A free bot that sends you a Telegram message when EMA 9 crosses EMA 20 on a closed candle,
the same signal as the Pine strategy in TradingView. It runs on GitHub Actions every 5 minutes,
so you don't need a paid TradingView plan.

It watches the 15m, 1H and 4H charts of the markets in `bot/markets.json`:
XAUUSD, NAS100, BTC, 1000PEPE, ZEC, HYPE, LIT, PENGU and FARTCOIN.

| Market | Price source | Note |
|---|---|---|
| XAUUSD | Twelve Data (free key) | TP = 100 pips ($10) |
| NAS100 | Yahoo Finance `NQ=F` | Nasdaq 100 futures; 4H built from 1H candles |
| Crypto | Gate.io USDT perpetuals (MEXC if Gate fails) | TP = 1%; 1000PEPE = PEPE x 1000 |

Prices come from these sources, not your TradingView broker, so levels can differ slightly,
and NAS100 can be some points away from a broker's NAS100 CFD.
GitHub can start a run a few minutes late, so a message can arrive a few minutes after the candle closes.

## Setup (about 10 minutes)

1. **Make a Telegram bot.** In Telegram, open `@BotFather`, send `/newbot`, and follow the steps.
   Copy the token it gives you. Then open your new bot and send it any message (for example "hi").
2. **Find your chat id.** Open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser.
   Find `"chat":{"id":123456789` and copy that number.
3. **Get a free Twelve Data key** at https://twelvedata.com (sign up, then copy the API key).
4. **Add the secrets on GitHub.** In this repo go to Settings > Secrets and variables > Actions >
   New repository secret, and add:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `TWELVEDATA_API_KEY`
5. **Optional:** to add or remove a market or timeframe, edit `bot/markets.json` on GitHub
   (timeframes can be `15m`, `1h`, `4h`; crypto symbols use the `COIN_USDT` form).
6. **Test it.** Go to Actions > "EMA 9/20 Telegram alerts" > Run workflow, tick
   "Send a test message", and run. You should get a TEST message in Telegram.

After that it runs by itself. The first run only remembers where it is, and every cross after that is sent once.

## Notes

- Each market and timeframe is only fetched after a new candle has closed, and at most once every
  10 minutes while waiting (weekends, the daily break, late data). Twelve Data is only used for gold:
  about 130 requests on a trading day, at most about 430 on a weekend, against 800 free a day.
- If a market's prices can't be read (for example a coin isn't listed), you get one Telegram
  message about it, and another when it works again.
- If the bot was down for a while, it only sends crosses from the last two candles, not old ones.
- GitHub pauses scheduled runs if the repo has no activity for 60 days. It emails you first,
  and you can turn the workflow back on in the Actions tab.
