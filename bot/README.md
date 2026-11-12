# EMA 9/20 Telegram alerts

A free bot that sends you a Telegram message when EMA 9 crosses EMA 20 on a closed candle,
the same signal as the Pine strategy in TradingView. It runs on GitHub Actions every 5 minutes,
so you don't need a paid TradingView plan.

Prices come from Twelve Data, not your TradingView broker, so levels can differ by a few cents.
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
5. **Optional settings** (Variables tab on the same page):
   - `INTERVAL`: `5min`, `15min` (default), `30min`, `1h`, `4h` or `1day`
   - `SYMBOL`: default `XAU/USD`
   - `TP_PIPS`: default `100` (0 = no TP in the message)
6. **Test it.** Go to Actions > "EMA 9/20 Telegram alerts" > Run workflow, tick
   "Send a test message", and run. You should get a TEST message in Telegram.

After that it runs by itself. The first run only remembers where it is, and every cross after that is sent once.

## Notes

- Use `5min` or slower. With `1min`, GitHub's 5-minute schedule is too slow.
- The free Twelve Data plan allows 800 requests a day; this uses about 290.
- GitHub pauses scheduled runs if the repo has no activity for 60 days. It emails you first,
  and you can turn the workflow back on in the Actions tab.
