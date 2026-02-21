#!/bin/bash
# Linux systemd service installer for airis-mcp-gateway

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SERVICE_NAME="airis-mcp-gateway.service"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
SERVICE_DEST="$SYSTEMD_USER_DIR/$SERVICE_NAME"

echo "=== AIRIS MCP Gateway Auto-Start Installer (Linux) ==="
echo ""

# Check for Docker
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker not found. Please install Docker."
    exit 1
fi

# Verify docker compose works
echo "Verifying docker compose..."
if ! docker compose version &> /dev/null; then
    echo "ERROR: 'docker compose' command not working"
    echo "Please ensure Docker Compose v2 is installed"
    exit 1
fi
echo "  docker compose v2: OK"
echo ""

# Create systemd user directory
mkdir -p "$SYSTEMD_USER_DIR"

# Stop existing if running
if systemctl --user is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    echo "Stopping existing service..."
    systemctl --user stop "$SERVICE_NAME"
fi

# Disable existing if enabled
if systemctl --user is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
    echo "Disabling existing service..."
    systemctl --user disable "$SERVICE_NAME"
fi

# Find docker compose path
DOCKER_COMPOSE_PATH="$(command -v docker)"

# Generate service file from template
echo "Generating systemd service file..."
TEMPLATE="$SCRIPT_DIR/$SERVICE_NAME.tmpl"
if [ ! -f "$TEMPLATE" ]; then
    echo "ERROR: Template not found: $TEMPLATE"
    exit 1
fi

# Detect architecture for ARM emulation
ARM_EMU_FLAG=""
if [ "$(uname -m)" = "x86_64" ] || [ "$(uname -m)" = "amd64" ]; then
  ARM_EMU_FLAG=" -f $REPO_ROOT/docker-compose.arm-emu.yml"
  echo "  Architecture: x86_64 (ARM emulation enabled)"
else
  echo "  Architecture: $(uname -m) (native)"
fi

sed -e "s|{{REPO_ROOT}}|$REPO_ROOT|g" \
    -e "s|{{USER}}|$USER|g" \
    -e "s|{{ARM_EMU_FLAG}}|$ARM_EMU_FLAG|g" \
    "$TEMPLATE" > "$SERVICE_DEST"

echo "  Created: $SERVICE_DEST"

# Reload systemd
echo "Reloading systemd..."
systemctl --user daemon-reload

# Enable and start service
echo "Enabling service..."
systemctl --user enable "$SERVICE_NAME"

echo "Starting service..."
systemctl --user start "$SERVICE_NAME"

# Enable lingering (allows user services to run without active session)
echo "Enabling user lingering..."
loginctl enable-linger "$USER" 2>/dev/null || true

# Verify
if systemctl --user is-active --quiet "$SERVICE_NAME"; then
    echo ""
    echo "=== Installation Complete ==="
    echo ""
    echo "The AIRIS MCP Gateway will now start automatically on boot."
    echo ""
    echo "Useful commands:"
    echo "  task autostart:status    - Check status"
    echo "  task autostart:uninstall - Remove auto-start"
    echo "  systemctl --user status $SERVICE_NAME"
    echo "  journalctl --user -u $SERVICE_NAME"
else
    echo ""
    echo "WARNING: Service may not have started correctly."
    echo "Check with: systemctl --user status $SERVICE_NAME"
fi
