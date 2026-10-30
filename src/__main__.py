import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from os import getenv
from time import sleep

from .alert_processes import CEXAlertProcess, TechnicalAlertProcess
from .telegram import TelegramBot
from .user_configuration import get_whitelist
from .utils import handle_env
from .indicators import TaapiioProcess
from .logger import logger
from .setup import do_setup


class HealthHandler(BaseHTTPRequestHandler):
    """Small HTTP endpoint required by Render web services."""

    def do_GET(self):
        if self.path != "/health":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format, *args):
        return


def start_health_server():
    port = int(getenv("PORT", "10000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    logger.info(f"Health endpoint listening on port {port}")


if __name__ == "__main__":
    # Process environment variables
    handle_env()

    # Do the setup process if the bot is not set up
    if len(get_whitelist()) == 0:
        do_setup()
        logger.info("Waiting for initialization ...")
        sleep(5)

    # Render requires a public HTTP port for a free web service.
    start_health_server()

    taapiio_process = None
    if getenv("TAAPIIO_APIKEY"):
        # Create global Taapi.io process for the aggregator and telegram bot to sync calls
        taapiio_process = TaapiioProcess(taapiio_apikey=getenv("TAAPIIO_APIKEY"))

    # Create the Telegram bot to listen to commands and send messages
    telegram_bot = TelegramBot(
        bot_token=getenv("TELEGRAM_BOT_TOKEN"), taapiio_process=taapiio_process
    )

    # Run the TG bot in a daemon thread
    threading.Thread(target=telegram_bot.run, daemon=True).start()

    # Run the CEXAlertProcess in a daemon thread
    threading.Thread(
        target=CEXAlertProcess(telegram_bot=telegram_bot).run, daemon=True
    ).start()

    if taapiio_process:
        # Run the Taapi.io process in a daemon thread
        threading.Thread(target=taapiio_process.run, daemon=True).start()

        # Run the TechnicalAlertProcess in a daemon thread
        threading.Thread(
            target=TechnicalAlertProcess(telegram_bot=telegram_bot).run, daemon=True
        ).start()

    # Keep the main thread alive to listen to interrupt
    logger.info("Bot started - use Ctrl+C to stop the bot.")
    while True:
        try:
            sleep(0.5)
        except KeyboardInterrupt:
            logger.info("Bot stopped")
            exit(1)
