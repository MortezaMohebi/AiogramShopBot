#!/usr/bin/env bash
# Resolve the repository rather than relying on the caller's current directory.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
exec python3 -m scripts.security_setup "$@"
