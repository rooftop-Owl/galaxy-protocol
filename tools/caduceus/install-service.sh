#!/usr/bin/env bash
# Caduceus Gateway — Service Installation Script
#
# Usage: sudo ./install-service.sh [--project-root /path/to/project]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Default: 4 levels up from tools/caduceus/install-service.sh
DEFAULT_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
PROJECT_ROOT="${1:-$DEFAULT_ROOT}"

SERVICE_NAME="caduceus-gateway"
SERVICE_SRC="$SCRIPT_DIR/../../services/caduceus-gateway.service"
SERVICE_DST="/etc/systemd/system/${SERVICE_NAME}.service"

echo "🏥 Caduceus Gateway — Service Installer"
echo ""
echo "  Project root: $PROJECT_ROOT"
echo "  Service file: $SERVICE_SRC"
echo "  Install to:   $SERVICE_DST"
echo ""

# Validate
if [ ! -f "$SERVICE_SRC" ]; then
    echo "❌ Service file not found: $SERVICE_SRC"
    exit 1
fi

if [ ! -f "$PROJECT_ROOT/galaxy-protocol/tools/caduceus/gateway.py" ]; then
    echo "❌ gateway.py not found in $PROJECT_ROOT/galaxy-protocol/tools/caduceus/"
    echo "   Is PROJECT_ROOT correct?"
    exit 1
fi

# Check root
if [ "$EUID" -ne 0 ]; then
    echo "❌ This script requires root. Run with: sudo $0"
    exit 1
fi

OPENCODE_BIN="${GALAXY_OPENCODE_BIN:-}"
if [ -z "$OPENCODE_BIN" ]; then
    OPENCODE_BIN="$(command -v opencode 2>/dev/null || true)"
fi
if [ -z "$OPENCODE_BIN" ] && [ -n "${SUDO_USER:-}" ]; then
    USER_CANDIDATE="/home/${SUDO_USER}/.opencode/bin/opencode"
    if [ -x "$USER_CANDIDATE" ]; then
        OPENCODE_BIN="$USER_CANDIDATE"
    fi
fi

if [ -n "$OPENCODE_BIN" ]; then
    echo "✅ OpenCode binary detected: $OPENCODE_BIN"
else
    echo "⚠️  Could not detect OpenCode binary."
    echo "   Service will use PATH lookup; set GALAXY_OPENCODE_BIN later if needed."
fi

# Substitute paths
sed \
  -e "s|WorkingDirectory=.*|WorkingDirectory=$PROJECT_ROOT|g" \
  -e "s|^Environment=GALAXY_OPENCODE_BIN=.*|Environment=GALAXY_OPENCODE_BIN=$OPENCODE_BIN|g" \
  "$SERVICE_SRC" > "$SERVICE_DST"

echo "✅ Service file installed to $SERVICE_DST"

# Reload systemd
systemctl daemon-reload
echo "✅ systemd daemon reloaded"

echo ""
echo "Next steps:"
echo "  sudo systemctl enable ${SERVICE_NAME}    # Enable on boot"
echo "  sudo systemctl start ${SERVICE_NAME}     # Start now"
echo "  sudo systemctl status ${SERVICE_NAME}    # Check status"
echo "  journalctl -u ${SERVICE_NAME} -f         # Follow logs"
