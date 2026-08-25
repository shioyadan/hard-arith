#!/usr/bin/env bash

set -euo pipefail

workspace_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v devcontainer >/dev/null 2>&1; then
    echo "devcontainer CLI is not installed." >&2
    echo "Run: npm install -g @devcontainers/cli" >&2
    exit 127
fi

devcontainer up --workspace-folder "$workspace_dir"

if (( $# == 0 )); then
    exec devcontainer exec --workspace-folder "$workspace_dir" bash
fi

exec devcontainer exec --workspace-folder "$workspace_dir" "$@"
