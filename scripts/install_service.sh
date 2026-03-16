#!/bin/bash
# ============================================================
# Install Dennis as a persistent macOS LaunchAgent
# (auto-starts on login, restarts on crash)
# Run: bash scripts/install_service.sh
# ============================================================
set -e

AGENT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$AGENT_DIR/.venv/bin/python"
PLIST_LABEL="com.dennis.agent"
PLIST_FILE="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"

if [ ! -f "$PYTHON" ]; then
  echo "❌ Virtual environment not found. Run setup_mac.sh first."
  exit 1
fi

if [ ! -f "$AGENT_DIR/.env" ]; then
  echo "❌ .env not found. Copy .env.example to .env and fill in credentials."
  exit 1
fi

echo "Installing LaunchAgent: $PLIST_LABEL"

cat > "$PLIST_FILE" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
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
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
    </dict>

    <!-- Auto-restart on crash -->
    <key>KeepAlive</key>
    <true/>

    <!-- Start on login -->
    <key>RunAtLoad</key>
    <true/>

    <!-- Log files -->
    <key>StandardOutPath</key>
    <string>$AGENT_DIR/data/logs/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$AGENT_DIR/data/logs/stderr.log</string>

    <!-- Throttle restarts (seconds) -->
    <key>ThrottleInterval</key>
    <integer>10</integer>
</dict>
</plist>
EOF

# Load the service
launchctl unload "$PLIST_FILE" 2>/dev/null || true
launchctl load -w "$PLIST_FILE"

echo ""
echo "✅ Dennis LaunchAgent installed and started!"
echo ""
echo "Useful commands:"
echo "  launchctl stop  $PLIST_LABEL   # Stop Dennis"
echo "  launchctl start $PLIST_LABEL   # Start Dennis"
echo "  launchctl unload ~/Library/LaunchAgents/$PLIST_LABEL.plist  # Uninstall"
echo "  tail -f $AGENT_DIR/data/logs/dennis.log  # View logs"
