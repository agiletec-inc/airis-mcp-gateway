#!/usr/bin/env bash
# Guard: airis-mcp-gateway is a PUBLIC repository, so every GitHub Actions job
# must run on a GitHub-hosted runner (ubuntu-*, macos-*, windows-*).
#
# Self-hosted runners on a public repo let any fork pull request execute code
# on the runner host — GitHub's own guidance says self-hosted runners should
# "almost never be used for public repositories". This script fails CI if any
# workflow declares a non-hosted `runs-on`, so the policy cannot regress.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKFLOW_DIR="$ROOT_DIR/.github/workflows"

if [ ! -d "$WORKFLOW_DIR" ]; then
    echo "no .github/workflows directory — nothing to check"
    exit 0
fi

bad=0
checked=0

for wf in "$WORKFLOW_DIR"/*.yml "$WORKFLOW_DIR"/*.yaml; do
    [ -e "$wf" ] || continue
    name="$(basename "$wf")"

    # Extract every `runs-on:` value. Handles `runs-on: x`, quoted values and
    # inline arrays `runs-on: [a, b]`; emits one normalised value per line.
    values="$(grep -E '^[[:space:]]*runs-on:' "$wf" \
        | sed -E 's/.*runs-on:[[:space:]]*//' \
        | tr -d '[]"'"'" \
        | tr ',' '\n' \
        | sed -E 's/^[[:space:]]*//; s/[[:space:]]*$//' \
        | grep -v '^$' || true)"

    [ -z "$values" ] && continue

    while IFS= read -r value; do
        checked=$((checked + 1))
        case "$value" in
            ubuntu-* | macos-* | windows-*)
                ;;  # GitHub-hosted — OK
            *)
                echo "FAIL: $name declares runs-on '$value' — not a GitHub-hosted runner" >&2
                bad=1
                ;;
        esac
    done <<< "$values"
done

if [ "$bad" -ne 0 ]; then
    {
        echo ""
        echo "airis-mcp-gateway is a PUBLIC repository: every job must use a"
        echo "GitHub-hosted runner (ubuntu-*, macos-*, windows-*). Self-hosted"
        echo "runners are forbidden here — a fork pull request could run code on"
        echo "the runner host. See GitHub's secure-use guidance."
    } >&2
    exit 1
fi

echo "workflow runner tests passed — $checked job(s), all GitHub-hosted"
