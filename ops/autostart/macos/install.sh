#!/bin/bash
# macOS LaunchAgent installer for airis-mcp-gateway
# Supports both OrbStack and Docker Desktop

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PLIST_NAME="com.agiletec.airis-mcp-gateway.plist"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_DEST="$LAUNCH_AGENTS_DIR/$PLIST_NAME"

echo "=== AIRIS MCP Gateway Auto-Start Installer ==="
echo ""

# Detect docker compose path
detect_docker_compose() {
    # Check for OrbStack first (preferred on M-series Macs)
    if [ -f "$HOME/.orbstack/bin/docker" ]; then
        # OrbStack uses 'docker compose' (v2 syntax)
        echo "$HOME/.orbstack/bin/docker"
        return 0
    fi

    # Check Docker Desktop
    if command -v docker &> /dev/null; then
        DOCKER_PATH="$(command -v docker)"
        echo "$DOCKER_PATH"
        return 0
    fi

    # Check common Docker Desktop locations
    if [ -f "/usr/local/bin/docker" ]; then
        echo "/usr/local/bin/docker"
        return 0
    fi

    if [ -f "/opt/homebrew/bin/docker" ]; then
        echo "/opt/homebrew/bin/docker"
        return 0
    fi

    return 1
}

# Detect Docker runtime
detect_docker_runtime() {
    if [ -f "$HOME/.orbstack/bin/docker" ]; then
        echo "orbstack"
    elif docker info 2>/dev/null | grep -q "Docker Desktop"; then
        echo "docker-desktop"
    else
        echo "unknown"
    fi
}

echo "Detecting Docker installation..."
DOCKER_PATH=$(detect_docker_compose)
if [ -z "$DOCKER_PATH" ]; then
    echo "ERROR: Docker not found. Please install Docker Desktop or OrbStack."
    exit 1
fi

RUNTIME=$(detect_docker_runtime)
echo "  Docker path: $DOCKER_PATH"
echo "  Runtime: $RUNTIME"
echo "  Repository: $REPO_ROOT"
echo ""

# For docker compose v2, we need 'docker compose' not 'docker-compose'
DOCKER_COMPOSE_PATH="$DOCKER_PATH"

# Verify docker compose works
echo "Verifying docker compose..."
if ! "$DOCKER_COMPOSE_PATH" compose version &> /dev/null; then
    echo "ERROR: 'docker compose' command not working"
    echo "Please ensure Docker Compose v2 is installed"
    exit 1
fi
echo "  docker compose v2: OK"
echo ""

# Create LaunchAgents directory if needed
mkdir -p "$LAUNCH_AGENTS_DIR"

# Unload existing if present
if launchctl list 2>/dev/null | grep -q "com.agiletec.airis-mcp-gateway"; then
    echo "Unloading existing LaunchAgent..."
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
fi

# Generate plist from template
echo "Generating LaunchAgent plist..."
TEMPLATE="$SCRIPT_DIR/$PLIST_NAME.tmpl"
if [ ! -f "$TEMPLATE" ]; then
    echo "ERROR: Template not found: $TEMPLATE"
    exit 1
fi

# Replace placeholders
sed -e "s|{{DOCKER_COMPOSE_PATH}}|$DOCKER_COMPOSE_PATH|g" \
    -e "s|{{REPO_ROOT}}|$REPO_ROOT|g" \
    -e "s|{{HOME}}|$HOME|g" \
    "$TEMPLATE" > "$PLIST_DEST"

# Since we need 'docker compose' (two args), update plist for compose subcommand
# The template uses docker, we need to insert 'compose' as second argument
# Rewrite with proper arguments for docker compose v2
cat > "$PLIST_DEST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.agiletec.airis-mcp-gateway</string>

    <key>ProgramArguments</key>
    <array>
        <string>$DOCKER_COMPOSE_PATH</string>
        <string>compose</string>
        <string>-f</string>
        <string>$REPO_ROOT/compose.yaml</string>
        <string>up</string>
        <string>-d</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$REPO_ROOT</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <false/>

    <key>StandardOutPath</key>
    <string>$HOME/Library/Logs/airis-mcp-gateway.log</string>

    <key>StandardErrorPath</key>
    <string>$HOME/Library/Logs/airis-mcp-gateway.error.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin:$HOME/.orbstack/bin</string>
    </dict>
</dict>
</plist>
EOF

echo "  Created: $PLIST_DEST"

# Load the LaunchAgent
echo "Loading LaunchAgent..."
launchctl load "$PLIST_DEST"

# Verify
if launchctl list 2>/dev/null | grep -q "com.agiletec.airis-mcp-gateway"; then
    echo ""
    echo "=== Installation Complete ==="
    echo ""
    echo "The AIRIS MCP Gateway will now start automatically when you log in."
    echo ""
    echo "Useful commands:"
    echo "  task autostart:status    - Check status"
    echo "  task autostart:uninstall - Remove auto-start"
    echo ""
    echo "Log files:"
    echo "  $HOME/Library/Logs/airis-mcp-gateway.log"
    echo "  $HOME/Library/Logs/airis-mcp-gateway.error.log"
else
    echo ""
    echo "WARNING: LaunchAgent may not have loaded correctly."
    echo "Check with: launchctl list | grep airis"
fi
