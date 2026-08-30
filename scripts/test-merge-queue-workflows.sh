#!/usr/bin/env bash
# Required Actions checks must report on GitHub's temporary merge-group SHA.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for workflow in ci.yml codeql.yml; do
    path="$ROOT_DIR/.github/workflows/$workflow"
    if ! grep -Eq '^  merge_group:' "$path"; then
        echo "FAIL: $workflow must handle the merge_group event" >&2
        exit 1
    fi
done

echo "merge queue workflow tests passed"
