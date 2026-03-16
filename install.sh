#!/usr/bin/env bash
# =============================================================================
# Dennis – One-Command Installer
#
# Supports:  macOS 13+ (Apple Silicon & Intel)
#            Raspberry Pi OS / Ubuntu / Debian (arm64 & x86_64)
#
# Usage:
#   bash install.sh                   # Full install (recommended)
#   bash install.sh --lightweight     # Raspberry Pi / low-RAM: skips Playwright
#   bash install.sh --skip-ollama     # Skip local LLM installation
#   bash install.sh --skip-wizard     # Skip credentials wizard (re-run later)
#
# Re-running this script is safe – all steps are idempotent.
# =============================================================================
set -euo pipefail

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

ok()   { echo -e "${GREEN}  ✅  $*${NC}"; }
warn() { echo -e "${YELLOW}  ⚠️   $*${NC}"; }
err()  { echo -e "${RED}  ❌  $*${NC}" >&2; exit 1; }
info() { echo -e "${BLUE}  ℹ   $*${NC}"; }
step() { echo -e "\n${BOLD}┌─ $* ─────────────────────────────────────────────┐${NC}"; }

# ── Parse arguments ───────────────────────────────────────────────────────────
LIGHTWEIGHT=false
SKIP_OLLAMA=false
SKIP_WIZARD=false

for arg in "$@"; do
  case "$arg" in
    --lightweight)  LIGHTWEIGHT=true ;;
    --skip-ollama)  SKIP_OLLAMA=true ;;
    --skip-wizard)  SKIP_WIZARD=true ;;
    --help|-h)
      echo "Usage: bash install.sh [--lightweight] [--skip-ollama] [--skip-wizard]"
      exit 0 ;;
    *) warn "Unknown flag: $arg (ignored)" ;;
  esac
done

# ── Detect OS and architecture ────────────────────────────────────────────────
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
  Darwin) PLATFORM="macos" ;;
  Linux)  PLATFORM="linux" ;;
  *)      err "Unsupported platform: $OS. Dennis runs on macOS or Linux." ;;
esac

# Detect Raspberry Pi
IS_PI=false
if [[ "$PLATFORM" == "linux" ]] && grep -qi "raspberry" /proc/cpuinfo 2>/dev/null; then
  IS_PI=true
  LIGHTWEIGHT=true  # Force lightweight on Pi
fi

# ── Detect available RAM (MB) ─────────────────────────────────────────────────
RAM_MB=0
if [[ "$PLATFORM" == "macos" ]]; then
  RAM_MB=$(( $(sysctl -n hw.memsize) / 1024 / 1024 ))
elif [[ -f /proc/meminfo ]]; then
  RAM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
fi

# Recommend Ollama model based on RAM
if   (( RAM_MB >= 14000 )); then RECOMMENDED_MODEL="deepseek-r1:8b"
elif (( RAM_MB >= 6000  )); then RECOMMENDED_MODEL="llama3.2:3b"
else                              RECOMMENDED_MODEL="llama3.2:1b"
fi

AGENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$AGENT_DIR/.venv"

# ── Banner ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║         Dennis AI Assistant – Installer              ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
info "Platform : $OS / $ARCH$(${IS_PI} && echo ' (Raspberry Pi)' || true)"
info "RAM      : ${RAM_MB} MB"
info "Mode     : $(${LIGHTWEIGHT} && echo 'lightweight (no Playwright)' || echo 'full')"
info "Directory: $AGENT_DIR"
echo ""

# ═════════════════════════════════════════════════════════════════════════════
# Step 1 – System dependencies
# ═════════════════════════════════════════════════════════════════════════════
step "1. System dependencies"

if [[ "$PLATFORM" == "macos" ]]; then
  # ── Homebrew ──────────────────────────────────────────────────────────────
  if ! command -v brew &>/dev/null; then
    info "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add Homebrew to PATH for Apple Silicon
    if [[ "$ARCH" == "arm64" ]]; then
      eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
  fi
  ok "Homebrew $(brew --version | head -1)"

  # ── Python ────────────────────────────────────────────────────────────────
  PYTHON=""
  for py in python3.12 python3.11; do
    if command -v "$py" &>/dev/null; then PYTHON="$(command -v "$py")"; break; fi
  done
  if [[ -z "$PYTHON" ]]; then
    info "Installing Python 3.11 via Homebrew..."
    brew install python@3.11
    PYTHON="$(command -v python3.11)"
  fi

elif [[ "$PLATFORM" == "linux" ]]; then
  # ── apt packages ──────────────────────────────────────────────────────────
  if command -v apt-get &>/dev/null; then
    info "Updating package list..."
    sudo apt-get update -qq

    APT_PKGS=(python3 python3-venv python3-pip ffmpeg git curl)
    if ${LIGHTWEIGHT}; then
      info "Lightweight mode: skipping Chromium system package"
    fi

    info "Installing system packages: ${APT_PKGS[*]}"
    sudo apt-get install -y "${APT_PKGS[@]}"
  fi

  PYTHON=""
  for py in python3.12 python3.11 python3; do
    if command -v "$py" &>/dev/null; then PYTHON="$(command -v "$py")"; break; fi
  done
fi

[[ -z "${PYTHON:-}" ]] && err "Python 3.11+ not found. Install it and re-run."
PY_VER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
ok "Python $PY_VER → $PYTHON"

# Version guard
PY_MAJOR=$("$PYTHON" -c "import sys; print(sys.version_info.major)")
PY_MINOR=$("$PYTHON" -c "import sys; print(sys.version_info.minor)")
if (( PY_MAJOR < 3 || (PY_MAJOR == 3 && PY_MINOR < 11) )); then
  err "Python 3.11+ is required. Found $PY_VER."
fi

# ═════════════════════════════════════════════════════════════════════════════
# Step 2 – Python virtual environment
# ═════════════════════════════════════════════════════════════════════════════
step "2. Python virtual environment"
cd "$AGENT_DIR"

if [[ ! -d "$VENV" ]]; then
  info "Creating .venv..."
  "$PYTHON" -m venv "$VENV"
fi
PY="$VENV/bin/python"
PIP="$VENV/bin/pip"
ok "Virtual environment ready: $VENV"

# ═════════════════════════════════════════════════════════════════════════════
# Step 3 – Python packages
# ═════════════════════════════════════════════════════════════════════════════
step "3. Python packages"
info "Upgrading pip..."
"$PIP" install --upgrade pip --quiet

info "Installing requirements (this may take 1–3 minutes)..."
"$PIP" install -r requirements.txt --quiet
ok "Python packages installed"

# ═════════════════════════════════════════════════════════════════════════════
# Step 4 – Playwright browser (skip in lightweight mode)
# ═════════════════════════════════════════════════════════════════════════════
step "4. Playwright browser"
if ${LIGHTWEIGHT}; then
  info "Lightweight mode – skipping Playwright (using httpx+BeautifulSoup4 instead)"
  # Write LIGHTWEIGHT_MODE=true to .env.defaults if not already set
  ENV_FILE="$AGENT_DIR/.env"
  if [[ -f "$ENV_FILE" ]] && grep -q "^LIGHTWEIGHT_MODE=" "$ENV_FILE"; then
    true  # Already set by user
  else
    info "Setting LIGHTWEIGHT_MODE=true in .env"
    echo "LIGHTWEIGHT_MODE=true" >> "$ENV_FILE"
  fi
else
  if "$VENV/bin/playwright" install chromium --with-deps 2>/dev/null; then
    ok "Playwright Chromium installed"
  else
    warn "Playwright install failed – web browsing will be limited."
    info "Fix manually: source .venv/bin/activate && playwright install chromium"
  fi
fi

# ═════════════════════════════════════════════════════════════════════════════
# Step 5 – Ollama (local LLM)
# ═════════════════════════════════════════════════════════════════════════════
step "5. Ollama (local LLM – reduces DeepSeek API costs)"

if ${SKIP_OLLAMA}; then
  info "Skipping Ollama (--skip-ollama flag set)"
else
  echo ""
  echo -e "  Ollama runs ${BOLD}DeepSeek R1 / Llama${NC} locally to handle cheap tasks:"
  echo "    • Goal completion evaluation"
  echo "    • Memory pruning summaries"
  echo "    • Notification worthiness scoring"
  echo ""
  echo "  Based on your RAM (${RAM_MB} MB), recommended model: ${BOLD}${RECOMMENDED_MODEL}${NC}"
  echo ""
  read -r -p "  Install Ollama and pull ${RECOMMENDED_MODEL}? [Y/n]: " ans_ollama
  ans_ollama="${ans_ollama:-Y}"

  if [[ "$(echo "$ans_ollama" | tr '[:upper:]' '[:lower:]')" != "n" ]]; then
    # ── Install Ollama ───────────────────────────────────────────────────────
    if ! command -v ollama &>/dev/null; then
      if [[ "$PLATFORM" == "macos" ]]; then
        if command -v brew &>/dev/null; then
          info "Installing Ollama via Homebrew..."
          brew install ollama
        else
          info "Downloading Ollama installer..."
          OLLAMA_PKG="/tmp/Ollama-darwin.pkg"
          if [[ "$ARCH" == "arm64" ]]; then
            curl -fsSL "https://ollama.com/download/Ollama-darwin.zip" -o /tmp/Ollama-darwin.zip
            unzip -qo /tmp/Ollama-darwin.zip -d /tmp/OllamaApp
            # Copy app if not already there
            if [[ ! -d "/Applications/Ollama.app" ]]; then
              cp -r "/tmp/OllamaApp/Ollama.app" /Applications/
            fi
            ok "Ollama.app installed to /Applications"
          else
            curl -fsSL "https://ollama.com/download/Ollama-darwin.zip" -o /tmp/Ollama-darwin.zip
            unzip -qo /tmp/Ollama-darwin.zip -d /tmp/OllamaApp
            if [[ ! -d "/Applications/Ollama.app" ]]; then
              cp -r "/tmp/OllamaApp/Ollama.app" /Applications/
            fi
            ok "Ollama.app installed to /Applications"
          fi
        fi
      elif [[ "$PLATFORM" == "linux" ]]; then
        info "Installing Ollama via official install script..."
        curl -fsSL https://ollama.com/install.sh | sh
      fi
    fi

    if command -v ollama &>/dev/null; then
      ok "Ollama $(ollama --version 2>/dev/null || echo 'installed')"
    elif [[ -d "/Applications/Ollama.app" ]]; then
      ok "Ollama.app installed (open it to start the server)"
    else
      warn "Ollama command not found after install. You may need to restart your shell."
    fi

    # ── Start ollama serve (background, if not already running) ──────────────
    OLLAMA_RUNNING=false
    if curl -s --max-time 2 http://localhost:11434/api/tags &>/dev/null; then
      OLLAMA_RUNNING=true
    elif command -v ollama &>/dev/null; then
      info "Starting ollama serve in background..."
      nohup ollama serve > "$AGENT_DIR/data/logs/ollama.log" 2>&1 &
      OLLAMA_PID=$!
      # Wait up to 10s for it to start
      for i in {1..10}; do
        if curl -s --max-time 1 http://localhost:11434/api/tags &>/dev/null; then
          OLLAMA_RUNNING=true; break
        fi
        sleep 1
      done
      if ${OLLAMA_RUNNING}; then
        ok "Ollama server started (PID $OLLAMA_PID)"
      else
        warn "Ollama server didn't respond within 10s. Pull the model manually later:"
        warn "  ollama pull ${RECOMMENDED_MODEL}"
      fi
    fi

    # ── Pull the model ───────────────────────────────────────────────────────
    if ${OLLAMA_RUNNING} && command -v ollama &>/dev/null; then
      # Check if model is already pulled
      if ollama list 2>/dev/null | grep -q "${RECOMMENDED_MODEL%%:*}"; then
        ok "Model ${RECOMMENDED_MODEL} already available"
      else
        echo ""
        info "Pulling ${RECOMMENDED_MODEL} (this downloads ~5–9 GB, may take several minutes)..."
        info "Progress will be shown below:"
        echo ""
        if ollama pull "${RECOMMENDED_MODEL}"; then
          ok "Model ${RECOMMENDED_MODEL} ready"
        else
          warn "Model pull failed. Pull it manually: ollama pull ${RECOMMENDED_MODEL}"
        fi
      fi
    fi

    # ── Write Ollama settings to .env placeholder ────────────────────────────
    # first_run.py will ask the user to confirm, but we pre-fill good defaults
    ENV_FILE="$AGENT_DIR/.env"
    if [[ ! -f "$ENV_FILE" ]] || ! grep -q "^OLLAMA_ENABLED=" "$ENV_FILE" 2>/dev/null; then
      {
        echo "OLLAMA_ENABLED=true"
        echo "LOCAL_MODEL_URL=http://localhost:11434"
        echo "LOCAL_MODEL=${RECOMMENDED_MODEL}"
      } >> "$ENV_FILE"
      info "Pre-filled Ollama settings in .env (wizard will confirm them)"
    fi

  else
    info "Skipping Ollama. All inference will use the remote DeepSeek API."
  fi
fi

# ═════════════════════════════════════════════════════════════════════════════
# Step 6 – Data directory
# ═════════════════════════════════════════════════════════════════════════════
step "6. Data directory"
mkdir -p "$AGENT_DIR/data/logs"
ok "data/ directory ready"

# ═════════════════════════════════════════════════════════════════════════════
# Step 7 – Credentials wizard
# ═════════════════════════════════════════════════════════════════════════════
step "7. Credentials & configuration"

if ${SKIP_WIZARD}; then
  info "Skipping wizard (--skip-wizard flag set)."
  info "Run it later with:  source .venv/bin/activate && python scripts/first_run.py"
else
  echo ""
  echo "  The wizard will ask for:"
  echo "    • DeepSeek API key  (required)"
  echo "    • Telegram bot token  (required)"
  echo "    • GitHub, Google, LinkedIn credentials  (optional)"
  echo ""
  echo "  Press Ctrl-C at any point to stop and resume later."
  echo ""
  "$PY" scripts/first_run.py
fi

# ═════════════════════════════════════════════════════════════════════════════
# Done
# ═════════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║              ✅  Installation complete!              ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  ┌─ Run Dennis manually ──────────────────────────────────┐"
echo "  │  source .venv/bin/activate                             │"
echo "  │  python main.py                                        │"
echo "  └────────────────────────────────────────────────────────┘"
echo ""
echo "  ┌─ Install as background service (auto-start on login) ──┐"
echo "  │  bash scripts/install_service.sh                       │"
echo "  └────────────────────────────────────────────────────────┘"
echo ""
echo "  ┌─ Re-run credentials wizard ────────────────────────────┐"
echo "  │  source .venv/bin/activate                             │"
echo "  │  python scripts/first_run.py                           │"
echo "  └────────────────────────────────────────────────────────┘"
echo ""
if command -v ollama &>/dev/null || [[ -d "/Applications/Ollama.app" ]]; then
echo "  ┌─ Ollama model management ──────────────────────────────┐"
echo "  │  ollama list                        # see pulled models │"
echo "  │  ollama pull deepseek-r1:8b         # pull/update model │"
echo "  │  ollama serve                       # start server      │"
echo "  └────────────────────────────────────────────────────────┘"
echo ""
fi
echo "  Then message your Telegram bot to get started!"
echo ""
