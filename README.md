# IG Hide Followers — Telegram Bot

Self-hosted Telegram bot to **hide or unhide** your Instagram followers & following lists using your own session ID.

## Features

- Inline button UI (Hide / Unhide / Help / About)
- Session ID prompt (message auto-deleted when possible)
- Optional allow-list of Telegram user IDs
- Clear success / error messages
- No database — session is not saved

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env → put BOT_TOKEN (and optional ALLOWED_USERS)
python bot.py
```

`.env` loads automatically. No `export` or bash env commands needed.

## Commands

| Command   | Action                |
|-----------|------------------------|
| /start    | Open main menu         |
| /help     | Session ID guide       |
| /cancel   | Abort current action   |

## Get Instagram Session ID

1. Log into Instagram in a browser  
2. F12 → Application → Cookies → `instagram.com`  
3. Copy `sessionid` value  

## Warnings

- Instagram **private API** → against Instagram Terms of Service  
- Session ID = full account access — treat like a password  
- Only use on **accounts you own**  
- Self-host only; do not run a public bot that collects strangers’ sessions  

## Premium custom emoji

Telegram Premium custom emoji need your own emoji pack IDs.  
This bot uses high-quality Unicode emoji + Markdown formatting for a clean premium look.  
You can replace emoji in `bot.py` with `tg://emoji?id=...` custom entities if you own packs.
