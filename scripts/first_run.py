#!/usr/bin/env python3
"""
Dennis – First-run setup wizard.

Walks you through configuring all required credentials and API keys,
tests each one, and runs Google OAuth. Run this once before starting Dennis.

Usage:
    python scripts/first_run.py
"""
import getpass
import os
import sys
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ── Helpers ────────────────────────────────────────────────────────────────

def _prompt(label: str, default: str = "", secret: bool = False) -> str:
    display = label
    if default:
        display += f" [{default}]"
    display += ": "
    try:
        val = getpass.getpass(display) if secret else input(display)
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.")
        sys.exit(0)
    return val.strip() or default


def _read_env() -> dict:
    env_path = ROOT / ".env"
    existing = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()
    return existing


def _write_env(values: dict):
    env_path = ROOT / ".env"
    lines = []
    for key, val in sorted(values.items()):
        lines.append(f"{key}={val}")
    env_path.write_text("\n".join(lines) + "\n")
    print(f"  ✅ Saved to {env_path}")


def _section(title: str):
    print(f"\n{'─' * 50}")
    print(f"  {title}")
    print(f"{'─' * 50}")


# ── API key validators ─────────────────────────────────────────────────────

def _test_deepseek(api_key: str) -> bool:
    print("  Testing DeepSeek API key...", end=" ", flush=True)
    try:
        import httpx
        r = httpx.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": "Say OK"}],
                "max_tokens": 5,
            },
            timeout=15,
        )
        if r.status_code == 200:
            print("✅")
            return True
        print(f"❌ HTTP {r.status_code}: {r.text[:100]}")
        return False
    except Exception as e:
        print(f"❌ {e}")
        return False


def _test_telegram(token: str) -> bool:
    print("  Testing Telegram token...", end=" ", flush=True)
    try:
        import httpx
        r = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        data = r.json()
        if data.get("ok"):
            username = data["result"].get("username", "unknown")
            print(f"✅  Bot: @{username}")
            return True
        print(f"❌ {data.get('description', 'Unknown error')}")
        return False
    except Exception as e:
        print(f"❌ {e}")
        return False


def _test_github(token: str) -> bool:
    print("  Testing GitHub token...", end=" ", flush=True)
    try:
        import httpx
        r = httpx.get(
            "https://api.github.com/user",
            headers={"Authorization": f"token {token}"},
            timeout=10,
        )
        if r.status_code == 200:
            login = r.json().get("login", "unknown")
            print(f"✅  Logged in as: {login}")
            return True
        print(f"❌ HTTP {r.status_code}")
        return False
    except Exception as e:
        print(f"❌ {e}")
        return False


def _run_google_auth() -> bool:
    """Run the Google OAuth flow (opens browser)."""
    print("  Opening browser for Google OAuth authorization...")
    try:
        # Import after sys.path is set
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        import config
        from google_auth_oauthlib.flow import InstalledAppFlow

        if not config.GOOGLE_CREDENTIALS_FILE.exists():
            print(f"  ❌ credentials.json not found at {config.GOOGLE_CREDENTIALS_FILE}")
            return False

        flow = InstalledAppFlow.from_client_secrets_file(
            str(config.GOOGLE_CREDENTIALS_FILE), config.GOOGLE_SCOPES
        )
        creds = flow.run_local_server(port=0)
        config.GOOGLE_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(str(config.GOOGLE_TOKEN_FILE), "w") as f:
            f.write(creds.to_json())
        print(f"  ✅ Google token saved to {config.GOOGLE_TOKEN_FILE}")
        return True
    except Exception as e:
        print(f"  ❌ Google auth failed: {e}")
        print("  Run manually: python scripts/google_auth.py")
        return False


# ── Main wizard ────────────────────────────────────────────────────────────

def main():
    print(dedent("""
    ╔════════════════════════════════════════════════╗
    ║        Dennis Agent – First-Run Setup          ║
    ╚════════════════════════════════════════════════╝

    This wizard configures all credentials and API keys.
    Your credentials are stored locally in .env – never shared.

    Press Ctrl-C at any time to quit without saving.
    """))

    existing = _read_env()
    values = dict(existing)  # Start with whatever is already set

    # ── 1. DeepSeek (required) ─────────────────────────────────────────────
    _section("1. DeepSeek API  (REQUIRED)")
    print("  Get your key at: https://platform.deepseek.com/api_keys")
    key = _prompt("  DEEPSEEK_API_KEY", existing.get("DEEPSEEK_API_KEY", ""), secret=True)
    if key:
        _test_deepseek(key)
        values["DEEPSEEK_API_KEY"] = key
    else:
        print("  ⚠️  No key entered – Dennis will not start without this.")

    # ── 2. Telegram ────────────────────────────────────────────────────────
    _section("2. Telegram Bot  (REQUIRED)")
    print("  Steps:")
    print("    a) Open Telegram and message @BotFather")
    print("    b) Send /newbot and follow the prompts")
    print("    c) Copy the token BotFather gives you")
    token = _prompt("  TELEGRAM_BOT_TOKEN", existing.get("TELEGRAM_BOT_TOKEN", ""), secret=True)
    if token:
        _test_telegram(token)
        values["TELEGRAM_BOT_TOKEN"] = token

    print()
    print("  Your Telegram user ID (send a message to @userinfobot to get it):")
    allowed = _prompt("  TELEGRAM_ALLOWED_USERS", existing.get("TELEGRAM_ALLOWED_USERS", ""))
    if allowed:
        values["TELEGRAM_ALLOWED_USERS"] = allowed

    # ── 3. Agent settings ──────────────────────────────────────────────────
    _section("3. Agent Settings")
    values["AGENT_NAME"] = _prompt(
        "  Agent name", existing.get("AGENT_NAME", "Dennis")
    )
    values["AGENT_TIMEZONE"] = _prompt(
        "  Timezone (e.g. America/New_York, America/Los_Angeles, Europe/London)",
        existing.get("AGENT_TIMEZONE", "America/New_York"),
    )
    values["AUTONOMOUS_LOOP_INTERVAL"] = _prompt(
        "  Background check interval in seconds (300 = every 5 min)",
        existing.get("AUTONOMOUS_LOOP_INTERVAL", "300"),
    )
    values["MAX_TOOL_CALLS_PER_TURN"] = _prompt(
        "  Max tool calls per conversation turn",
        existing.get("MAX_TOOL_CALLS_PER_TURN", "10"),
    )

    # ── 4. GitHub (optional) ───────────────────────────────────────────────
    _section("4. GitHub  (optional)")
    print("  Create a Personal Access Token at:")
    print("  https://github.com/settings/tokens  (needs repo, read:user scopes)")
    gh_token = _prompt("  GITHUB_TOKEN (Enter to skip)", existing.get("GITHUB_TOKEN", ""), secret=True)
    if gh_token:
        if _test_github(gh_token):
            values["GITHUB_TOKEN"] = gh_token
            values["GITHUB_USERNAME"] = _prompt(
                "  GITHUB_USERNAME", existing.get("GITHUB_USERNAME", "")
            )
    else:
        print("  Skipping GitHub.")

    # ── 5. Google (Gmail + Calendar) ───────────────────────────────────────
    _section("5. Google  (Gmail + Calendar, optional)")
    data_dir = ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    print("  Steps to get credentials.json:")
    print("    a) Go to https://console.cloud.google.com/")
    print("    b) Create/select a project")
    print("    c) Enable: Gmail API, Google Calendar API, Google Drive API")
    print("    d) Create OAuth 2.0 credentials → Desktop App")
    print("    e) Download as 'credentials.json' and place it here:")
    print(f"       {data_dir}/credentials.json")

    # Also accept old root-level placement and move it automatically
    creds_file = data_dir / "credentials.json"
    old_creds = ROOT / "credentials.json"
    if not creds_file.exists() and old_creds.exists():
        import shutil
        shutil.move(str(old_creds), str(creds_file))
        print(f"  ✅ Moved credentials.json → data/credentials.json")
    if creds_file.exists():
        print("  ✅ Found credentials.json")
        run_now = input("  Run Google OAuth browser flow now? [Y/n]: ").strip().lower()
        if run_now != "n":
            # Save .env first so config loads correctly
            _write_env(values)
            _run_google_auth()
    else:
        print("  ⚠️  credentials.json not found – skipping Google setup.")
        print("  Run 'python scripts/google_auth.py' after placing credentials.json.")

    # ── 6. LinkedIn (optional) ─────────────────────────────────────────────
    _section("6. LinkedIn  (optional, scraping-based)")
    print("  ⚠️  LinkedIn automation may trigger security checks or require 2FA.")
    print("  Cookies are saved after first successful login to reduce prompts.")
    use_li = input("  Configure LinkedIn? [y/N]: ").strip().lower()
    if use_li == "y":
        values["LINKEDIN_EMAIL"] = _prompt(
            "  LINKEDIN_EMAIL", existing.get("LINKEDIN_EMAIL", "")
        )
        values["LINKEDIN_PASSWORD"] = _prompt(
            "  LINKEDIN_PASSWORD", existing.get("LINKEDIN_PASSWORD", ""), secret=True
        )
    else:
        print("  Skipping LinkedIn.")

    # ── Save ───────────────────────────────────────────────────────────────
    _section("Saving configuration")
    _write_env(values)

    # ── Next steps ─────────────────────────────────────────────────────────
    print(dedent(f"""
    ✅ Setup complete!

    ┌─ To run Dennis manually: ─────────────────────┐
    │  source .venv/bin/activate                     │
    │  python main.py                                │
    └────────────────────────────────────────────────┘

    ┌─ To install as a background service: ─────────┐
    │  bash scripts/install_service.sh               │
    └────────────────────────────────────────────────┘

    ┌─ If Google auth wasn't done yet: ─────────────┐
    │  python scripts/google_auth.py                 │
    └────────────────────────────────────────────────┘

    Then send a message to your Telegram bot to get started.
    """))


if __name__ == "__main__":
    main()
