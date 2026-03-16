"""Central configuration loaded from environment."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
DATA_DIR = ROOT / os.getenv("DATA_DIR", "data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "logs").mkdir(exist_ok=True)

# ── DeepSeek ───────────────────────────────────────────────────────────────
DEEPSEEK_API_KEY = os.environ["DEEPSEEK_API_KEY"]
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_REASONER_MODEL = "deepseek-reasoner"

# ── Telegram ───────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_ALLOWED_USERS = [
    int(uid.strip())
    for uid in os.getenv("TELEGRAM_ALLOWED_USERS", "").split(",")
    if uid.strip()
]

# ── GitHub ─────────────────────────────────────────────────────────────────
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME", "")

# ── Google ─────────────────────────────────────────────────────────────────
GOOGLE_CREDENTIALS_FILE = DATA_DIR / os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GOOGLE_TOKEN_FILE = DATA_DIR / os.getenv("GOOGLE_TOKEN_FILE", "google_token.json")
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive",
]

# ── LinkedIn ───────────────────────────────────────────────────────────────
LINKEDIN_EMAIL = os.getenv("LINKEDIN_EMAIL", "")
LINKEDIN_PASSWORD = os.getenv("LINKEDIN_PASSWORD", "")
LINKEDIN_COOKIES_FILE = DATA_DIR / os.getenv("LINKEDIN_COOKIES_FILE", "linkedin_cookies.json")

# ── Agent behavior ─────────────────────────────────────────────────────────
AGENT_NAME = os.getenv("AGENT_NAME", "Dennis")
AGENT_TIMEZONE = os.getenv("AGENT_TIMEZONE", "America/New_York")
AUTONOMOUS_LOOP_INTERVAL = int(os.getenv("AUTONOMOUS_LOOP_INTERVAL", "300"))
MAX_TOOL_CALLS_PER_TURN = int(os.getenv("MAX_TOOL_CALLS_PER_TURN", "10"))
MAX_HISTORY_TURNS = int(os.getenv("MAX_HISTORY_TURNS", "20"))
MEMORY_MAX_RESULTS = int(os.getenv("MEMORY_MAX_RESULTS", "10"))

# ── Cost guard ─────────────────────────────────────────────────────────────
DAILY_API_CALL_BUDGET = int(os.getenv("DAILY_API_CALL_BUDGET", "200"))

# ── Quiet hours (local timezone, 0-23) ─────────────────────────────────────
# Notifications generated outside [QUIET_HOURS_END, QUIET_HOURS_START) are queued.
QUIET_HOURS_START = int(os.getenv("QUIET_HOURS_START", "22"))
QUIET_HOURS_END = int(os.getenv("QUIET_HOURS_END", "7"))
MAX_NOTIFICATIONS_PER_HOUR = int(os.getenv("MAX_NOTIFICATIONS_PER_HOUR", "5"))

# ── Proactive email triage ─────────────────────────────────────────────────
# Comma-separated sender addresses that always get an immediate alert
PRIORITY_EMAIL_SENDERS = [
    s.strip() for s in os.getenv("PRIORITY_EMAIL_SENDERS", "").split(",") if s.strip()
]
# Keywords in subject/body that make an email high-priority
PRIORITY_EMAIL_KEYWORDS = [
    k.strip()
    for k in os.getenv("PRIORITY_EMAIL_KEYWORDS", "urgent,asap,action required,time sensitive").split(",")
    if k.strip()
]
# How often to scan for priority emails (seconds); 0 to disable
PRIORITY_EMAIL_CHECK_INTERVAL = int(os.getenv("PRIORITY_EMAIL_CHECK_INTERVAL", "900"))

# ── Voice transcription ────────────────────────────────────────────────────
# faster-whisper model size: tiny (39MB), base (74MB), small (244MB)
# Use "tiny" on a Raspberry Pi, "base" or "small" on a Mac mini
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")

# ── Webhook server ─────────────────────────────────────────────────────────
# Set WEBHOOK_PORT=0 to disable the webhook server
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8765"))
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")  # Required if WEBHOOK_PORT > 0

# ── Memory retention ───────────────────────────────────────────────────────
# Raw conversation turns older than this are summarised and pruned from ChromaDB
MEMORY_RETENTION_DAYS = int(os.getenv("MEMORY_RETENTION_DAYS", "90"))

# ── Lightweight mode (Raspberry Pi or low-RAM devices) ─────────────────────
# Replaces Playwright web browsing with httpx+BeautifulSoup4, skips LinkedIn
LIGHTWEIGHT_MODE = os.getenv("LIGHTWEIGHT_MODE", "false").lower() == "true"

# ── Storage paths ──────────────────────────────────────────────────────────
MEMORY_DB_PATH = str(DATA_DIR / "memory.db")
CHROMA_DB_PATH = str(DATA_DIR / "chroma_db")
