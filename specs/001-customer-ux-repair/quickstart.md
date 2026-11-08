# Quickstart: Validate customer UX repair

Run these checks from the repository root with synthetic shoppers and products.
Production tokens, live charges and production data are not needed.

## Offline automated checks

Use Python 3.12 (CI and the existing Docker image use it) and the pinned dependencies.
With an existing isolated Python 3.12 environment:

```powershell
python -m pip install -r requirements.txt
python -m pip install httpx==0.28.1 aiosqlite==0.20.0
python -m pytest -q tests/test_beta_conversation_ux.py tests/test_beta_terms_navigation.py tests/test_beta_checkout_policy.py tests/test_beta_cart_form_navigation.py tests/test_multibot_catalog_acl_offline.py tests/test_runtime_receivers.py
python -m pytest -q tests/test_beta_customer_menu.py tests/test_beta_customer_search.py tests/test_shop_channel_catalog.py tests/test_telegram_channel_transport.py tests/test_bale_channel_transport.py tests/test_beta_paused_customer_support.py
python -m pytest -q tests/test_beta_customer_account.py tests/test_beta_checkout_copy.py
python -m pytest -q tests/test_shared_payment_settlement.py tests/test_beta_dispatch_paid_notification.py tests/test_beta_digital_refund_serialization.py tests/test_shop_delivery_dedup_offline.py tests/test_beta_mixed_split.py tests/test_beta_bale_mixed_cart.py tests/test_beta_bale_mixed_payment_guard.py
python -m pytest -q tests
```

If Python 3.12 is unavailable locally, the following builds the checked-in Python 3.12
Dockerfile and runs the isolated suite with no runtime network:

```powershell
docker build -t aiogram-customer-ux-base:local .
@'
FROM aiogram-customer-ux-base:local
RUN python -m pip install --no-cache-dir httpx==0.28.1 aiosqlite==0.20.0
'@ | docker build -f - -t aiogram-customer-ux-test:local .
docker run --rm --network none aiogram-customer-ux-test:local python -m pytest -q tests
```

Execute focused suites in P0, P1, P2 order and run the full suite for integration. Existing
tests and planned assertions are in [traceability.md](traceability.md). Record versions,
commit, results, and any tests skipped or expected to change (old generic Terms fallback,
single-result Search and gallery-first assumptions). SQLite/transport fakes do not prove
PostgreSQL locking or native-client behavior.

For a full-suite Docker run, install the two test-only packages above in the test image.
Linux shell tests need LF endings. On Windows, run those tests from a disposable snapshot
with LF shell scripts to keep the working tree intact.

## Isolated PostgreSQL and fake-provider journeys

Use Docker Compose v2. The bootstrap profile is on the internal QA network. Leave
existing volumes intact; verify the QA environment guard and use the fake provider clients.
Do not point these commands at an existing deployment or populate live credentials.

```powershell
python -m scripts.beta_qa_environment
docker compose -f compose.beta-qa.yml up -d --wait postgres redis
docker compose -f compose.beta-qa.yml run --rm --build --no-deps bootstrap
docker compose -f compose.beta-qa.yml run --rm --no-deps bootstrap python -m scripts.beta_storefront_e2e --stage seed
```

The storefront runner captures actual callback IDs, edits and wizard steps. The downstream
runners reuse its fake transports. The seed expects the lab's synthetic `shopadmin` fixture.
Use fresh fixture identities or the guarded seed before each suite that mutates orders.

```powershell
docker compose -f compose.beta-qa.yml run --rm --no-deps bootstrap python -m scripts.beta_storefront_e2e --stage menus
docker compose -f compose.beta-qa.yml run --rm --no-deps bootstrap python -m scripts.beta_storefront_e2e --stage concurrency
docker compose -f compose.beta-qa.yml run --rm --no-deps bootstrap python -m scripts.beta_storefront_e2e --stage keyboard
docker compose -f compose.beta-qa.yml run --rm --no-deps bootstrap python -m scripts.beta_storefront_e2e --stage discovery
docker compose -f compose.beta-qa.yml run --rm --no-deps bootstrap python -m scripts.beta_commerce_e2e --stage terms
docker compose -f compose.beta-qa.yml run --rm --no-deps bootstrap python -m scripts.beta_commerce_e2e --stage policy
docker compose -f compose.beta-qa.yml run --rm --no-deps bootstrap python -m scripts.beta_commerce_e2e
docker compose -f compose.beta-qa.yml run --rm --no-deps bootstrap python -m scripts.beta_digital_refund_e2e
docker compose -f compose.beta-qa.yml run --rm --no-deps bootstrap python -m scripts.beta_account_notifications_e2e
```

Validate the additive Alembic upgrade separately against a private PostgreSQL QA instance
with the prior head's schema and a fixture of legacy rows/valid drafts. The historical
Alembic chain starts with SQLite-only SQL. For this QA check, bootstrap the prior revision's
metadata in a fresh private database, verify the schema and stamp the prior head before
applying the new revision. The regular QA bootstrap uses current metadata and does not
itself prove the production migration.
On the guarded QA environment with Alembic configured to that disposable DB, check
`python -m alembic current`, apply `python -m alembic upgrade head`, and verify the
expected revision, preserved existing data, and safe old callback recovery. Do not apply a
downgrade to a live database.

Capture before/after view transcripts, valid action and keyboard order, exact message/markup
counts, provider call counts and durable state deltas. Include distinct update IDs racing
for one control, same-message revision change, lost lease, cancellation, unknown sends,
expired drafts, and policy and quote changes. Assert two unrelated conversations can
make progress concurrently. Compare orders, attempts, consent, refunds, deliveries and
receipts before and after; the paired matrix is in [traceability.md](traceability.md).

## Native-client review

Use separately authorized test bots and controlled shoppers if native checks are available;
never execute a real charge. Capture Telegram and Bale product preview behavior,
legacy Bale ack where available, text edits and fallback, persistence/exit from native
contact, and R-10 narrow-screen/assistive checks. With a Persian reviewer, verify full
terms navigation, plain next-action labels, amounts/currency and mixed-script order
references. Use the existing Store/Bot dashboard policy controls to test defaults, override,
and disabled destinations on both clients. Record client versions and distinguish source,
simulated, and native evidence. If a native case cannot be reproduced, mark it unverified;
do not present a fake result as native acceptance.
