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
LINKEDIN_COOKIES_FILE = ROOT / os.getenv("LINKEDIN_COOKIES_FILE", "data/linkedin_cookies.json")

# ── Agent behavior ─────────────────────────────────────────────────────────
AGENT_NAME = os.getenv("AGENT_NAME", "Dennis")
AGENT_TIMEZONE = os.getenv("AGENT_TIMEZONE", "America/New_York")
AUTONOMOUS_LOOP_INTERVAL = int(os.getenv("AUTONOMOUS_LOOP_INTERVAL", "300"))
MAX_TOOL_CALLS_PER_TURN = int(os.getenv("MAX_TOOL_CALLS_PER_TURN", "10"))
MAX_HISTORY_TURNS = int(os.getenv("MAX_HISTORY_TURNS", "20"))
MEMORY_MAX_RESULTS = int(os.getenv("MEMORY_MAX_RESULTS", "10"))

# ── Cost guard ─────────────────────────────────────────────────────────────
# Set to 0 to disable. Counts API calls (not tokens) as a cheap proxy for spend.
DAILY_API_CALL_BUDGET = int(os.getenv("DAILY_API_CALL_BUDGET", "200"))

# ── Storage paths ──────────────────────────────────────────────────────────
MEMORY_DB_PATH = str(DATA_DIR / "memory.db")
CHROMA_DB_PATH = str(DATA_DIR / "chroma_db")
GOALS_DB_PATH = str(DATA_DIR / "goals.db")
