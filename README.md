# Dennis – Persistent Mac Mini AI Assistant

A fully autonomous AI assistant that:
- Lives permanently on your Mac mini (auto-starts, auto-restarts)
- Talks to you via **Telegram** from your phone
- Uses **DeepSeek** as its brain (pay-per-token cloud API)
- Pursues your **goals autonomously** in the background
- Has **persistent memory** (remembers everything across restarts)
- Can access: **Gmail, Calendar, LinkedIn, GitHub, web, Mac shell**

---

## Quick Start

### 1. Prerequisites
- Mac mini running macOS Monterey+
- Python 3.11+
- A Telegram account
- DeepSeek API key (https://platform.deepseek.com)

### 2. Install
```bash
git clone <this-repo> ~/Dennis
cd ~/Dennis
bash scripts/setup_mac.sh
```

### 3. Configure credentials
```bash
cp .env.example .env
nano .env   # Fill in all values (see below)
```

### 4. Set up Telegram bot
1. Open Telegram → search for `@BotFather`
2. Send `/newbot`, follow prompts
3. Copy the token → paste into `TELEGRAM_BOT_TOKEN` in `.env`
4. Find your user ID: search `@userinfobot` → paste into `TELEGRAM_ALLOWED_USERS`

### 5. Set up Google access (Gmail/Calendar)
```bash
source .venv/bin/activate
python scripts/google_auth.py   # Opens browser for OAuth
```

### 6. Start Dennis
**As a background service (recommended):**
```bash
bash scripts/install_service.sh
```

**Manually (for testing):**
```bash
source .venv/bin/activate
python main.py
```

---

## Credentials Reference

| Variable | Where to get it |
|---|---|
| `DEEPSEEK_API_KEY` | https://platform.deepseek.com → API Keys |
| `TELEGRAM_BOT_TOKEN` | @BotFather on Telegram |
| `TELEGRAM_ALLOWED_USERS` | @userinfobot on Telegram (your numeric ID) |
| `GITHUB_TOKEN` | GitHub → Settings → Developer settings → Personal access tokens |
| `LINKEDIN_EMAIL/PASSWORD` | Your LinkedIn login credentials |
| `GOOGLE_CREDENTIALS_FILE` | Google Cloud Console → APIs & Services → Credentials (OAuth Desktop app) |

---

## Using Dennis

### Telegram Commands
- `/start` – Introduction and command list
- `/goals` – View active autonomous goals
- `/memory <query>` – Search your memory
- `/status` – Agent status
- `/clear` – Clear conversation history

### Example conversations
```
You: Research the top 5 CPA firm referral networks and find BD contacts
Dennis: [runs web research autonomously, saves findings, reports back]

You: Draft a LinkedIn post about tax season tips for small businesses
Dennis: [drafts post, shows it to you for approval before posting]

You: Set a goal to find 10 potential BD partners every week
Dennis: [creates a persistent goal, starts working on it in background]

You: What emails do I need to respond to today?
Dennis: [checks Gmail, summarizes important unread emails]
```

### Safety guardrails
Dennis will **always ask for your approval** before:
- Sending any email
- Posting to LinkedIn
- Sending LinkedIn connection requests
- Running shell commands that modify system state

---

## Architecture

```
main.py                 ← Entry point
├── agent/
│   ├── core.py         ← DeepSeek LLM + tool-use loop
│   ├── memory.py       ← ChromaDB (semantic) + SQLite (structured)
│   └── scheduler.py    ← APScheduler autonomous background loop
├── bot/
│   └── telegram.py     ← Telegram bot (python-telegram-bot)
├── tools/
│   ├── registry.py     ← Tool definitions + dispatcher
│   ├── shell.py        ← macOS shell
│   ├── browser.py      ← Playwright web scraping
│   ├── github_tool.py  ← GitHub API
│   ├── google_tool.py  ← Gmail + Calendar
│   └── linkedin_tool.py← LinkedIn via Playwright
└── scripts/
    ├── setup_mac.sh          ← One-time setup
    ├── install_service.sh    ← Install launchd service
    └── google_auth.py        ← One-time Google OAuth
```

## Logs
```bash
tail -f ~/Dennis/data/logs/dennis.log
tail -f ~/Dennis/data/logs/stderr.log
```
