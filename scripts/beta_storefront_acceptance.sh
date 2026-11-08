#!/usr/bin/env bash
# Run the complete offline Beta gate in the configured Codespace checkout.
# No database mutation or Telegram/Bale request is authorized by this script.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

printf '\n[1/6] Compile Python source\n'
python3 -m compileall -q models services channels dashboard workers scripts tests

printf '\n[2/6] All Python regressions, including digital delivery and mixed checkout\n'
# Discover every test, so new Beta and legacy regressions cannot be omitted.
python3 -m pytest -q tests

printf '\n[3/6] Cloudflare Worker and relay-pool regressions\n'
node --test cloudflare/telegram-relay/test/*.test.mjs

printf '\n[4/6] Next.js TypeScript typecheck\n'
npm --prefix dashboard-next run typecheck

printf '\n[5/6] Next.js lint and unit tests\n'
npm --prefix dashboard-next run lint
npm --prefix dashboard-next run test

printf '\n[6/6] Next.js production build\n'
npm --prefix dashboard-next run build

printf '\nPASS: all offline checks completed.\n'
printf 'Separate PostgreSQL fresh-schema, two-provider E2E and browser gates remain required.\n'
