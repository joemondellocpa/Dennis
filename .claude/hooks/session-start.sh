#!/bin/bash
# SessionStart hook for Dennis – installs Python dependencies for web sessions
set -euo pipefail

# Only run in remote (Claude Code on the web) environments
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

REPO_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
VENV="$REPO_DIR/.venv"

# Create virtual environment if it doesn't exist
if [ ! -d "$VENV" ]; then
  echo "Creating Python virtual environment..."
  python3 -m venv "$VENV"
fi

PIP="$VENV/bin/pip"

# Upgrade pip quietly
"$PIP" install --upgrade pip --quiet

# Install all requirements except playwright (too heavy for web sessions)
echo "Installing Python dependencies..."
"$PIP" install \
  openai \
  python-telegram-bot \
  apscheduler \
  python-dotenv \
  chromadb \
  "numpy<2" \
  beautifulsoup4 \
  google-api-python-client \
  google-auth-oauthlib \
  google-auth-httplib2 \
  PyGithub \
  pypdf \
  python-docx \
  fastapi \
  uvicorn \
  httpx \
  aiofiles \
  pydantic \
  rich \
  loguru \
  pytest \
  pytest-asyncio \
  flake8 \
  --quiet

# Persist venv activation for the session
echo "export PATH=\"$VENV/bin:\$PATH\"" >> "${CLAUDE_ENV_FILE:-/dev/null}"
echo "export VIRTUAL_ENV=\"$VENV\"" >> "${CLAUDE_ENV_FILE:-/dev/null}"

echo "Dependencies installed successfully."
