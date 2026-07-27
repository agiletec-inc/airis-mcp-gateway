#!/usr/bin/env bash
set -euo pipefail

# AIRIS MCP Gateway - One-Command Installer
# Usage:
#   Install:   curl -fsSL https://raw.githubusercontent.com/agiletec-inc/airis-mcp-gateway/main/install.sh | bash
#   Uninstall: airis-mcp-gateway --uninstall
#
# No git required. Uses pre-built Docker images from GHCR.

VERSION="${AIRIS_VERSION:-latest}"
DIR="${AIRIS_MCP_DIR:-$HOME/.local/share/airis-mcp-gateway}"
BIN_DIR="${HOME}/.local/bin"
BASE_URL="https://raw.githubusercontent.com/agiletec-inc/airis-mcp-gateway/${VERSION}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()  { echo -e "${BLUE}[STEP]${NC} $1"; }

download() {
    local url="$1" dest="$2"
    local attempt
    for attempt in 1 2 3; do
        if curl -fsSL "$url" -o "$dest" 2>/dev/null; then
            return 0
        fi
        [ "$attempt" -lt 3 ] && sleep 1
    done
    log_error "Failed to download: $url"
    return 1
}

check_dependencies() {
    local missing=()
    command -v docker >/dev/null 2>&1 || missing+=("docker")
    command -v curl >/dev/null 2>&1 || missing+=("curl")

    if [ ${#missing[@]} -ne 0 ]; then
        log_error "Missing dependencies: ${missing[*]}"
        echo ""
        echo "Please install:"
        echo "  - Docker: https://docs.docker.com/get-docker/"
        exit 1
    fi

    if ! docker info >/dev/null 2>&1; then
        log_error "Docker is not running. Please start Docker Desktop or OrbStack."
        exit 1
    fi

    if ! docker compose version >/dev/null 2>&1; then
        log_error "Docker Compose v2 is required. Update Docker or install docker-compose-plugin."
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

    # Detect existing installation (accept legacy docker-compose.yml name)
    local is_update=false
    if [ -f "$DIR/compose.yaml" ] || [ -f "$DIR/docker-compose.yml" ]; then
        is_update=true
        log_info "Existing installation detected. Updating..."
    fi

    # Step 1: Download files (no git clone)
    log_step "1/4 Downloading configuration..."
    mkdir -p "$DIR"

    download "$BASE_URL/compose.yaml" "$DIR/compose.yaml"
    # Drop the legacy filename so Docker Compose does not auto-discover two files
    rm -f "$DIR/docker-compose.yml"

    # Only download mcp-config if not exists (preserve user customizations)
    if [ ! -f "$DIR/mcp-config.json" ]; then
        download "$BASE_URL/mcp-config.json.example" "$DIR/mcp-config.json"
        log_info "Created default mcp-config.json"
    else
        log_info "Preserved existing mcp-config.json"
    fi

    # Step 2: Start services
    log_step "2/4 Starting services..."
    cd "$DIR"
    docker compose pull -q 2>/dev/null || true
    docker compose up -d

    # Step 3: Health check with exponential backoff
    log_step "3/4 Verifying installation..."
    local api_ok=false
    local delay=2
    for i in {1..6}; do
        if curl -fsS http://localhost:9400/health >/dev/null 2>&1; then
            api_ok=true
            break
        fi
        sleep "$delay"
        delay=$((delay * 2 > 16 ? 16 : delay * 2))
    done

    # Step 4: Install CLI + Initialize client configuration
    log_step "4/4 Setting up CLI and client configuration..."

    # Install airis-mcp-gateway CLI
    mkdir -p "$BIN_DIR"
    download "$BASE_URL/scripts/airis-mcp-gateway" "$BIN_DIR/airis-mcp-gateway"
    chmod +x "$BIN_DIR/airis-mcp-gateway"

    local path_ok=true
    if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
        path_ok=false
    fi

    # Initialize AIRIS registry and managed client config
    local registry_initialized=false
    if "$BIN_DIR/airis-mcp-gateway" init "$DIR" --apply >/dev/null 2>&1; then
        registry_initialized=true
    fi

    # Register with Claude Code (if available)
    local claude_registered=false
    if command -v claude >/dev/null 2>&1; then
        # Remove old registrations (current and legacy names)
        claude mcp remove airis-mcp-gateway --scope user 2>/dev/null || true
        claude mcp remove airis-mcp-gateway --scope user 2>/dev/null || true

        if claude mcp add --scope user --transport http airis-mcp-gateway http://localhost:9400/mcp/ 2>/dev/null; then
            claude_registered=true
        fi
    fi

    # Gateway installation does not install repository tooling.
    # Summary
    echo ""
    if $api_ok; then
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
    $api_ok && echo -e "    API: ${GREEN}http://localhost:9400${NC}" || echo -e "    API: ${RED}http://localhost:9400 (not ready — check 'docker compose logs')${NC}"
    echo ""
    echo "  Files:"
    echo "    Config:  $DIR/mcp-config.json"
    echo "    Compose: $DIR/compose.yaml"
    echo ""
    echo "  CLI: airis-mcp-gateway"
    if ! $path_ok; then
        echo -e "    ${YELLOW}Add to PATH:${NC} export PATH=\"$BIN_DIR:\$PATH\""
    fi
    echo ""

    if $registry_initialized; then
        echo -e "  AIRIS Registry: ${GREEN}Initialized${NC}"
        echo "    Path: ~/.airis/mcp/registry.json"
    else
        echo "  Initialize AIRIS registry:"
        echo "    airis-mcp-gateway init"
    fi
    echo ""

    if $claude_registered; then
        echo -e "  Claude Code: ${GREEN}Registered (global)${NC}"
    else
        echo "  Register with Claude Code:"
        echo "    claude mcp add --scope user --transport http airis-mcp-gateway http://localhost:9400/mcp/"
    fi
    echo "  Claude Desktop: unmanaged (AIRIS does not modify its MCP config automatically)"
    echo ""

    # Next steps
    echo -e "  ${BOLD}Next steps:${NC}"
    echo "    1. Import and remove any repo-local mcp.json files:"
    echo "       airis-mcp-gateway import ~/github --apply"
    echo "       airis-mcp-gateway clean ~/github"
    echo "       airis-mcp-gateway doctor ~/github"
    echo "    2. Open Codex or Claude Code"
    echo "    3. Install superpowers plugin for TDD/debugging/planning:"
    echo "       /plugin install superpowers"
    echo "    4. Install playwright-cli for browser automation:"
    echo "       playwright-cli install --skills"
    echo ""
    echo "  Commands:"
    echo "    airis-mcp-gateway up       # Start"
    echo "    airis-mcp-gateway down     # Stop"
    echo "    airis-mcp-gateway logs -f  # View logs"
    echo "    airis-mcp-gateway status   # Check status"
    echo "    airis-mcp-gateway servers  # List MCP servers"
    echo "    airis-mcp-gateway init     # Initialize global registry"
    echo "    airis-mcp-gateway doctor   # Detect repo-local mcp.json drift"
    echo ""
    echo "  Uninstall:"
    echo "    airis-mcp-gateway --uninstall"
    echo ""
}

uninstall() {
    echo ""
    echo -e "${YELLOW}╔══════════════════════════════════════════╗${NC}"
    echo -e "${YELLOW}║    AIRIS MCP Gateway - Uninstalling      ║${NC}"
    echo -e "${YELLOW}╚══════════════════════════════════════════╝${NC}"
    echo ""

    # Unregister from Claude Code
    if command -v claude >/dev/null 2>&1; then
        log_step "Unregistering from Claude Code..."
        claude mcp remove airis-mcp-gateway --scope user 2>/dev/null || true
        claude mcp remove airis-mcp-gateway --scope user 2>/dev/null || true
    fi

    # Stop containers (accept legacy docker-compose.yml name)
    if [ -f "$DIR/compose.yaml" ] || [ -f "$DIR/docker-compose.yml" ]; then
        log_step "Stopping containers..."
        cd "$DIR"
        docker compose down -v 2>/dev/null || true
    fi

    # Remove installation
    if [ -d "$DIR" ]; then
        log_step "Removing installation..."
        rm -rf "$DIR"
        log_info "Removed $DIR"
    fi

    # Remove CLI
    if [ -f "$BIN_DIR/airis-mcp-gateway" ]; then
        rm -f "$BIN_DIR/airis-mcp-gateway"
        log_info "Removed $BIN_DIR/airis-mcp-gateway"
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
        echo "AIRIS MCP Gateway - One-Command Installer"
        echo ""
        echo "Usage:"
        echo "  curl -fsSL https://raw.githubusercontent.com/agiletec-inc/airis-mcp-gateway/main/install.sh | bash"
        echo ""
        echo "  install.sh              Install (default)"
        echo "  install.sh --uninstall  Uninstall"
        echo "  install.sh --help       Show this help"
        echo ""
        echo "Environment variables:"
        echo "  AIRIS_VERSION      Gateway version to install (default: latest, e.g. v1.2.3)"
        echo "  AIRIS_MCP_DIR      Install directory (default: ~/.local/share/airis-mcp-gateway)"
        ;;
    *)
        install
        ;;
esac
