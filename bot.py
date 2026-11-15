#!/usr/bin/env python3
"""
IG Hide Followers — Telegram Bot (self-hosted)
Hide / unhide YOUR Instagram followers & following list via session ID.

Setup:
  1. pip install -r requirements.txt
  2. Copy .env.example to .env and set BOT_TOKEN
  3. python bot.py

Security:
  - Run only for yourself or trusted private use.
  - Session IDs are passwords — never share them publicly.
  - Uses Instagram private API (ToS risk).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# ─── Auto-load .env (no export / bash needed) ─────────────
def _load_env():
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.is_file():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    except OSError:
        pass

_load_env()

# ─── Config ───────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ALLOWED_USERS = {
    int(x.strip())
    for x in os.getenv("ALLOWED_USERS", "").split(",")
    if x.strip().isdigit()
}  # empty = allow all (not recommended)

# Conversation states
WAIT_SESSION = 1

# Instagram API
API = "https://i.instagram.com/graphql/query"
APP_ID = "124024574287414"
NODE = "IGSettingsBooleanMutation"
ROOT = "xdt_api__v1__settings__set_bool"
SETTING_ID = "hide_followers_following_list"

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("ig-hide-bot")

# ─── Instagram core ───────────────────────────────────────

def parse_session(session: str) -> str:
    if not session:
        raise ValueError("Session ID is empty.")
    if any(ord(c) <= 32 or ord(c) >= 127 or c in "\";" for c in session):
        raise ValueError("Session ID contains invalid characters.")
    m = re.fullmatch(r"([1-9][0-9]*)(?::|%3[aA]).+", session)
    if not m:
        raise ValueError("Invalid session format. Expected: USERID%3aTOKEN…")
    return m.group(1)


def make_auth(user_id: str, session: str) -> str:
    payload = {
        "ds_user_id": user_id,
        "sessionid": session,
        "should_use_header_over_cookies": True,
    }
    token = base64.b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode()
    return "Bearer IGT:2:" + token


def set_hide(session: str, value: bool) -> dict:
    user_id = parse_session(session)
    auth = make_auth(user_id, session)
    variables = {
        "setting_id": SETTING_ID,
        "allow_error_codes": True,
        "callsite": "account_privacy",
        "value": value,
    }
    form = {
        "method": "post",
        "format": "json",
        "server_timestamps": "true",
        "locale": "user",
        "fb_api_req_friendly_name": NODE,
        "client_doc_id": "2669261950526978627082629536",
        "variables": json.dumps(variables),
    }
    headers = {
        "Authorization": auth,
        "Cookie": f"sessionid={session}; ds_user_id={user_id}",
        "IG-INTENDED-USER-ID": user_id,
        "X-IG-App-ID": APP_ID,
        "X-Auth-Type": "instagram",
        "User-Agent": "Instagram 453.0.0",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept-Encoding": "identity",
        "X-GraphQL-Client-Library": "pando",
        "X-FB-Friendly-Name": NODE,
    }

    class BlockRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            raise RuntimeError("Redirect blocked.")

    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        BlockRedirect(),
    )
    req = urllib.request.Request(
        API,
        data=urllib.parse.urlencode(form).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with opener.open(req, timeout=20) as resp:
            raw = resp.read(1_048_577)
            if len(raw) > 1_048_576:
                raise RuntimeError("Response too large.")
            return json.loads(raw)
    except urllib.error.HTTPError as err:
        body = err.read(16_385)
        details = {}
        try:
            data = json.loads(body) if len(body) <= 16_384 else {}
            if isinstance(data, dict):
                for k in ("message", "error_type", "status", "code"):
                    if isinstance(data.get(k), (str, int, bool)):
                        details[k] = data[k]
        except (ValueError, UnicodeError):
            pass
        msg = json.dumps(details) if details else "No details."
        for secret in filter(None, [auth, session, urllib.parse.unquote(session)]):
            msg = msg.replace(str(secret), "<REDACTED>")
        raise RuntimeError(f"HTTP {err.code}: {msg[:800]}") from None


def check_success(data: dict, expected: bool) -> bool:
    if not isinstance(data, dict):
        return False
    if data.get("errors") or data.get("error") or data.get("status") == "fail":
        return False
    values = data.get("data")
    if not isinstance(values, dict):
        return False
    found = [
        v for k, v in values.items()
        if k == ROOT or k.startswith(ROOT + "(")
    ]
    if len(found) != 1 or not isinstance(found[0], dict):
        return False
    res = found[0]
    if any(
        res.get(k)
        for k in (
            "error_name_value",
            "errorNameValue",
            "fallback_message",
            "fallbackMessage",
        )
    ):
        return False
    return res.get("value") is expected


# ─── Access control ───────────────────────────────────────

def allowed(user_id: int | None) -> bool:
    if not ALLOWED_USERS:
        return True
    return user_id in ALLOWED_USERS


# ─── UI copy (premium-style emoji presentation) ───────────

def home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔒 Hide lists", callback_data="action_hide"),
            InlineKeyboardButton("👁 Unhide lists", callback_data="action_show"),
        ],
        [
            InlineKeyboardButton("📖 How to get Session ID", callback_data="help_session"),
            InlineKeyboardButton("ℹ About", callback_data="about"),
        ],
    ])


WELCOME = """
✨ *IG Privacy Control*

Hide or show your Instagram *followers* & *following* lists in one tap.

🔐 Uses *your* session ID only  
⚡ Fast private API action  
🛡 Self-hosted — data stays with you

Tap a button below to start.
"""

ABOUT = """
💎 *About this bot*

• Changes the Instagram setting  
  `Hide followers and following lists`
• Works with *your own* account session
• Self-hosted Telegram bot (you control the token)

• Instagram private API → *ToS risk*
• Never share session IDs in public chats

Made for personal privacy control.
"""

HELP_SESSION = """
🔑 *How to get your Session ID*

1️⃣ Open Instagram in browser (logged in)  
2️⃣ Press `F12` → *Application* / *Storage*  
3️⃣ Cookies → `instagram.com`  
4️⃣ Copy the value of `sessionid`

Format looks like:
`1234567890%3aAbCdEf…`

⚠ Treat it like a password.  
Revoke by logging out other sessions if leaked.
"""

ASK_SESSION = """
🔐 *Send your Instagram Session ID*

Reply with the session ID for *your* account.

• Input is processed once and not stored  
• Use a private chat with this bot only  
• Type /cancel to abort
"""


# ─── Handlers ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not allowed(user.id if user else None):
        await update.message.reply_text("⛔ You are not allowed to use this bot.")
        return
    await update.message.reply_text(
        WELCOME,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=home_keyboard(),
    )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    if not allowed(user.id if user else None):
        await query.edit_message_text("⛔ Not allowed.")
        return ConversationHandler.END

    data = query.data or ""

    if data == "about":
        await query.edit_message_text(
            ABOUT,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=home_keyboard(),
        )
        return ConversationHandler.END

    if data == "help_session":
        await query.edit_message_text(
            HELP_SESSION,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=home_keyboard(),
        )
        return ConversationHandler.END

    if data in ("action_hide", "action_show"):
        context.user_data["hide"] = data == "action_hide"
        action = "HIDE" if context.user_data["hide"] else "UNHIDE"
        await query.edit_message_text(
            f"🎯 Action selected: *{action}*\n\n{ASK_SESSION}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return WAIT_SESSION

    return ConversationHandler.END


async def receive_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not allowed(user.id if user else None):
        await update.message.reply_text("⛔ Not allowed.")
        return ConversationHandler.END

    session = (update.message.text or "").strip()
    # Delete user message to reduce session exposure in chat history
    try:
        await update.message.delete()
    except Exception:
        pass

    hide = bool(context.user_data.get("hide", True))
    action_word = "Hiding" if hide else "Unhiding"

    status = await update.message.reply_text(
        f"⏳ {action_word} your lists…\nPlease wait."
    )

    try:
        result = set_hide(session, hide)
        if check_success(result, hide):
            msg = (
                "✅ *Success*\n\n"
                + (
                    "Your followers & following lists are now *hidden*."
                    if hide
                    else "Your followers & following lists are now *visible*."
                )
            )
        else:
            msg = (
                "⚠️ *Not confirmed*\n\n"
                "Instagram did not confirm the change.\n"
                "Session may be expired, or the API changed."
            )
    except ValueError as err:
        msg = f"⚠️ *Invalid input*\n\n`{err}`"
    except RuntimeError as err:
        msg = f"❌ *Request failed*\n\n`{err}`"
    except Exception as err:
        log.exception("unexpected")
        msg = f"❌ *Error*\n\n`{type(err).__name__}: {err}`"

    try:
        await status.edit_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=home_keyboard())
    except Exception:
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=home_keyboard())

    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "❎ Cancelled.",
        reply_markup=home_keyboard(),
    )
    return ConversationHandler.END


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        HELP_SESSION,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=home_keyboard(),
    )


def main() -> None:
    if not BOT_TOKEN:
        print("Set BOT_TOKEN environment variable (from @BotFather).")
        raise SystemExit(1)

    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(on_callback)],
        states={
            WAIT_SESSION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_session)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(conv)
    # Callbacks outside conversation (about / help buttons after end)
    app.add_handler(CallbackQueryHandler(on_callback))

    log.info("IG Hide bot starting…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
