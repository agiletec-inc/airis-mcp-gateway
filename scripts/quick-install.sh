#!/usr/bin/env bash
set -euo pipefail

# AIRIS MCP Gateway - Quick Install Script
# Usage:
#   Install:   curl -fsSL https://raw.githubusercontent.com/agiletec-inc/airis-mcp-gateway/main/scripts/quick-install.sh | bash
#   Uninstall: ~/.local/share/airis-mcp-gateway/scripts/quick-install.sh --uninstall

REPO="https://github.com/agiletec-inc/airis-mcp-gateway"
DIR="${AIRIS_MCP_DIR:-$HOME/.local/share/airis-mcp-gateway}"
CONFIG_DIR="${AIRIS_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/airis-mcp-gateway}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()  { echo -e "${BLUE}[STEP]${NC} $1"; }

check_dependencies() {
    local missing=()
    command -v docker >/dev/null 2>&1 || missing+=("docker")
    command -v git >/dev/null 2>&1 || missing+=("git")
    command -v curl >/dev/null 2>&1 || missing+=("curl")

    if [ ${#missing[@]} -ne 0 ]; then
        log_error "Missing dependencies: ${missing[*]}"
        echo ""
        echo "Please install:"
        echo "  - Docker: https://docs.docker.com/get-docker/"
        echo "  - Git: https://git-scm.com/downloads"
        exit 1
    fi

    if ! docker info >/dev/null 2>&1; then
        log_error "Docker is not running. Please start Docker Desktop or OrbStack."
        exit 1
    fi
}

install() {
    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║     AIRIS MCP Gateway - Quick Install    ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
    echo ""

    check_dependencies

    # Step 1: Clone or update repository
    log_step "1/4 Fetching repository..."
    mkdir -p "$DIR"
    if [ -d "$DIR/.git" ]; then
        log_info "Updating existing installation..."
        git -C "$DIR" fetch --tags -q 2>/dev/null || true
        local latest_tag=$(git -C "$DIR" describe --tags --abbrev=0 2>/dev/null || echo "main")
        git -C "$DIR" checkout -q "$latest_tag" 2>/dev/null || true
        git -C "$DIR" pull -q 2>/dev/null || true
    else
        log_info "Cloning repository..."
        git clone -q "$REPO" "$DIR"
        local latest_tag=$(git -C "$DIR" describe --tags --abbrev=0 2>/dev/null || echo "main")
        git -C "$DIR" checkout -q "$latest_tag" 2>/dev/null || true
    fi

    # Step 2: Setup config directory
    log_step "2/4 Setting up configuration..."
    mkdir -p "$CONFIG_DIR"
    if [ ! -f "$CONFIG_DIR/mcp-config.json" ]; then
        if [ -f "$DIR/config/profiles/recommended.json" ]; then
            cp "$DIR/config/profiles/recommended.json" "$CONFIG_DIR/mcp-config.json"
            log_info "Created config from recommended profile"
        elif [ -f "$DIR/mcp-config.json" ]; then
            cp "$DIR/mcp-config.json" "$CONFIG_DIR/mcp-config.json"
            log_info "Created config from default template"
        fi
    else
        log_info "Config already exists at $CONFIG_DIR/mcp-config.json"
    fi

    # Step 3: Setup .env if needed
    if [ ! -f "$DIR/.env" ]; then
        cp "$DIR/.env.example" "$DIR/.env"
        log_info "Created .env from example"
    fi

    # Step 4: Start services
    log_step "3/4 Starting services..."
    cd "$DIR"
    export AIRIS_CONFIG_DIR="$CONFIG_DIR"
    docker compose pull -q 2>/dev/null || true
    docker compose up -d

    # Step 5: Health check
    log_step "4/4 Verifying installation..."
    sleep 3

    local api_ok=false
    local gateway_ok=false

    for i in {1..10}; do
        if curl -fsS http://localhost:9400/health >/dev/null 2>&1; then
            api_ok=true
            break
        fi
        sleep 2
    done

    for i in {1..10}; do
        if curl -fsS http://localhost:9390/health >/dev/null 2>&1; then
            gateway_ok=true
            break
        fi
        sleep 2
    done

    # Step 5: Install airis-workspace (optional) - direct binary download, no Homebrew needed
    local workspace_installed=false
    if [ "${INSTALL_WORKSPACE:-true}" = "true" ]; then
        log_step "5/6 Installing airis-workspace..."
        if command -v airis >/dev/null 2>&1; then
            workspace_installed=true
            log_info "airis-workspace already installed"
        else
            # Detect OS and architecture
            local os=$(uname -s | tr '[:upper:]' '[:lower:]')
            local arch=$(uname -m)
            local target=""

            case "$os-$arch" in
                darwin-arm64)  target="aarch64-apple-darwin" ;;
                darwin-x86_64) target="x86_64-apple-darwin" ;;
                linux-x86_64)  target="x86_64-unknown-linux-gnu" ;;
                linux-aarch64) target="aarch64-unknown-linux-gnu" ;;
                *) log_warn "Unsupported platform: $os-$arch"; target="" ;;
            esac

            if [ -n "$target" ]; then
                log_info "Downloading latest airis-workspace for $target..."

                # Get latest release version from GitHub API
                local latest=$(curl -fsSL https://api.github.com/repos/agiletec-inc/airis-workspace/releases/latest | grep '"tag_name"' | sed -E 's/.*"v([^"]+)".*/\1/')

                if [ -n "$latest" ]; then
                    local url="https://github.com/agiletec-inc/airis-workspace/releases/download/v${latest}/airis-${latest}-${target}.tar.gz"
                    local install_dir="${HOME}/.local/bin"
                    mkdir -p "$install_dir"

                    if curl -fsSL "$url" | tar -xz -C "$install_dir" 2>/dev/null; then
                        chmod +x "$install_dir/airis"
                        workspace_installed=true
                        log_info "airis-workspace v$latest installed to $install_dir/airis"

                        # Add to PATH hint if not already there
                        if [[ ":$PATH:" != *":$install_dir:"* ]]; then
                            log_warn "Add to PATH: export PATH=\"$install_dir:\$PATH\""
                        fi
                    else
                        log_warn "Failed to download airis-workspace (optional)"
                    fi
                else
                    log_warn "Could not determine latest version"
                fi
            fi
        fi
    fi

    # Step 6: Register with Claude Code globally (if available)
    local claude_registered=false
    if command -v claude >/dev/null 2>&1; then
        log_step "6/6 Registering with Claude Code (global)..."

        # Clean up ALL project-level MCP configs (gateway should be global only)
        if [ -f "$HOME/.claude.json" ] && command -v jq >/dev/null 2>&1; then
            log_info "Cleaning project-level MCP configs..."
            jq '.projects |= with_entries(.value.mcpServers = {})' "$HOME/.claude.json" > /tmp/claude.json.tmp && \
                mv /tmp/claude.json.tmp "$HOME/.claude.json"
        fi

        # Remove old registrations
        claude mcp remove airis 2>/dev/null || true
        claude mcp remove airis --scope user 2>/dev/null || true
        claude mcp remove airis-mcp-gateway 2>/dev/null || true
        claude mcp remove airis-mcp-gateway --scope user 2>/dev/null || true

        # Register globally (user scope only)
        if claude mcp add --scope user --transport sse airis-mcp-gateway http://localhost:9400/sse 2>/dev/null; then
            claude_registered=true
            log_info "Registered globally with Claude Code"
        elif claude mcp add --scope user --transport sse airis-mcp-gateway http://localhost:9400/sse 2>&1 | grep -q "already exists"; then
            claude_registered=true
            log_info "Already registered globally with Claude Code"
        fi
    fi

    echo ""
    if $api_ok && $gateway_ok; then
        echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
        echo -e "${GREEN}║         Installation Complete!           ║${NC}"
        echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
    else
        echo -e "${YELLOW}╔══════════════════════════════════════════╗${NC}"
        echo -e "${YELLOW}║   Installation Complete (with warnings)  ║${NC}"
        echo -e "${YELLOW}╚══════════════════════════════════════════╝${NC}"
    fi

    echo ""
    echo "  Endpoints:"
    $api_ok && echo -e "    API:     ${GREEN}http://localhost:9400${NC}" || echo -e "    API:     ${RED}http://localhost:9400 (not ready)${NC}"
    $gateway_ok && echo -e "    Gateway: ${GREEN}http://localhost:9390${NC}" || echo -e "    Gateway: ${RED}http://localhost:9390 (not ready)${NC}"
    echo ""
    echo "  Config:    $CONFIG_DIR/mcp-config.json"
    echo "  Repo:      $DIR"
    echo ""
    if $claude_registered; then
        echo -e "  Claude Code: ${GREEN}Registered (global)${NC}"
    else
        echo "  Register with Claude Code (global):"
        echo "    claude mcp add --scope user --transport sse airis-mcp-gateway http://localhost:9400/sse"
    fi
    echo ""
    if $workspace_installed; then
        echo -e "  airis-workspace: ${GREEN}Installed${NC}"
        echo "    Run 'airis init' in a project to get started"
    else
        echo -e "  airis-workspace: ${YELLOW}Not installed${NC} (optional)"
        echo "    Re-run with INSTALL_WORKSPACE=true or download from:"
        echo "    https://github.com/agiletec-inc/airis-workspace/releases"
    fi
    echo ""
    echo "  Commands:"
    echo "    cd $DIR && docker compose logs -f    # View logs"
    echo "    cd $DIR && docker compose down       # Stop"
    echo "    cd $DIR && docker compose up -d      # Start"
    echo ""
    echo "  Uninstall:"
    echo "    $DIR/scripts/quick-install.sh --uninstall"
    echo ""
}

uninstall() {
    echo ""
    echo -e "${YELLOW}╔══════════════════════════════════════════╗${NC}"
    echo -e "${YELLOW}║    AIRIS MCP Gateway - Uninstalling      ║${NC}"
    echo -e "${YELLOW}╚══════════════════════════════════════════╝${NC}"
    echo ""

    # Unregister from Claude Code (both local and global)
    if command -v claude >/dev/null 2>&1; then
        log_step "Unregistering from Claude Code..."
        claude mcp remove airis 2>/dev/null || true
        claude mcp remove airis --scope user 2>/dev/null || true
        claude mcp remove airis-mcp-gateway 2>/dev/null || true
        claude mcp remove airis-mcp-gateway --scope user 2>/dev/null || true
    fi

    # Stop containers
    if [ -d "$DIR" ]; then
        log_step "Stopping containers..."
        cd "$DIR"
        docker compose down -v 2>/dev/null || true
    fi

    # Remove repository
    if [ -d "$DIR" ]; then
        log_step "Removing repository..."
        rm -rf "$DIR"
        log_info "Removed $DIR"
    fi

    # Ask about config
    if [ -d "$CONFIG_DIR" ]; then
        echo ""
        read -p "Remove config at $CONFIG_DIR? [y/N] " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf "$CONFIG_DIR"
            log_info "Removed $CONFIG_DIR"
        else
            log_info "Config preserved at $CONFIG_DIR"
        fi
    fi

    echo ""
    log_info "Uninstall complete."
    echo ""
}

# Main
case "${1:-install}" in
    --uninstall|-u|uninstall)
        uninstall
        ;;
    --help|-h|help)
        echo "AIRIS MCP Gateway - Quick Install"
        echo ""
        echo "Usage:"
        echo "  $0              Install (default)"
        echo "  $0 --uninstall  Uninstall"
        echo "  $0 --help       Show this help"
        echo ""
        echo "Environment variables:"
        echo "  AIRIS_MCP_DIR       Repository directory (default: ~/.local/share/airis-mcp-gateway)"
        echo "  AIRIS_CONFIG_DIR    Config directory (default: ~/.config/airis-mcp-gateway)"
        echo "  INSTALL_WORKSPACE   Install airis-workspace CLI (default: true, set to false to skip)"
        ;;
    *)
        install
        ;;
esac
