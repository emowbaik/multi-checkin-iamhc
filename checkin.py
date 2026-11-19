#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Multi-account auto check-in for api.hcnsec.cn (new-api fork).

Since 2026-11-19 the login endpoint requires a Cloudflare Turnstile token
(without one it answers `Turnstile token is empty`), so a plain `requests`
login stopped working. That is why the previous version reported
"Login failed" for every account.

The token is minted by a local Boterdrop solver (Camoufox) started by this
script, and the login + check-in POSTs leave through the SAME egress IP the
token was minted from — Cloudflare rejects a token presented from a different
IP. Set PROXY to route both through one residential exit when the runner IP
is rejected.

Environment:
    ACCOUNTS        one "email:password" per line (multi-account)
    EMAIL/PASSWORD  single-account fallback
    PROXY           optional http://user:pass@host:port (solver + requests)
    SOLVER_URL      reuse a running solver instead of starting one
    SOLVER_ROOT     solver checkout (default /tmp/boterdrop-solver)
    START_SOLVER    "1" to boot the bundled solver on SOLVER_PORT (default 8123)
    SOLVER_PORT     port for the local solver (default 8123)
    TG_BOT_TOKEN / TG_CHAT_ID   optional Telegram report
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BASE_URL = "https://api.hcnsec.cn"
TURNSTILE_SITEKEY = os.environ.get("TURNSTILE_SITEKEY", "0x4AAAAAAFIovBqwE9xMkrm_")
QUOTA_PER_UNIT = 500000  # new-api default: 500000 quota = $1
CST = timezone(timedelta(hours=8))

SOLVE_TIMEOUT_SEC = 90
DELAY_BETWEEN_ACCOUNTS_SEC = 3


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_accounts() -> list[tuple[str, str]]:
    raw = os.environ.get("ACCOUNTS", "").strip()
    accounts: list[tuple[str, str]] = []
    if raw:
        for line_no, line in enumerate(raw.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            if ":" not in line:
                print(f"⚠️  ACCOUNTS line {line_no} is malformed (expected email:password) — skipped")
                continue
            email, password = line.split(":", 1)
            email, password = email.strip(), password.strip()
            if email and password:
                accounts.append((email, password))
            else:
                print(f"⚠️  ACCOUNTS line {line_no} has empty email or password — skipped")
        return accounts

    email = os.environ.get("EMAIL", "").strip()
    password = os.environ.get("PASSWORD", "").strip()
    if email and password:
        return [(email, password)]
    return []


def quota_to_dollar(quota) -> float:
    try:
        return round(float(quota) / QUOTA_PER_UNIT, 2)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# HTTP helpers (one session, one egress IP)
# ---------------------------------------------------------------------------

def http_json(url: str, *, method: str = "GET", body: dict | None = None,
              headers: dict | None = None, timeout: int = 30) -> tuple[int, dict | None]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json, text/plain, */*")
    req.add_header("User-Agent", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                                "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    req.add_header("Origin", BASE_URL)
    req.add_header("Referer", f"{BASE_URL}/login")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
    except Exception as exc:  # noqa: BLE001
        return 0, {"message": str(exc)}
    try:
        return status, json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return status, {"message": raw.decode("utf-8", "replace")[:300]}


class Solver:
    """Thin client for the Boterdrop solver (Camoufox) HTTP API."""

    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")

    def wait_ready(self, timeout: int = 120) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"{self.base}/docs", timeout=5) as resp:
                    if resp.status == 200:
                        return True
            except Exception:  # noqa: BLE001
                time.sleep(2)
        return False

    def turnstile(self, url: str, sitekey: str) -> str | None:
        query = urllib.parse.urlencode({"url": url, "sitekey": sitekey})
        status, data = http_json(f"{self.base}/turnstile?{query}", timeout=30)
        task_id = (data or {}).get("task_id")
        if not task_id:
            print(f"   solver rejected task: {data}")
            return None
        deadline = time.time() + SOLVE_TIMEOUT_SEC
        while time.time() < deadline:
            time.sleep(2)
            _, result = http_json(f"{self.base}/result?id={task_id}", timeout=20)
            state = (result or {}).get("status")
            if state == "success":
                return (result or {}).get("value")
            if state == "error":
                print(f"   solver error: {result}")
                return None
        print("   solver timed out")
        return None


def start_solver() -> Solver | None:
    """Boot the bundled solver (Camoufox) on SOLVER_PORT when asked to."""
    port = os.environ.get("SOLVER_PORT", "8123")
    solver = Solver(os.environ.get("SOLVER_URL") or f"http://127.0.0.1:{port}")
    if os.environ.get("SOLVER_URL"):
        return solver if solver.wait_ready(60) else None

    if os.environ.get("START_SOLVER") != "1":
        print("ℹ️  SOLVER_URL not set and START_SOLVER != 1 — cannot mint a Turnstile token")
        return None

    root = os.environ.get("SOLVER_ROOT", "/tmp/boterdrop-solver")
    runner = os.path.join(root, "run_solver.py")
    if not os.path.exists(runner):
        print(f"❌ solver launcher missing: {runner}")
        return None

    proxy = os.environ.get("PROXY", "").strip()
    env = dict(os.environ)
    env["SOLVER_PORT"] = port
    print(f"starting solver on :{port} (proxy={'yes' if proxy else 'no'})")
    log = open(os.path.join("/tmp", "solver.log"), "wb")
    subprocess.Popen([sys.executable, runner], cwd=root, env=env, stdout=log, stderr=log)
    return solver if solver.wait_ready(180) else None


# ---------------------------------------------------------------------------
# Telegram report
# ---------------------------------------------------------------------------

def send_notification(message: str) -> None:
    token = os.environ.get("TG_BOT_TOKEN", "")
    chat = os.environ.get("TG_CHAT_ID", "")
    print("\n" + "=" * 34)
    print(message)
    print("=" * 34)
    if not (token and chat):
        print("TG config absent — skipping notification")
        return
    status, _ = http_json(
        f"https://api.telegram.org/bot{token}/sendMessage",
        method="POST", body={"chat_id": chat, "text": message[:4000], "parse_mode": "HTML"},
        timeout=15,
    )
    print("notification sent" if status == 200 else f"notification failed: {status}")


# ---------------------------------------------------------------------------
# Per-account flow
# ---------------------------------------------------------------------------

def checkin_account(solver: Solver | None, email: str, password: str,
                    index: int, total: int) -> dict:
    prefix = f"[{index}/{total}]"
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'-' * 30}\n{prefix} {email}")

    if solver is None:
        return {"email": email, "ok": False, "error": "no solver", "time": now}

    token = solver.turnstile(f"{BASE_URL}/login", TURNSTILE_SITEKEY)
    if not token:
        return {"email": email, "ok": False, "error": "turnstile solve failed", "time": now}
    print(f"{prefix} turnstile token minted ({len(token)} chars)")

    login_url = f"{BASE_URL}/api/user/login?turnstile={urllib.parse.quote(token)}"
    status, body = http_json(login_url, method="POST",
                             body={"username": email, "password": password})
    body = body or {}
    if not body.get("success"):
        message = str(body.get("message", ""))
        retry_hint = ""
        if "Turnstile" in message:
            retry_hint = " (token rejected — the exit IP must match the solve IP)"
        return {"email": email, "ok": False,
                "error": f"login: {message}{retry_hint}"[:160], "time": now}

    data = body.get("data") or {}
    user_id = data.get("id")
    username = data.get("username") or email
    print(f"{prefix} logged in as {username} (id {user_id})")

    headers = {"New-Api-User": str(user_id)}
    _, before = http_json(f"{BASE_URL}/api/user/self", headers=headers)
    quota_before = quota_to_dollar(((before or {}).get("data") or {}).get("quota", 0))

    status, resp = http_json(f"{BASE_URL}/api/user/checkin", method="POST",
                             body={}, headers=headers)
    resp = resp or {}
    message = str(resp.get("message", ""))

    _, after = http_json(f"{BASE_URL}/api/user/self", headers=headers)
    quota_after = quota_to_dollar(((after or {}).get("data") or {}).get("quota", 0))

    success = bool(resp.get("success"))
    already = any(k in message for k in ("已签到", "重复签到", "今天已签到"))
    awarded = round(quota_after - quota_before, 2) if success else 0.0

    if success:
        print(f"{prefix} ✅ checked in (+{awarded}$)")
    elif already:
        print(f"{prefix} ✅ already checked in today")
    else:
        print(f"{prefix} ❌ check-in failed: {message}")

    return {
        "email": email,
        "ok": success or already,
        "awarded": awarded,
        "balance": quota_after,
        "message": message or ("already" if already else ""),
        "time": now,
    }


def build_report(results: list[dict]) -> str:
    ok = [r for r in results if r["ok"]]
    bad = [r for r in results if not r["ok"]]
    lines = [
        "🎁 <b>iamhc Check-in Report</b>",
        f"✅ {len(ok)} ok · ❌ {len(bad)} failed · total {len(results)}",
        "",
    ]
    for r in results:
        icon = "✅" if r["ok"] else "❌"
        if r.get("awarded"):
            extra = f"+{r['awarded']}$"
        elif r.get("message"):
            extra = r["message"][:60]
        else:
            extra = (r.get("error") or "")[:70]
        lines.append(f"{icon} {r['email']} — {extra}")
    if ok:
        lines.append("")
        lines.append(f"💰 balance: {round(sum(r.get('balance', 0) for r in ok), 2)}$")
    if results:
        lines.append(f"⏱️ {results[0]['time']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    accounts = load_accounts()
    if not accounts:
        print("❌ No accounts. Set ACCOUNTS=email:password (one per line) or EMAIL/PASSWORD.")
        return 1

    print(f"🚀 {len(accounts)} account(s) — solver + check-in")

    solver = start_solver()
    if solver is None:
        print("❌ No Turnstile solver available — every login would fail on "
              "'Turnstile token is empty'. Set SOLVER_URL or START_SOLVER=1.")
        return 1

    results: list[dict] = []
    for index, (email, password) in enumerate(accounts, 1):
        try:
            result = checkin_account(solver, email, password, index, len(accounts))
        except Exception as exc:  # noqa: BLE001
            result = {"email": email, "ok": False, "error": str(exc)[:200],
                      "time": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")}
            print(f"[{index}/{len(accounts)}] ❌ error: {exc}")
        results.append(result)
        if index < len(accounts):
            time.sleep(DELAY_BETWEEN_ACCOUNTS_SEC)

    print(f"\n{'=' * 34}")
    for r in results:
        print(f"  {'✅' if r['ok'] else '❌'} {r['email']}")
    print("=" * 34)

    send_notification(build_report(results))
    return 0 if any(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
