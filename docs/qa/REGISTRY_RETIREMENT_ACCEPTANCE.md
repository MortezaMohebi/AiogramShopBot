# Registry-only retirement — acceptance

Scope: retire the original application, global compatibility APIs and obsolete database schema across the repository, while preserving modern Store-owned data and capabilities. The branch is based on `16b229f6` from Draft PR #19. No merge is part of this operation.

## Verified changes

- Registry-only ASGI entrypoint, BotContext, explicit Store ownership, per-bot credentials and receivers. The original bot/handler/repository/crypto application and SQLAdmin are removed.
- Broadcast, notifications, digital delivery and Workflow Runtime retain durable receipts and unknown-result quarantine; no environment-token fallback remains.
- Cloudflare relay accepts only authenticated v2 per-bot bindings. The shared-key v1 protocol is removed.
- Fresh installation initializes the current 119-table model transactionally. A populated database cannot be mistaken for a fresh install. Existing versioned databases retain the guarded migration path.
- Retirement is restricted to 24 named tables, uses PostgreSQL transactional DDL and `RESTRICT`, and blocks external foreign keys, merchant-text conflicts or unresolved customer identity links.
- The Codespaces Origin regression is fixed without broadening CSRF origins. New bot forms use the current Store. Bot-specific Relay choices validate Store access and expose only that Store's assignment counts.
- HTML form patterns use browser-compatible Unicode Sets syntax, including Slug, username, Workflow and UoM forms.

## Evidence

| Check | Result | Evidence |
| --- | --- | --- |
| Full Python suite | 1306 PASS (3 existing collection warnings) | `registry-retirement/python.log` |
| Next.js unit tests | 307 PASS | `registry-retirement/next-tests.log` |
| Typecheck, Lint, production Build | PASS | `registry-retirement/next-*.log` |
| Cloudflare Worker tests | 15 PASS | `registry-retirement/relay.log` |
| PostgreSQL schema acceptance | 11 PASS | `registry-retirement/postgresql.json` |
| PostgreSQL Runtime acceptance | 23 PASS | `registry-retirement/runtime.log` |
| PostgreSQL Broadcast | PASS: three bots, two concurrent workers | `registry-retirement/broadcast.json` |
| Active Codespace schema retirement | PASS: 24 obsolete tables removed, all 119 modern tables preserved | `registry-retirement/live-cutover.json` |
| Actual production `/bots` browser flow | 11 PASS; zero console/runtime/failed HTTP responses | `registry-retirement/browser.json` |

The dedicated PostgreSQL schema acceptance includes rollback after a late initialization failure, competing initializers, repeated bootstrap, conflict preflights, populated-data preservation and repeated retirement. Runtime and Broadcast acceptance use Fake Providers and real PostgreSQL, including competing workers, crash recovery and unknown send outcomes without automatic retry.

The active `telegram-bale-connection-ready` database was backed up privately before retirement. Within the same DDL transaction, hashes of modern records were compared before commit; owner password/MFA/session, Store and other business rows were preserved. Singleton merchant text was checked separately for a lossless transfer. Private SQL backups, session cookies, real secrets and resolved operational configuration are excluded from Git.

The old `telegram-bale-codespace` app, Dashboard and gateway are stopped. Its database/volumes remain available for recovery. Current development access remains port 3006; webhook ingress 8086 stays Private. No real bot credentials, live sends, payments, webhook transfers or customer Workflow activation occurred.

## Limits and retained history

Historical migrations, legal attribution and old QA evidence remain historical records. Historical bot identities that still own modern orders in another installation are retained as inert audit owners; they cannot acquire Runtime, Action or credential authority. Restoring retired historical business data requires a verified SQL backup.

This acceptance proves controlled Fake Provider behavior and the running Codespace UI. It does not claim a live Telegram/Bale provider onboarding or financial transaction.
