#!/usr/bin/env bash
# =============================================================================
# Dennis – macOS LaunchAgent installer / uninstaller
#
# Installs Dennis as a persistent background service that:
#   • Starts automatically at login
#   • Restarts automatically on crash
#   • Logs stdout/stderr to data/logs/
#
# Usage:
#   bash scripts/install_service.sh            # Install / reinstall
#   bash scripts/install_service.sh --remove   # Uninstall
# =============================================================================
set -euo pipefail

AGENT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$AGENT_DIR/.venv/bin/python"
PLIST_LABEL="com.dennis.agent"
PLIST_FILE="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"
LOG_DIR="$AGENT_DIR/data/logs"

# ── Colour helpers ────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'
ok()   { echo -e "${GREEN}  ✅  $*${NC}"; }
warn() { echo -e "${YELLOW}  ⚠️   $*${NC}"; }
err()  { echo -e "${RED}  ❌  $*${NC}" >&2; exit 1; }
info() { echo "       $*"; }

# ── Uninstall path ────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--remove" ]]; then
  echo ""
  echo -e "${BOLD}Removing Dennis LaunchAgent...${NC}"
  if [[ -f "$PLIST_FILE" ]]; then
    launchctl unload "$PLIST_FILE" 2>/dev/null || true
    rm "$PLIST_FILE"
    ok "LaunchAgent removed. Dennis will no longer start at login."
  else
    warn "No LaunchAgent found at $PLIST_FILE – nothing to remove."
  fi
  exit 0
fi

# ── Pre-flight checks ─────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║       Dennis – Background Service Installer          ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${NC}"
echo ""

[[ "$(uname)" == "Darwin" ]] || err "LaunchAgent installation is macOS-only. On Linux, use systemd (see docs)."
[[ -f "$PYTHON" ]]            || err "Virtual environment not found. Run  bash install.sh  first."
[[ -f "$AGENT_DIR/.env" ]]    || err ".env not found. Run  bash install.sh  first."

mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$LOG_DIR"

# ── Write the plist ───────────────────────────────────────────────────────────
cat > "$PLIST_FILE" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_LABEL</string>

    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>$AGENT_DIR/main.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$AGENT_DIR</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>

    <!-- Auto-restart on crash -->
    <key>KeepAlive</key>
    <true/>

    <!-- Start at login -->
    <key>RunAtLoad</key>
    <true/>

    <!-- Throttle restart loops (10 seconds between restarts) -->
    <key>ThrottleInterval</key>
    <integer>10</integer>

    <!-- Redirect logs -->
    <key>StandardOutPath</key>
    <string>$LOG_DIR/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/stderr.log</string>
</dict>
</plist>
PLIST

info "Plist written: $PLIST_FILE"

# ── Load / reload the service ─────────────────────────────────────────────────
launchctl unload "$PLIST_FILE" 2>/dev/null || true
launchctl load -w "$PLIST_FILE"

# Give it a moment to start
sleep 2

if launchctl list | grep -q "$PLIST_LABEL"; then
  ok "Dennis is running as a background service!"
else
  warn "Service loaded but not yet listed – it may start momentarily."
  info "Check with: launchctl list | grep dennis"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "  ┌─ Service management commands ─────────────────────────┐"
echo "  │  launchctl stop  $PLIST_LABEL     │"
echo "  │  launchctl start $PLIST_LABEL     │"
echo "  └────────────────────────────────────────────────────────┘"
echo ""
echo "  ┌─ View logs ────────────────────────────────────────────┐"
echo "  │  tail -f $LOG_DIR/stdout.log   │"
echo "  │  tail -f $LOG_DIR/stderr.log   │"
echo "  └────────────────────────────────────────────────────────┘"
echo ""
echo "  ┌─ Uninstall ────────────────────────────────────────────┐"
echo "  │  bash scripts/install_service.sh --remove              │"
echo "  └────────────────────────────────────────────────────────┘"
echo ""
