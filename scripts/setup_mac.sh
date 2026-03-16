#!/bin/bash
# ============================================================
# Dennis Agent – Mac mini setup script (macOS Monterey+)
# Run once: bash scripts/setup_mac.sh
# ============================================================
set -e

AGENT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
echo "Setting up Dennis in: $AGENT_DIR"

# ── 1. Homebrew ────────────────────────────────────────────────────────────
if ! command -v brew &>/dev/null; then
  echo "Installing Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# ── 2. Python 3.11+ ────────────────────────────────────────────────────────
if ! command -v python3.11 &>/dev/null && ! command -v python3.12 &>/dev/null; then
  echo "Installing Python 3.11..."
  brew install python@3.11
fi

PYTHON=$(command -v python3.12 || command -v python3.11 || command -v python3)
echo "Using Python: $PYTHON ($($PYTHON --version))"

# ── 3. Virtual environment ─────────────────────────────────────────────────
cd "$AGENT_DIR"
if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  $PYTHON -m venv .venv
fi
source .venv/bin/activate

# ── 4. Python dependencies ─────────────────────────────────────────────────
echo "Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# ── 5. Playwright browsers ─────────────────────────────────────────────────
echo "Installing Playwright Chromium browser..."
playwright install chromium

# ── 6. Create data directory ───────────────────────────────────────────────
mkdir -p data/logs

# ── 7. First-run setup wizard ──────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Running first-run setup wizard..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
python scripts/first_run.py

echo ""
echo "✅ Setup complete!"
echo ""
echo "To install Dennis as a background service (auto-start on login):"
echo "  bash scripts/install_service.sh"
echo ""
echo "To run Dennis manually:"
echo "  source .venv/bin/activate && python main.py"
