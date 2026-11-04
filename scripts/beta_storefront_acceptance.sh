#!/usr/bin/env bash
# Run all locally available Beta storefront checks without mutating a database
# or contacting Telegram/Bale. Run inside the configured Codespace checkout.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

printf '\n[1/6] Compile Python source\n'
python3 -m compileall -q models services channels dashboard workers scripts tests

printf '\n[2/6] Beta customer experience and security regressions\n'
python3 -m pytest -q   tests/test_beta_p0_security.py   tests/test_beta_customer_menu.py   tests/test_beta_customer_search.py   tests/test_beta_customer_account.py   tests/test_beta_customer_orders.py   tests/test_beta_checkout_policy.py   tests/test_beta_support_fulfillment.py   tests/test_beta_stock_notifications.py   tests/test_beta_chat_navigation.py   tests/test_beta_stars_quote.py   tests/test_beta_stars_snapshot.py

printf '\n[3/6] Existing shop, multibot and payment regressions\n'
python3 -m pytest -q   tests/test_shop_channel_catalog.py   tests/test_multibot_catalog_acl_offline.py   tests/test_multibot_runtime_offline.py   tests/test_shared_cart.py   tests/test_shared_payment_settlement.py

printf '\n[4/6] Next.js TypeScript typecheck\n'
npm --prefix dashboard-next run typecheck

printf '\n[5/6] Next.js lint and unit tests\n'
npm --prefix dashboard-next run lint
npm --prefix dashboard-next run test

printf '\n[6/6] Next.js production build\n'
npm --prefix dashboard-next run build

printf '\nPASS: all offline checks completed.\n'
printf 'Separate PostgreSQL fresh-schema + Telegram/Bale provider E2E remain required.\n'
