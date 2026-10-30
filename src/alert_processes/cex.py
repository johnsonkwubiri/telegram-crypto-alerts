import time
from datetime import datetime
import os

from ..user_configuration import (
    LocalUserConfiguration,
    MongoDBUserConfiguration,
    get_whitelist,
)
from ..logger import logger
from ..config import *
from .base import BaseAlertProcess
from ..telegram import TelegramBot

import requests
from ratelimit import limits, sleep_and_retry


class CEXAlertProcess(BaseAlertProcess):
    def __init__(self, telegram_bot: TelegramBot):
        """
        :param telegram_bot: The Telegram bot instance
        """
        super().__init__(telegram_bot)
        self.polling = False  # Temporary variable to manage alerts


    def poll_user_alerts(self, tg_user_id: str) -> None:
        """
        1. Load the user's configuration
        2. poll all alerts and create posts
        3. Remove alert conditions
        4. Send alerts if found

        :param tg_user_id: The Telegram user ID from the database
        """
        configuration = (
            LocalUserConfiguration(tg_user_id)
            if not USE_MONGO_DB
            else MongoDBUserConfiguration(tg_user_id)
        )
        alerts_database = configuration.load_alerts()
        config = configuration.load_config()

        do_update = False  # If any changes are made, update the database
        post_queue = []
        for pair in alerts_database.copy().keys():

            remove_queue = []
            for alert in alerts_database[pair]:
                if alert["type"] == "s":
                    condition, value, post_string = self.get_simple_indicator(
                        pair, alert
                    )

                    if condition:  # If there is a simple alert condition satisfied
                        cooldown = alert.get("trigger", {}).get("cooldown_seconds")
                        last_trigger = alert.get("trigger", {}).get("last_triggered", 0)
                        if int(time.time()) > last_trigger + (cooldown or 0):
                            post_queue.append((post_string, pair))

                        current_time = int(time.time())
                        alert["trigger"] = {
                            "cooldown_seconds": cooldown,
                            "last_triggered": current_time,
                        }
                        if not alert["trigger"]["cooldown_seconds"]:
                            # If the alert has no cooldown setting, remove it
                            remove_queue.append(alert)

                        do_update = True  # Since the alert needs to be updated in the database, signal do_update

            for item in remove_queue:
                alerts_database[pair].remove(item)
                if len(alerts_database[pair]) == 0:
                    alerts_database.pop(pair)

        if do_update:
            configuration.update_alerts(alerts_database)

        if len(post_queue) > 0:
            self.polling = False
            for post, pair in post_queue:
                logger.info(post)
                status = self.tg_alert(
                    post=post, channel_ids=config["channels"], pair=pair
                )
                if len(status[1]) > 0:
                    logger.warn(
                        f"Failed to send Telegram alert ({post}) to the following IDs: {status[1]}"
                    )

        if not self.polling:
            self.polling = True
            logger.info(f"Bot polling for next alert...")

    @sleep_and_retry
    @limits(calls=1, period=CEX_POLLING_PERIOD)
    def poll_all_alerts(self) -> None:
        for user in get_whitelist():
            self.poll_user_alerts(tg_user_id=user)

    def get_simple_indicator(
        self, pair: str, alert: dict, pair_price: float = None
    ) -> tuple[bool, float, str]:
        """
        Accounts for the 3 following simple price movement indicators:
        PCTCHG - Percent change in the price
        ABOVE - Price above the target
        BELOW - Price below the target

        :param pair: The crypto pair
        :param pair_price: The current price of the crypto pair.
                           Get the pair price before calling the self.get_pair_price() function
        :param alert: An alert data dictionary as returned by src.io_handler.UserConfiguration.load_alerts()

        :returns: Tuple:
                  (Boolean) True if the indicator is satisfied, False if not
                  (Float) The current value of the indicator
                  (String) The formatted string to send with alerts
        """
        target = alert["target"]
        # indicator = alert["indicator"]
        comparison = alert["comparison"]
        if pair_price is None:
            pair_price = self.get_latest_price(token_pair=pair.replace("/", ""))

        if comparison == "PCTCHG":
            entry = alert["entry"]
            if pair_price > (entry * (1 + target)):
                pct_chg = ((pair_price - entry) / entry) * 100
                return (
                    True,
                    pct_chg,
                    f"{pair} UP {pct_chg:.1f}% FROM {entry} AT {pair_price}",
                )
            elif pair_price < (entry * (1 - target)):
                pct_chg = ((entry - pair_price) / entry) * 100
                return (
                    True,
                    pct_chg,
                    f"{pair} DOWN {pct_chg:.1f}% FROM {entry} AT {pair_price}",
                )
        elif comparison == "24HRCHG":
            pct_change = self.get_pct_change(pair.replace("/", ""), window="1d")
            if abs(pct_change) >= alert["target"]:
                return (
                    True,
                    pct_change,
                    f"{pair} 24HR CHANGE {pct_change:.1f}% AT {pair_price}",
                )
        elif comparison == "ABOVE":
            if pair_price > target:
                return True, pair_price, f"{pair} ABOVE {target} TARGET AT {pair_price}"
        elif comparison == "BELOW":
            if pair_price < target:
                return True, pair_price, f"{pair} BELOW {target} TARGET AT {pair_price}"

        return False, pair_price, ""

    def get_latest_price(
        self,
        token_pair: str,
        retry_delay: int = 2,
        maximum_retries: int = 5,
        _try: int = 1,
    ) -> float:
        """
        Fetch a public Binance futures price, falling back to CoinGecko.

        This uses public endpoints only and does not place trades or require
        exchange credentials.
        """
        symbol = token_pair.upper()
        base, quote = symbol, "USDT"
        for suffix in ("USDT", "USDC", "BUSD", "BTC", "ETH", "BNB", "USD"):
            if symbol.endswith(suffix) and len(symbol) > len(suffix):
                base, quote = symbol[:-len(suffix)], suffix
                break

        coin_ids = {
            "BTC": "bitcoin", "ETH": "ethereum", "BNB": "binancecoin",
            "SOL": "solana", "XRP": "ripple", "ADA": "cardano",
            "DOGE": "dogecoin", "TRX": "tron", "TON": "the-open-network",
            "AVAX": "avalanche-2", "LINK": "chainlink", "DOT": "polkadot",
            "LTC": "litecoin", "BCH": "bitcoin-cash", "MATIC": "matic-network",
            "SHIB": "shiba-inu", "SUI": "sui", "USDT": "tether",
            "USDC": "usd-coin", "BUSD": "binance-usd",
        }
        coin_id = coin_ids.get(base)
        vs_currency = {"USDT": "usd", "USDC": "usd", "BUSD": "usd", "USD": "usd"}.get(quote)

        binance_url = "https://fapi.binance.com/fapi/v1/ticker/price"
        try:
            response = requests.get(binance_url, params={"symbol": symbol}, timeout=10)
            response.raise_for_status()
            price = float(response.json()["price"])
            if price <= 0:
                raise ValueError("Binance returned a non-positive price")
            return price
        except Exception as binance_error:
            if not coin_id or not vs_currency:
                raise ConnectionAbortedError(
                    f"Binance futures price failed for {symbol} ({binance_error}); "
                    f"CoinGecko fallback has no mapping for {symbol}"
                ) from binance_error
            gecko_url = "https://api.coingecko.com/api/v3/simple/price"
            try:
                response = requests.get(
                    gecko_url,
                    params={"ids": coin_id, "vs_currencies": vs_currency},
                    timeout=10,
                )
                response.raise_for_status()
                price = float(response.json()[coin_id][vs_currency])
                if price <= 0:
                    raise ValueError("CoinGecko returned a non-positive price")
                return price
            except Exception as gecko_error:
                coinbase_pair = f"{base}-{ 'USD' if vs_currency == 'usd' else vs_currency.upper() }"
                try:
                    response = requests.get(
                        f"https://api.coinbase.com/v2/prices/{coinbase_pair}/spot",
                        timeout=10,
                    )
                    response.raise_for_status()
                    price = float(response.json()["data"]["amount"])
                    if price <= 0:
                        raise ValueError("Coinbase returned a non-positive price")
                    return price
                except Exception as coinbase_error:
                    raise ConnectionAbortedError(
                        f"All price sources failed for {symbol}: "
                        f"Binance: {binance_error}; CoinGecko: {gecko_error}; Coinbase: {coinbase_error}"
                    ) from coinbase_error

    def get_pct_change(
        self,
        token_pair: str,
        window: str,
        retry_delay: int = 2,
        maximum_retries: int = 5,
        _try: int = 1,
    ) -> float:
        """
        Make a request to Binance API and return the 24 hour % change for a token pair

        :param token_pair: token pair without the slash (e.g. BTCUSDT)
        :param window: The time window for the price change (e.g. 1d for 1 day)
        :param _try: The current try for recursive retries
        :param retry_delay: seconds delay between retries
        :param maximum_retries: Maxiumum number of retries

        :return float: The percent change of the token pair (expressed as a percentage, i.e. -3.8 for -3.8%)
        """
        assert window in BINANCE_TIMEFRAMES, (
            f"Invalid window ({window}) for Binance API. "
            f"Must be one of {BINANCE_TIMEFRAMES}"
        )
        url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
        try:
            response = requests.get(url, params={"symbol": token_pair.upper()}, timeout=10)
            response.raise_for_status()
            return float(response.json()["priceChangePercent"])
        except Exception as binance_error:
            symbol = token_pair.upper()
            base, quote = symbol, "USDT"
            for suffix in ("USDT", "USDC", "BUSD", "BTC", "ETH", "BNB", "USD"):
                if symbol.endswith(suffix) and len(symbol) > len(suffix):
                    base, quote = symbol[:-len(suffix)], suffix
                    break
            coin_ids = {
                "BTC": "bitcoin", "ETH": "ethereum", "BNB": "binancecoin",
                "SOL": "solana", "XRP": "ripple", "ADA": "cardano",
                "DOGE": "dogecoin", "TRX": "tron", "TON": "the-open-network",
                "AVAX": "avalanche-2", "LINK": "chainlink", "DOT": "polkadot",
                "LTC": "litecoin", "BCH": "bitcoin-cash", "MATIC": "matic-network",
                "SHIB": "shiba-inu", "SUI": "sui", "USDT": "tether",
                "USDC": "usd-coin", "BUSD": "binance-usd",
            }
            coin_id = coin_ids.get(base)
            vs_currency = {"USDT": "usd", "USDC": "usd", "BUSD": "usd", "USD": "usd"}.get(quote)
            if not coin_id or not vs_currency:
                raise ConnectionAbortedError(
                    f"Binance 24h change failed for {symbol} ({binance_error}); "
                    f"CoinGecko fallback has no mapping for {symbol}"
                ) from binance_error
            try:
                response = requests.get(
                    "https://api.coingecko.com/api/v3/simple/price",
                    params={"ids": coin_id, "vs_currencies": vs_currency,
                            "include_24hr_change": "true"},
                    timeout=10,
                )
                response.raise_for_status()
                return float(response.json()[coin_id][f"{vs_currency}_24h_change"])
            except Exception as gecko_error:
                coinbase_pair = f"{base}-{ 'USD' if vs_currency == 'usd' else vs_currency.upper() }"
                try:
                    now_response = requests.get(
                        f"https://api.coinbase.com/v2/prices/{coinbase_pair}/spot", timeout=10)
                    now_response.raise_for_status()
                    now_price = float(now_response.json()["data"]["amount"])
                    from datetime import datetime, timedelta, timezone
                    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
                    past_response = requests.get(
                        f"https://api.coinbase.com/v2/prices/{coinbase_pair}/spot",
                        params={"date": yesterday}, timeout=10)
                    past_response.raise_for_status()
                    past_price = float(past_response.json()["data"]["amount"])
                    change = (now_price - past_price) / past_price * 100
                    return change
                except Exception as coinbase_error:
                    raise ConnectionAbortedError(
                        f"All 24h change sources failed for {symbol}: "
                        f"Binance: {binance_error}; CoinGecko: {gecko_error}; Coinbase: {coinbase_error}"
                    ) from coinbase_error

    def tg_alert(self, post: str, channel_ids: list[str], pair: str = None) -> tuple:
        """
        Sends the post (price alert) to each registered user of the Telegram bot

        :param post: A message to send to each registered bot user
        :param channel_ids: All group ids to send the alert to (self.config_client.load_config()['channels'])
        :param pair: The binance pair corresponding to the alert (for showing chart)

        :return: Tuple = ([successful group ids], [unsuccessful group ids])
        """
        post = f"🔔 <b>CEX ALERT:</b> 🔔\n\n" + post
        if pair:
            pair_fmt = pair.replace("/", "_")
            post += f"\n\n<a href='https://www.binance.com/en/trade/{pair_fmt}?type=spot'><b>View {pair} Chart</b></a>"
        output = ([], [])
        for g_id in channel_ids:
            try:
                # requests.post(url=f'https://api.telegram.org/bot{self.tg_bot_token}/sendMessage',
                #               params={'chat_id': g_id, 'text': header_str + post, "parse_mode": "HTML"})
                self.telegram_bot.send_message(
                    chat_id=g_id,
                    text=post,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                output[0].append(g_id)
            except:
                output[1].append(g_id)

        return output

    def run(self):
        """
        Start the CEX alert process and run in an infinite loop
        """
        try:
            logger.warn(f"{type(self).__name__} started at {datetime.utcnow()} UTC+0")
            while True:
                self.poll_all_alerts()
        except NotImplementedError as exc:
            logger.critical(exc_info=exc)
            # self.alert_admins(str(exc))
        except KeyboardInterrupt:
            logger.critical("KeyboardInterrupt detected. Exiting...")
            exit(0)
        except Exception as exc:
            logger.critical(
                "An error has occurred in the CEX alert process. Trying again in 15 seconds...",
                exc_info=exc,
            )
            time.sleep(15)
