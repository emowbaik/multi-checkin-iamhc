#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import requests
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

# ---------------------------------------------------------------------------
# Config — two supported modes:
#
#   Mode 1 (Multi-account, recommended):
#     ACCOUNTS = "email1:password1\nemail2:password2\n..."
#
#   Mode 2 (Single-account, backward-compatible):
#     EMAIL    = "..."
#     PASSWORD = "..."
# ---------------------------------------------------------------------------

TG_CHAT_ID   = os.environ.get("TG_CHAT_ID") or ""
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or ""

BASE_URL        = "https://api.hcnsec.cn"
QUOTA_PER_UNIT  = 500000  # new-api default quota conversion: 500000 quota = $1
TURNSTILE_TOKEN = ""      # Turnstile is not enabled on this site; unused for now

CST = timezone(timedelta(hours=8))  # China Standard Time (UTC+8)


# ---------------------------------------------------------------------------
# Account loader
# ---------------------------------------------------------------------------

def load_accounts():
    """
    Returns a list of (email, password) tuples.
    Reads ACCOUNTS env var first (one email:password per line);
    falls back to single-account EMAIL / PASSWORD if ACCOUNTS is absent.
    """
    raw = os.environ.get("ACCOUNTS", "").strip()
    if raw:
        accounts = []
        for line_no, line in enumerate(raw.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            if ":" not in line:
                print(f"⚠️  ACCOUNTS line {line_no} is malformed (expected email:password) — skipped")
                continue
            # Split only on the first colon so passwords may contain colons
            email, password = line.split(":", 1)
            email, password = email.strip(), password.strip()
            if email and password:
                accounts.append((email, password))
            else:
                print(f"⚠️  ACCOUNTS line {line_no} has empty email or password — skipped")
        return accounts

    # Fallback: single-account mode
    email    = os.environ.get("EMAIL", "").strip()
    password = os.environ.get("PASSWORD", "").strip()
    if email and password:
        return [(email, password)]

    return []


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def login(session: requests.Session, email: str, password: str):
    """Log in and return user info (id + username). Returns None on failure."""
    url = f"{BASE_URL}/api/user/login?turnstile={quote(TURNSTILE_TOKEN)}"
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/login",
    }
    try:
        resp = session.post(
            url,
            headers=headers,
            json={"username": email, "password": password},
            timeout=20,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"Login request failed: {e}")
        return None

    data = resp.json()
    if not data.get("success"):
        print(f"Login failed: {data.get('message', '')}")
        return None

    user_data = data.get("data", {})
    user_id   = user_data.get("id")
    username  = user_data.get("username", "")
    if not user_id:
        print("Login succeeded but no user ID returned")
        return None

    print(f"✅ Logged in | Account: {username} | ID: {user_id}")
    return {"id": user_id, "username": username}


def get_user_info(session: requests.Session, user_id):
    """Fetch user info and return the data dict (contains quota etc.). Returns None on failure."""
    url     = f"{BASE_URL}/api/user/self"
    headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0",
        "Referer": BASE_URL,
        "New-Api-User": str(user_id),
    }
    try:
        resp = session.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"Failed to fetch user info: {e}")
        return None

    return data.get("data") if data.get("success") else None


def checkin(session: requests.Session, user_id):
    """Perform check-in and return the full JSON response. Returns an error dict on failure."""
    url     = f"{BASE_URL}/api/user/checkin"
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Origin": BASE_URL,
        "Referer": BASE_URL,
        "New-Api-User": str(user_id),
    }
    try:
        resp = session.post(url, headers=headers, json={}, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"Check-in request failed: {e}")
        return {"success": False, "message": str(e)}


def quota_to_dollar(quota):
    """Convert internal quota value to USD (2 decimal places)."""
    return round(quota / QUOTA_PER_UNIT, 2)


# ---------------------------------------------------------------------------
# Notification
# ---------------------------------------------------------------------------

def send_notification(message: str):
    print("\n" + "=" * 30)
    print(message)
    print("=" * 30)

    if TG_BOT_TOKEN and TG_CHAT_ID:
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
                json={"chat_id": TG_CHAT_ID, "text": message, "parse_mode": "HTML"},
                timeout=10,
            )
            if resp.status_code == 200:
                print("Telegram notification sent successfully")
            else:
                print(f"Telegram notification failed: {resp.status_code} {resp.text}")
        except Exception as e:
            print(f"Telegram notification failed: {e}")
    else:
        print("TG_BOT_TOKEN / TG_CHAT_ID not configured — skipping Telegram notification")


# ---------------------------------------------------------------------------
# Per-account checkin flow
# ---------------------------------------------------------------------------

def run_checkin_for_account(email: str, password: str, index: int, total: int):
    """Run the full login → check-in → notify flow for a single account."""
    prefix = f"[{index}/{total}]"
    print(f"\n{'─' * 30}")
    print(f"{prefix} Processing account: {email}")

    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    session = requests.Session()

    # 1. Login
    user = login(session, email, password)
    if not user:
        msg = (
            f"🎁 iamhc Check-in Notification\n\n"
            f"❌ Login failed\n"
            f"👤 Account: {email}\n"
            f"⏱️ Time: {now}"
        )
        send_notification(msg)
        return False

    user_id  = user["id"]
    username = user.get("username") or email

    # 2. Balance before check-in
    info_before = get_user_info(session, user_id)
    balance_before = quota_to_dollar(info_before.get("quota", 0)) if info_before else "?"

    # 3. Perform check-in
    checkin_data = checkin(session, user_id)

    # 4. Balance after check-in
    info_after = get_user_info(session, user_id)
    balance_after = quota_to_dollar(info_after.get("quota", 0)) if info_after else "?"

    # 5. Build notification
    success = checkin_data.get("success", False)
    msg_api = str(checkin_data.get("message", ""))

    footer = (
        f"👤 Account: {username}\n"
        f"💰 Balance before: {balance_before}$\n"
        f"💰 Balance after: {balance_after}$\n"
        f"⏱️ Time: {now}"
    )

    if success:
        awarded_data  = checkin_data.get("data") or {}
        awarded_quota = awarded_data.get("quota_awarded", 0)
        if awarded_quota:
            awarded_dollar = quota_to_dollar(awarded_quota)
        elif isinstance(balance_after, float) and isinstance(balance_before, float):
            awarded_dollar = round(balance_after - balance_before, 2)
        else:
            awarded_dollar = "?"
        print(f"✅ Check-in successful | Earned: {awarded_dollar}$")
        header = f"✅ Check-in successful! Earned {awarded_dollar}$\n"

    elif any(kw in msg_api for kw in ("已签到", "重复签到", "今天已签到")):
        print(f"✅ Already checked in today | Balance: {balance_after}$")
        header = "✅ Already checked in today!\n"

    else:
        print(f"❌ Check-in failed | {msg_api}")
        header = f"❌ Check-in failed: {msg_api}\n"

    send_notification(f"🎁 iamhc Check-in Notification\n\n{header}{footer}")
    return success


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    accounts = load_accounts()

    if not accounts:
        print(
            "❌ No accounts found. Please set one of the following env vars:\n"
            "   Multi-account : ACCOUNTS=email1:password1 (one per line)\n"
            "   Single-account: EMAIL=... and PASSWORD=..."
        )
        sys.exit(1)

    total   = len(accounts)
    results = []

    print(f"🚀 Found {total} account(s) — starting batch check-in...")

    for i, (email, password) in enumerate(accounts, 1):
        ok = run_checkin_for_account(email, password, i, total)
        results.append((email, ok))

    # Summary report
    print(f"\n{'=' * 30}")
    print(f"📊 Batch check-in complete ({total} account(s))")
    for email, ok in results:
        status = "✅" if ok else "❌"
        print(f"  {status} {email}")
    print("=" * 30)


if __name__ == "__main__":
    main()
