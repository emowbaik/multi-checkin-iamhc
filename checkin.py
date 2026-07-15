#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import requests
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

# ---------------------------------------------------------------------------
# Config — dua mode yang didukung:
#
#   Mode 1 (Multi-akun, direkomendasikan):
#     ACCOUNTS = "email1:password1\nemail2:password2\n..."
#
#   Mode 2 (Single-akun, kompatibel ke belakang):
#     EMAIL    = "..."
#     PASSWORD = "..."
# ---------------------------------------------------------------------------

TG_CHAT_ID   = os.environ.get("TG_CHAT_ID") or ""
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or ""

BASE_URL        = "https://api.hcnsec.cn"
QUOTA_PER_UNIT  = 500000  # new-api 默认额度换算比例：500000 quota = 1$
TURNSTILE_TOKEN = ""      # 该站点暂未开启 turnstile，暂时用不上此参数

CST = timezone(timedelta(hours=8))  # China Standard Time (UTC+8)


# ---------------------------------------------------------------------------
# Account loader
# ---------------------------------------------------------------------------

def load_accounts():
    """
    返回 [(email, password), ...] 列表。
    优先读取 ACCOUNTS 环境变量（每行一个 email:password）；
    如不存在则回退到单账户的 EMAIL / PASSWORD。
    """
    raw = os.environ.get("ACCOUNTS", "").strip()
    if raw:
        accounts = []
        for line_no, line in enumerate(raw.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            if ":" not in line:
                print(f"⚠️  ACCOUNTS 第 {line_no} 行格式错误（应为 email:password），已跳过")
                continue
            # 只在第一个冒号处分割，以允许密码中含有冒号
            email, password = line.split(":", 1)
            email, password = email.strip(), password.strip()
            if email and password:
                accounts.append((email, password))
            else:
                print(f"⚠️  ACCOUNTS 第 {line_no} 行 email 或 password 为空，已跳过")
        return accounts

    # 回退：单账户模式
    email    = os.environ.get("EMAIL", "").strip()
    password = os.environ.get("PASSWORD", "").strip()
    if email and password:
        return [(email, password)]

    return []


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def login(session: requests.Session, email: str, password: str):
    """登录并返回用户信息（id + username）。失败返回 None。"""
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
        print(f"登录请求异常: {e}")
        return None

    data = resp.json()
    if not data.get("success"):
        print(f"登录失败: {data.get('message', '')}")
        return None

    user_data = data.get("data", {})
    user_id   = user_data.get("id")
    username  = user_data.get("username", "")
    if not user_id:
        print("登录成功但未获取到用户 ID")
        return None

    print(f"✅ 登录成功 | 账户: {username} | ID: {user_id}")
    return {"id": user_id, "username": username}


def get_user_info(session: requests.Session, user_id):
    """获取用户信息，返回 data 字典（包含 quota 等字段）。失败返回 None。"""
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
        print(f"获取用户信息异常: {e}")
        return None

    return data.get("data") if data.get("success") else None


def checkin(session: requests.Session, user_id):
    """执行签到，返回签到响应的完整 JSON。失败返回错误结构。"""
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
        print(f"签到请求异常: {e}")
        return {"success": False, "message": str(e)}


def quota_to_dollar(quota):
    """将内部 quota 值转换为美元金额（保留两位小数）。"""
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
                print("Telegram 通知发送成功")
            else:
                print(f"Telegram 通知发送失败: {resp.status_code} {resp.text}")
        except Exception as e:
            print(f"Telegram 通知发送失败: {e}")
    else:
        print("未配置 TG_BOT_TOKEN / TG_CHAT_ID，跳过 Telegram 推送")


# ---------------------------------------------------------------------------
# Per-account checkin flow
# ---------------------------------------------------------------------------

def run_checkin_for_account(email: str, password: str, index: int, total: int):
    """对单个账户执行完整的登录→签到→通知流程。"""
    prefix = f"[{index}/{total}]"
    print(f"\n{'─' * 30}")
    print(f"{prefix} 开始处理账户: {email}")

    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    session = requests.Session()

    # 1. 登录
    user = login(session, email, password)
    if not user:
        msg = (
            f"🎁 iamhc 签到通知\n\n"
            f"❌ 登录失败\n"
            f"👤 账户: {email}\n"
            f"⏱️ 时间: {now}"
        )
        send_notification(msg)
        return False

    user_id  = user["id"]
    username = user.get("username") or email

    # 2. 签到前余额
    info_before = get_user_info(session, user_id)
    balance_before = quota_to_dollar(info_before.get("quota", 0)) if info_before else "?"

    # 3. 执行签到
    checkin_data = checkin(session, user_id)

    # 4. 签到后余额
    info_after = get_user_info(session, user_id)
    balance_after = quota_to_dollar(info_after.get("quota", 0)) if info_after else "?"

    # 5. 构建通知
    success = checkin_data.get("success", False)
    msg_api = str(checkin_data.get("message", ""))

    footer = (
        f"👤 账户: {username}\n"
        f"💰 签到前余额: {balance_before}$\n"
        f"💰 当前余额: {balance_after}$\n"
        f"⏱️ 签到时间: {now}"
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
        print(f"✅ 签到成功 | 获得: {awarded_dollar}$")
        header = f"✅ 签到成功，本次获得 {awarded_dollar}$\n"

    elif any(kw in msg_api for kw in ("已签到", "重复签到", "今天已签到")):
        print(f"✅ 今日已签到 | 当前余额: {balance_after}$")
        header = "✅ 今日已签到过！\n"

    else:
        print(f"❌ 签到失败 | {msg_api}")
        header = f"❌ 签到失败: {msg_api}\n"

    send_notification(f"🎁 iamhc 签到通知\n\n{header}{footer}")
    return success


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    accounts = load_accounts()

    if not accounts:
        print(
            "❌ 未找到账户配置。请设置以下任一环境变量：\n"
            "   多账户: ACCOUNTS=email1:password1 (每行一个)\n"
            "   单账户: EMAIL=... 且 PASSWORD=..."
        )
        sys.exit(1)

    total   = len(accounts)
    results = []

    print(f"🚀 共检测到 {total} 个账户，开始批量签到...")

    for i, (email, password) in enumerate(accounts, 1):
        ok = run_checkin_for_account(email, password, i, total)
        results.append((email, ok))

    # 汇总报告
    print(f"\n{'=' * 30}")
    print(f"📊 批量签到完成 ({total} 个账户)")
    for email, ok in results:
        status = "✅" if ok else "❌"
        print(f"  {status} {email}")
    print("=" * 30)


if __name__ == "__main__":
    main()
