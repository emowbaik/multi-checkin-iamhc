# iamhc Auto Check-in Script

Automatically logs in to [api.hcnsec.cn](https://api.hcnsec.cn) and performs a daily check-in, with optional Telegram notifications.  
Supports **multi-account batch check-in**.

---

## Configuration — Secrets

Go to **Settings → Secrets and variables → Actions** in your repository and add the following secrets:

### Multi-account mode (recommended)

| Secret Name | Description |
|-------------|-------------|
| `ACCOUNTS` | One account per line, format: `email:password` |
| `TG_BOT_TOKEN` | Telegram Bot Token (optional) |
| `TG_CHAT_ID` | Telegram Chat ID (optional) |

**Example value for `ACCOUNTS`:**
```
alice@gmail.com:password123
bob@gmail.com:mypassword456
user3@example.com:anotherpass
```

> Passwords containing a colon (`:`) are supported — the script splits only on the **first** colon.

### Single-account mode (backward-compatible)

If you prefer not to use `ACCOUNTS`, the old two-secret approach still works:

| Secret Name | Description |
|-------------|-------------|
| `EMAIL` | Login email |
| `PASSWORD` | Login password |

---

## Manual Trigger

Go to the **Actions** tab in your repository, select the `iamhc Daily Checkin` workflow, and click **Run workflow**.

---

## Getting a Telegram Bot Token and Chat ID

1. Search for `@BotFather` on Telegram, send `/newbot` to create a bot, and copy the **Bot Token**.
2. Search for `@userinfobot`, send any message, and copy your **Chat ID**.
3. Send your bot at least one message first to activate the conversation — otherwise the bot cannot push notifications to you.

---

## Credits

This project is based on the original work by **[eooce](https://github.com/eooce)**:

> 📦 [eooce/Auto-checkin-iamhc](https://github.com/eooce/Auto-checkin-iamhc)

The following improvements were made on top of the original:

- ✨ **Multi-account support** — batch check-in via the `ACCOUNTS` secret (one `email:password` per line)
- 🔧 **Error handling** — all HTTP calls are now wrapped with `try/except` and `raise_for_status()`
- 💰 **Decimal balance display** — balances now show 2 decimal places instead of rounding to integers
- 🕐 **Proper timezone handling** — replaced manual UTC+8 offset with Python's `datetime.timezone`
- 🌐 **English UI** — all messages, logs, and notifications translated to English
- 🔁 **Fixed GitHub Actions versions** — upgraded from non-existent `@v6` to stable `@v4`
