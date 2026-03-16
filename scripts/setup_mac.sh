#!/usr/bin/env bash
# ============================================================
# Dennis Agent – macOS setup (legacy entry point)
# This script now delegates to install.sh in the project root.
# ============================================================
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
exec bash "$SCRIPT_DIR/install.sh" "$@"
