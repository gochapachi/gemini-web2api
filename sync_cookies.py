#!/usr/bin/env python3
"""
sync_cookies.py - Automatically sync active Google Gemini cookies from local browser into gemini-auth.json and config.json.
"""
import os
import sys
import json
import time
import re
import sqlite3
import shutil
import tempfile
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUTH_FILE = os.path.join(BASE_DIR, "gemini-auth.json")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

def get_firefox_cookies():
    appdata = os.environ.get("APPDATA", "")
    profiles_dir = os.path.join(appdata, "Mozilla", "Firefox", "Profiles")
    if not os.path.exists(profiles_dir):
        return None

    # Find the most recently modified cookies.sqlite
    candidates = []
    for root, dirs, files in os.walk(profiles_dir):
        if "cookies.sqlite" in files:
            p = os.path.join(root, "cookies.sqlite")
            candidates.append((os.path.getmtime(p), p))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    
    for _, src in candidates:
        temp_dir = tempfile.gettempdir()
        dst = os.path.join(temp_dir, f"ff_cookie_sync_{os.getpid()}.sqlite")
        try:
            shutil.copy2(src, dst)
            conn = sqlite3.connect(dst)
            cursor = conn.cursor()
            cursor.execute("SELECT host, name, value FROM moz_cookies WHERE host LIKE '%google.com%'")
            rows = cursor.fetchall()
            conn.close()
            os.remove(dst)

            cookie_map = {}
            for host, name, val in rows:
                if host in [".google.com", "gemini.google.com"]:
                    cookie_map[name] = val
                elif name not in cookie_map:
                    cookie_map[name] = val

            # Verify if this profile has google session cookies
            if "SAPISID" in cookie_map and ("SID" in cookie_map or "__Secure-1PSID" in cookie_map):
                return cookie_map
        except Exception as e:
            if os.path.exists(dst):
                try:
                    os.remove(dst)
                except Exception:
                    pass
            continue
    return None

def sync():
    print("[*] Searching for active Google session in Firefox...")
    cookie_map = get_firefox_cookies()
    if not cookie_map:
        print("[!] No active Google session found in Firefox cookies.")
        return False

    cookie_str = "; ".join([f"{k}={v}" for k, v in cookie_map.items()])
    sapisid = cookie_map.get("SAPISID") or cookie_map.get("__Secure-1PAPISID") or cookie_map.get("__Secure-3PAPISID")

    print("[*] Querying gemini.google.com/app for live XSRF token and build label...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
        "Cookie": cookie_str
    }
    req = urllib.request.Request("https://gemini.google.com/app", headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=12)
        html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[!] Failed to connect to Gemini Web: {e}")
        return False

    snlm0e_match = re.search(r'"SNlM0e":"([^"]+)"', html)
    xsrf = snlm0e_match.group(1) if snlm0e_match else None
    cfb2h_match = re.search(r'"cfb2h":"([^"]+)"', html)
    bl = cfb2h_match.group(1) if cfb2h_match else "boq_assistant-bard-web-server_20260917.13_p0"
    user_gaia = re.search(r'"S06Grb":"([^"]+)"', html)
    has_advanced = "advanced" in html.lower()

    if not user_gaia or not user_gaia.group(1):
        print("[!] Session is not recognized as logged-in by Google. Please log into gemini.google.com in Firefox.")
        return False

    print(f"[*] Account authenticated! Gaia ID: {user_gaia.group(1)}")
    print(f"[*] Gemini Advanced detected: {has_advanced}")
    print(f"[*] Live XSRF Token: {xsrf[:25] if xsrf else 'None'}...")
    print(f"[*] Live Build Label (gemini_bl): {bl}")

    # Update gemini-auth.json
    auth_data = {
        "cookie": cookie_str,
        "sapisid": sapisid,
        "auth_user": None,
        "xsrf_token": xsrf,
        "gemini_bl": bl
    }
    with open(AUTH_FILE, "w", encoding="utf-8") as f:
        json.dump(auth_data, f, indent=2)
    print(f"[+] Saved updated credentials to {AUTH_FILE}")

    # Update config.json
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
        cfg["gemini_bl"] = bl
        if xsrf:
            cfg["xsrf_token"] = xsrf
        cfg["default_model"] = "gemini-3.8-flash"
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        print(f"[+] Updated {CONFIG_FILE} with latest token and default_model = gemini-3.8-flash")

    print("[✔] Google Gemini session sync successful!")
    return True

if __name__ == "__main__":
    sync()
