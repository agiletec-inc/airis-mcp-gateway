#!/usr/bin/env bash
# Regression test for issue #135: compose-file reference drift.
#
# PR #146 renamed the root docker-compose.yml to compose.yaml but left stale
# references to the old name in task configs and autostart templates, which
# silently broke `task dev:*` and OS autostart. This test fails if any
# REPO_ROOT-relative compose reference points at a file that does not exist,
# or if a second auto-discoverable compose file reappears at the repo root.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

fail() { echo "FAIL: $1" >&2; exit 1; }

# 1. The canonical compose file exists at the repo root.
[ -f "$ROOT_DIR/compose.yaml" ] || fail "compose.yaml missing at repo root"

# 2. compose.yaml is the ONLY compose file at the repo root. No compose.yml,
#    no compose.<env>.yaml overrides (e.g. .dev/.dist), no legacy
#    docker-compose*.{yml,yaml}. One file builds-or-pulls for every audience
#    (image+build+pull_policy in compose.yaml), so any sibling is either a
#    reintroduced variant or an auto-discovery conflict (issue #135).
shopt -s nullglob
strays=()
for f in "$ROOT_DIR"/compose.yml \
         "$ROOT_DIR"/compose.*.yaml "$ROOT_DIR"/compose.*.yml \
         "$ROOT_DIR"/docker-compose*.yml "$ROOT_DIR"/docker-compose*.yaml; do
    # compose.yml has no wildcard, so nullglob can't drop it — test existence.
    [ -e "$f" ] && strays+=("$(basename "$f")")
done
shopt -u nullglob
if [ ${#strays[@]} -gt 0 ]; then
    fail "stray compose file(s) at repo root: ${strays[*]} — there must be exactly one compose file: compose.yaml"
fi

# 3. Every "<REPO_ROOT>/<file>.ya?ml" compose reference resolves to a real file.
#    Covers both `{{.REPO_ROOT}}` (go-task) and `{{REPO_ROOT}}` (autostart
#    templates) — the shared "REPO_ROOT}}/" substring matches either form.
check_file_refs() {
    local where="$1" refs ref
    refs="$(grep -oE 'REPO_ROOT}}/[A-Za-z0-9._/-]+\.ya?ml' "$ROOT_DIR/$where" \
        | sed 's#.*REPO_ROOT}}/##' | sort -u)"
    [ -n "$refs" ] || fail "$where: no REPO_ROOT-relative compose reference found"
    while IFS= read -r ref; do
        [ -f "$ROOT_DIR/$ref" ] || \
            fail "$where references '$ref' which does not exist at repo root"
    done <<< "$refs"
}

check_file_refs ".tasks.d/dev.yml"
check_file_refs "ops/autostart/macos/com.agiletec.airis-mcp-gateway.plist.tmpl"
check_file_refs "ops/autostart/linux/airis-mcp-gateway.service.tmpl"

echo "compose reference tests passed"
