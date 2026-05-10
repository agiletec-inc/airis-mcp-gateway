#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$ROOT_DIR/scripts/airis-gateway"

tmpdir="$(mktemp -d "${TMPDIR:-/tmp}/airis-gateway-smoke.XXXXXX")"
trap 'rm -rf "$tmpdir"' EXIT

assert_contains() {
    local haystack="$1"
    local needle="$2"
    if [[ "$haystack" != *"$needle"* ]]; then
        echo "Expected output to contain: $needle" >&2
        exit 1
    fi
}

run_global_registry_flow() {
    mkdir -p "$tmpdir/repos/repo-a" "$tmpdir/repos/repo-b" "$tmpdir/.codex" "$tmpdir/.claude" "$tmpdir/.gemini"

    cat > "$tmpdir/repos/repo-a/mcp.json" <<'JSON'
{"mcpServers":{"github":{"command":"npx","args":["-y","@modelcontextprotocol/server-github"],"env":{"GITHUB_PERSONAL_ACCESS_TOKEN":"${GITHUB_TOKEN}"},"enabled":true}}}
JSON

    cat > "$tmpdir/repos/repo-b/mcp.json" <<'JSON'
{"mcpServers":{"airis-mcp-gateway":{"command":"npx","args":["mcp-remote","http://localhost:9400/sse"],"enabled":true},"github":{"command":"npx","args":["-y","@modelcontextprotocol/server-github"],"env":{"GITHUB_PERSONAL_ACCESS_TOKEN":"${GITHUB_TOKEN}"},"enabled":true}}}
JSON

    cat > "$tmpdir/.codex/config.toml" <<'TOML'
[mcp_servers.airis-mcp-gateway]
url = "http://localhost:9400/mcp"
TOML

    local init_plan
    init_plan="$(
        AIRIS_MCP_DIR="$ROOT_DIR" \
        AIRIS_REGISTRY_DIR="$tmpdir/state" \
        CODEX_CONFIG_PATH="$tmpdir/.codex/config.toml" \
        CLAUDE_CODE_DIR="$tmpdir/.claude" \
        GEMINI_CONFIG_DIR="$tmpdir/.gemini" \
        CLAUDE_DESKTOP_CONFIG_PATH="$tmpdir/claude.json" \
        "$CLI" init "$tmpdir/repos"
    )"
    assert_contains "$init_plan" "AIRIS MCP Init Plan"
    assert_contains "$init_plan" "No files changed"
    test -f "$tmpdir/repos/repo-a/mcp.json"

    AIRIS_MCP_DIR="$ROOT_DIR" \
    AIRIS_REGISTRY_DIR="$tmpdir/state" \
    CODEX_CONFIG_PATH="$tmpdir/.codex/config.toml" \
    CLAUDE_CODE_DIR="$tmpdir/.claude" \
    GEMINI_CONFIG_DIR="$tmpdir/.gemini" \
    CLAUDE_DESKTOP_CONFIG_PATH="$tmpdir/claude.json" \
    "$CLI" init "$tmpdir/repos" --apply >/dev/null

    test ! -f "$tmpdir/repos/repo-a/mcp.json"
    test ! -f "$tmpdir/repos/repo-b/mcp.json"
    test -f "$tmpdir/.claude/commands/airis-research-first.md"
    test -f "$tmpdir/.gemini/settings.json"
    test -f "$tmpdir/.codex/airis/AIRIS.md"

    local doctor_output
    doctor_output="$(
        AIRIS_MCP_DIR="$ROOT_DIR" \
        AIRIS_REGISTRY_DIR="$tmpdir/state" \
        CODEX_CONFIG_PATH="$tmpdir/.codex/config.toml" \
        CLAUDE_CODE_DIR="$tmpdir/.claude" \
        GEMINI_CONFIG_DIR="$tmpdir/.gemini" \
        "$CLI" doctor "$tmpdir/repos"
    )"
    assert_contains "$doctor_output" "AIRIS MCP Doctor: OK"
}

run_codex_drift_detection() {
    mkdir -p "$tmpdir/drift/repo" "$tmpdir/drift/.codex"

    cat > "$tmpdir/drift/.codex/config.toml" <<'TOML'
[mcp_servers.airis-mcp-gateway]
url = "http://localhost:9999/mcp"
TOML

    AIRIS_MCP_DIR="$ROOT_DIR" \
    AIRIS_REGISTRY_DIR="$tmpdir/drift-state" \
    CODEX_CONFIG_PATH="$tmpdir/drift/.codex/config.toml" \
    CLAUDE_CODE_DIR="$tmpdir/drift/.claude" \
    GEMINI_CONFIG_DIR="$tmpdir/drift/.gemini" \
    CLAUDE_DESKTOP_CONFIG_PATH="$tmpdir/drift/claude.json" \
    "$CLI" init "$tmpdir/drift/repo" --apply >/dev/null

    cat > "$tmpdir/drift/.codex/config.toml" <<'TOML'
[mcp_servers.airis-mcp-gateway]
url = "http://localhost:9999/mcp"
TOML

    local doctor_output
    set +e
    doctor_output="$(
        AIRIS_MCP_DIR="$ROOT_DIR" \
        AIRIS_REGISTRY_DIR="$tmpdir/drift-state" \
        CODEX_CONFIG_PATH="$tmpdir/drift/.codex/config.toml" \
        CLAUDE_CODE_DIR="$tmpdir/drift/.claude" \
        GEMINI_CONFIG_DIR="$tmpdir/drift/.gemini" \
        "$CLI" doctor "$tmpdir/drift/repo" 2>&1
    )"
    local status=$?
    set -e

    if [ "$status" -eq 0 ]; then
        echo "Expected doctor to fail for stale Codex endpoint" >&2
        exit 1
    fi

    assert_contains "$doctor_output" "Codex config points to stale endpoint"
    assert_contains "$doctor_output" "airis-gateway init"
}

run_global_registry_flow
run_codex_drift_detection

echo "airis-gateway smoke tests passed"
