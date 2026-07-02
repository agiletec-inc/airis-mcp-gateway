"""
Registry/docs drift gate (issue #193).

The registry SSoT is `mcp-config.json` (runtime, gitignored). Its tracked
mirror is `mcp-config.json.example`. Docs, workflows, and static catalogs
must never route agents to a server that doesn't exist in the registry, or
that exists but is `enabled: false` there (unless the text explicitly warns
that the server is disabled).

Scope note: `config/gateway-config.yaml` is intentionally EXCLUDED from this
scan. It is slated for removal in issue #196 and is out of scope here.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]

# `server:tool` call syntax, e.g. "supabase:query", "stripe:create_customer".
# Also matches the `server:*` wildcard form (e.g. "figma:*", "cloudflare:*")
# used in routing-guide prose — a plain trailing `\b` never matches after
# `*` (both neighbours are non-word chars), so a negative lookahead is used
# instead to bound the match for both the alnum and wildcard tool forms.
TOOL_REF_PATTERN = re.compile(r"\b([a-z][a-z0-9-]+):(\*|[a-z][a-z0-9_-]+)(?![a-z0-9_-])")

# `[server]` routing-tag syntax used in workflows/*.yaml mcp_instructions bullets.
BRACKET_REF_PATTERN = re.compile(r"\[([a-z][a-z0-9-]+)\]")

# Servers that must never be advertised in routing contexts, full stop —
# either because they don't exist in the registry, or because the project
# has explicitly decided not to support them (issue #193: cloudflare would
# need real API credentials to register, which is a human decision, out of
# scope). Always a violation, even if a disabled stub happens to exist in
# mcp-config.json.example and even if the line carries a caveat.
FORBIDDEN_SERVERS = {"cloudflare"}

# Phrases that indicate a disabled-server mention is a deliberate, honest
# caveat ("don't call this, it's off") rather than a routing instruction.
DISQUALIFIERS = (
    "disabled",
    "not authorized",
    "never authorized",
    "do not call",
    "not enabled",
    "removed",
    "not support",
    "out of scope",
)

SCAN_FILES = [
    "README.md",
    "CLAUDE.md",
    "docs/architecture.md",
    "config/toolsets.json",
    "catalogs/airis-catalog.yaml",
    *sorted(str(p.relative_to(REPO_ROOT)) for p in (REPO_ROOT / "workflows").glob("*.yaml")),
]


def _load_registry() -> tuple[set[str], set[str], set[str]]:
    """Return (all_servers, enabled_servers, policy_disabled_servers) from the
    tracked registry mirror.

    `policy_disabled_servers` is DERIVED directly from each server's
    `policy_disabled` flag (e.g. supabase, mindbase) rather than a hardcoded
    Python set, so this gate can't silently drift from the registry itself —
    a server can only become policy-disabled by an explicit registry edit.
    """
    data = json.loads((REPO_ROOT / "mcp-config.json.example").read_text())
    servers = data["mcpServers"]
    all_servers = set(servers.keys())
    enabled_servers = {name for name, cfg in servers.items() if cfg.get("enabled")}
    policy_disabled_servers = {name for name, cfg in servers.items() if cfg.get("policy_disabled")}
    return all_servers, enabled_servers, policy_disabled_servers


ALL_SERVERS, ENABLED_SERVERS, POLICY_DISABLED_SERVERS = _load_registry()


def _line_is_disqualified(line: str) -> bool:
    lowered = line.lower()
    return any(phrase in lowered for phrase in DISQUALIFIERS)


def _scan_text_for_routing_violations(relpath: str, text: str) -> list[str]:
    """Find server references in `text` that route to a missing/disabled server."""
    violations: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        candidates: set[str] = set()
        for m in TOOL_REF_PATTERN.finditer(line):
            # Skip connection-string userinfo like "user:pass@host" — not a
            # server:tool call, just credentials embedded in a URL.
            if line[m.end() : m.end() + 1] == "@":
                continue
            candidates.add(m.group(1))
        for m in BRACKET_REF_PATTERN.finditer(line):
            candidates.add(m.group(1))

        for server in candidates:
            # Ignore words that happen to match the pattern but aren't a
            # tracked, forbidden, or known-missing server name (URLs, code
            # identifiers, timestamps, etc.) — this is what keeps the
            # matcher pragmatic.
            if server not in ALL_SERVERS and server not in FORBIDDEN_SERVERS:
                continue

            if server in FORBIDDEN_SERVERS:
                # Never supported here (issue #193): always a violation,
                # regardless of whether a disabled stub exists in the
                # registry mirror.
                violations.append(
                    f"{relpath}:{lineno}: routes to '{server}', which this "
                    f"project has decided not to support — {line.strip()!r}"
                )
                continue

            if server not in ALL_SERVERS:
                # Missing server not covered by FORBIDDEN_SERVERS: always a violation.
                violations.append(
                    f"{relpath}:{lineno}: routes to '{server}', which does not "
                    f"exist in mcp-config.json.example — {line.strip()!r}"
                )
                continue

            if (
                server in POLICY_DISABLED_SERVERS
                and server not in ENABLED_SERVERS
                and not _line_is_disqualified(line)
            ):
                violations.append(
                    f"{relpath}:{lineno}: routes to '{server}', which is "
                    f"enabled:false (policy-disabled) in mcp-config.json.example "
                    f"and the line carries no disabled-server caveat — {line.strip()!r}"
                )

        # Also catch bare mentions of forbidden servers that aren't in
        # `server:tool` or `[server]` syntax — e.g. a markdown table row
        # "| **cloudflare** | ... |" or prose "DNS/workers → cloudflare".
        for server in FORBIDDEN_SERVERS:
            if re.search(rf"\b{re.escape(server)}\b", line, re.IGNORECASE) and not _line_is_disqualified(line):
                violations.append(
                    f"{relpath}:{lineno}: mentions '{server}', which this "
                    f"project has decided not to support — {line.strip()!r}"
                )
    return violations


def test_all_servers_and_enabled_servers_are_populated():
    """Sanity check that the registry mirror actually parsed."""
    assert len(ALL_SERVERS) >= 10
    assert len(ENABLED_SERVERS) >= 5
    assert ENABLED_SERVERS <= ALL_SERVERS


@pytest.mark.parametrize("relpath", SCAN_FILES)
def test_no_routing_references_to_missing_or_disabled_servers(relpath: str):
    path = REPO_ROOT / relpath
    assert path.exists(), f"expected scan target {relpath} to exist"

    text = path.read_text()
    violations = _scan_text_for_routing_violations(relpath, text)

    assert not violations, "Registry/docs drift found:\n" + "\n".join(violations)


def test_toolsets_json_keys_reference_real_registry_servers():
    """config/toolsets.json is keyed by server name — every key must exist in
    the registry and none may be a forbidden server (catches phantom entries
    like the old 'cloudflare' block)."""
    data = json.loads((REPO_ROOT / "config" / "toolsets.json").read_text())
    keys = set(data.keys())
    phantom = (keys - ALL_SERVERS) | (keys & FORBIDDEN_SERVERS)
    assert not phantom, f"toolsets.json references servers not in the registry: {phantom}"


def test_airis_catalog_yaml_registry_keys_reference_real_registry_servers():
    """catalogs/airis-catalog.yaml is keyed by server name under `registry` —
    every key must exist in mcp-config.json.example and none may be a
    forbidden server (catches phantom entries like the old 'cloudflare' block)."""
    data = yaml.safe_load((REPO_ROOT / "catalogs" / "airis-catalog.yaml").read_text())
    registry_keys = set(data.get("registry", {}).keys())
    phantom = (registry_keys - ALL_SERVERS) | (registry_keys & FORBIDDEN_SERVERS)
    assert not phantom, f"airis-catalog.yaml references servers not in the registry: {phantom}"


def test_airis_catalog_yaml_disabled_servers_are_annotated():
    """Any catalog entry for a disabled registry server must carry a nearby
    'disabled' annotation, so a reader/agent doesn't assume it's callable."""
    raw = (REPO_ROOT / "catalogs" / "airis-catalog.yaml").read_text()
    data = yaml.safe_load(raw)
    registry_keys = set(data.get("registry", {}).keys())
    disabled_in_catalog = registry_keys & POLICY_DISABLED_SERVERS

    lines = raw.splitlines()
    for server in disabled_in_catalog:
        key_pattern = re.compile(rf"^  {re.escape(server)}:\s*$")
        key_lineno = next(
            (i for i, line in enumerate(lines) if key_pattern.match(line)), None
        )
        assert key_lineno is not None, f"could not locate top-level key for {server}"

        # Look at the block of lines immediately preceding the key for a
        # disabled-server caveat (comment annotation).
        window = lines[max(0, key_lineno - 10) : key_lineno]
        assert any(_line_is_disqualified(line) for line in window), (
            f"catalogs/airis-catalog.yaml: '{server}' is enabled:false in the "
            f"registry but has no disabled-server annotation above its entry"
        )
