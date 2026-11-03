#!/usr/bin/env bash
# Use only the repository-local Codespaces setup, never production Compose.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
exec python3 scripts/codespace_setup.py "$@"
