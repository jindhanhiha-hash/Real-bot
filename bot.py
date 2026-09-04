#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging
from typing import List, Optional

import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.error import NetworkError, TimedOut, RetryAfter
from telegram.request import HTTPXRequest

# ------------------------------------------------------------
# CONFIGURATION – EDIT THESE CUNTS
# ------------------------------------------------------------
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # Replace with your actual token

# The steaming pile of SOCKS4 proxies you scraped (all 38 of them)
PROXY_LIST = [
    "85.228.42.180:4153", "109.197.55.234:1080", "45.4.183.109:5678",
    "31.170.18.129:4153", "90.188.92.116:36335", "163.172.171.22:16379",
    "45.70.52.26:4153", "123.200.28.149:1080", "98.178.72.21:10919",
    "41.180.70.2:4153", "45.169.88.106:5678", "103.66.74.61:1081",
    "103.248.9.69:80", "111.119.162.248:10931", "174.64.199.79:4145",
    "197.211.24.206:5678", "98.182.147.97:4145", "212.39.114.139:5678",
    "165.16.45.200:1080", "188.163.170.130:35578", "45.128.133.153:1080",
    "103.21.40.35:4145", "103.89.62.5:4153", "78.159.131.108:1082",
    "181.189.132.74:5678", "171.242.14.54:1080", "113.53.29.228:13629",
    "98.162.96.52:4145", "45.236.185.1:4153", "102.38.50.133:4153",
    "121.101.190.241:43296", "147.45.60.110:1082", "192.111.137.35:4145",
    "98.175.31.195:4145", "72.221.232.152:4145", "205.240.77.164:4145",
    "46.8.60.2:1080", "51.91.144.39:59191"
]

# Timeout settings – fuck the default 5 seconds, we give 30 to read
CONNECT_TIMEOUT = 15.0   # seconds to establish TCP
READ_TIMEOUT = 30.0      # seconds to wait for Telegram's response

# Polling interval – don't hammer the API like a horny teenager
POLL_INTERVAL = 1.0

# ------------------------------------------------------------
# PROXY TESTER – quick cunt-check
# ------------------------------------------------------------
async def test_proxy(proxy_url: str) -> bool:
    """Check if the proxy can reach httpbin.org within 3 seconds."""
    try:
        async with httpx.AsyncClient(proxy=proxy_url, timeout=3.0) as client:
            resp = await client.get("http://httpbin.org/ip")
            return resp.status_code == 200
    except Exception:
        return False

async def get_working_proxy(proxy_list: List[str]) -> Optional[str]:
    """Iterate through the list, return first working SOCKS4 proxy, else None."""
    for entry in proxy_list:
        proxy_url = f"socks4://{entry}"
        if await test_proxy(proxy_url):
            return proxy_url
    return None

# ------------------------------------------------------------
# BOT LOGIC – dumb as fuck, but it works
# ------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Bot is alive, you cunt. Send me anything.")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"You said: {update.message.text}")

# ------------------------------------------------------------
# MAIN – build the app with proxy or without
# ------------------------------------------------------------
def build_application(proxy_url: Optional[str] = None) -> Application:
    """Create an Application with proper timeouts and optional SOCKS4 proxy."""
    # Build a custom HTTPX client
    client_kwargs = {
        "timeout": httpx.Timeout(CONNECT_TIMEOUT, read=READ_TIMEOUT),
    }
    if proxy_url:
        client_kwargs["proxy"] = proxy_url
        logging.info(f"Using proxy: {proxy_url}")
    else:
        logging.info("No proxy – going raw.")

    http_client = httpx.AsyncClient(**client_kwargs)

    # Create the Request object
    request = HTTPXRequest(http_client=http_client)

    # Build the Application
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(request)
        .connect_timeout(CONNECT_TIMEOUT)
        .read_timeout(READ_TIMEOUT)
        .build()
    )

    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    return app

# ------------------------------------------------------------
# POLLING WRAPPER – retry like a stubborn mule
# ------------------------------------------------------------
async def run_with_retries(app: Application, max_retries: int = 3) -> None:
    """Start polling with retry logic on NetworkError."""
    retries = 0
    while retries < max_retries:
        try:
            logging.info(f"Polling attempt {retries+1}/{max_retries}")
            await app.run_polling(poll_interval=POLL_INTERVAL)
            break  # if it runs forever, we don't reach this
        except NetworkError as e:
            logging.error(f"NetworkError: {e}. Retrying in 5 sec...")
            await asyncio.sleep(5)
            retries += 1
        except Exception as e:
            logging.critical(f"Unhandled shit: {e}")
            break
    else:
        logging.critical("All retries failed. Fuck this, exiting.")

# ------------------------------------------------------------
# ENTRY POINT – get a proxy, build app, run
# ------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    # Try to find a working proxy from the list
    logging.info("Scanning for a live SOCKS4 proxy (this might take a while)...")
    working_proxy = asyncio.run(get_working_proxy(PROXY_LIST))

    if working_proxy:
        logging.info(f"Found working proxy: {working_proxy}")
    else:
        logging.warning("No working proxy found. Proceeding without proxy – hope your network isn't blocked.")

    app = build_application(proxy_url=working_proxy)

    # Run the bot with retries
    asyncio.run(run_with_retries(app))
