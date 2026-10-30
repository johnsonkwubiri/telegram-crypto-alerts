# simple setup guide for telegram crypto alerts

This copy sends price and optional technical-indicator alerts to Telegram. It does not buy, sell, or place trades.

## What it needs

- Python 3.11 is selected for Render. The original setup guide says Python 3.9 or newer, and its Dockerfile uses Python 3.11.
- The dependencies in `requirements.txt`: pyTelegramBotAPI, requests, python-dotenv, ratelimit, ratelimiter, sendgrid, pymongo, pyyaml, and black.
- Three required settings: `TELEGRAM_USER_ID`, `TELEGRAM_BOT_TOKEN`, and `LOCATION`. Use `global` for the Binance global price endpoint, or `us` for the Binance US endpoint.
- A Taapi.io API key is optional. Without it, normal Binance price alerts work, but technical-indicator alerts do not. `TAAPIIO_TIER` defaults to `free` in the code. The configured free limit is 1 request per 20 seconds.
- The default setup stores users and alerts in local JSON files. There is no database account needed, but Render free services have temporary storage. Files can be lost when Render restarts, redeploys, or spins down. This means saved alerts and setup may need to be restored after one of those events.

The project code does not place trades. Do not add exchange trading keys; this bot does not need them.

## Deploy it for free

1. **Make your Telegram bot.** Open Telegram and search for `@BotFather`. Send `/newbot`, follow its instructions, and copy the token it gives you. Keep the token private. Anyone with it can control your bot.

2. **Find your Telegram user ID.** In Telegram, message `@userinfobot` and copy the numeric ID it returns. This identifies you as the first bot administrator.

3. **Put this project in your GitHub account.** Sign in to GitHub. Open the original project at https://github.com/hschickdevs/Telegram-Crypto-Alerts and use **Fork** to make your own copy, or upload this prepared project folder as a new repository. The prepared copy is in the `apps/telegram-crypto-alerts` folder. Do not upload a real `.env` file or paste your bot token into a public file. The `.env.example` is only a sample.

4. **Create the Render service.** Sign in to Render, choose **New**, then **Blueprint** (sometimes shown as **Blueprint instance**), connect your GitHub account if Render asks, and select your copy of the repository. Render reads `render.yaml` and prepares a free web service. If using the prepared folder inside a larger repository, set the service's **Root Directory** to `apps/telegram-crypto-alerts` before deploying. If that field is not available during Blueprint setup, upload this folder's contents into the root of a separate repository instead.

5. **Add the private settings.** When Render asks, enter `TELEGRAM_USER_ID` as the numeric ID from step 2 and `TELEGRAM_BOT_TOKEN` as the secret from BotFather. `LOCATION` is already set to `global` in the blueprint. Keep secrets in Render's Environment settings, not in GitHub. Save the settings and deploy.

6. **Check that it starts.** In Render, open the service's URL and add `/health` to the end. It should show `ok`. In Telegram, open your new bot and press **Start**. Try `/get_price BTC/USDT`. A price response confirms the bot can reach Binance. Try `/new_alert BTC/USDT PRICE ABOVE 100000` to create a price alert, changing the number to a level you choose. Use `/view_alerts` to see active alerts.

7. **Keep the free service awake for continuous monitoring.** Render free web services go to sleep after 15 minutes with no incoming traffic. While asleep, the bot cannot check prices; the next request can take about a minute to wake the service. To reduce interruptions, create a free scheduled ping at https://cron-job.org every 10 minutes. Set the URL to your Render service URL ending in `/health`, use an HTTP GET request, and enable the schedule. Open that URL after setup to make sure it returns `ok`. This outside ping is an uptime workaround, not a guarantee: Render can restart the service, and free service storage is temporary.

8. **Optional technical alerts.** Only if you want technical indicators, obtain a Taapi.io API key and add `TAAPIIO_APIKEY` in Render's Environment settings. `TAAPIIO_TIER` can be omitted because the code defaults to `free`; if you set it, use `free`, `basic`, `pro`, or `expert` to match your Taapi.io plan. The free Taapi.io limits may restrict how frequently indicator values update. No Taapi.io key is needed for basic price alerts.

## Settings at a glance

Required: `TELEGRAM_USER_ID`, `TELEGRAM_BOT_TOKEN`, and `LOCATION`.

Optional: `TAAPIIO_APIKEY` and `TAAPIIO_TIER` for technical indicators. See `.env.example` for a safe template. Render supplies `PORT` automatically; it is not a setting you need to add yourself.

The source also contains optional MongoDB connection variables, but the repository currently hard-codes `USE_MONGO_DB = False`. Adding MongoDB credentials alone will not enable it. The free deployment in this guide uses the built-in local JSON storage instead.
