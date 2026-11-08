# Registry-only retirement contract

The supported application entrypoint is `scripts.secure_app:app`. All bots are explicitly registered and every operation is bound to authenticated bot/Store context. Fresh schema creation registers only modern `shop_` tables, creates Store/UoM/admin access and creates zero bots or credentials.

## Removed execution surfaces

The original `bot.py`, `run.py`, `multibot.py`, handlers/repositories/crypto subsystem, original ORM tables, SQLAdmin UI and JWT login, global profile/connection/transport controls, built-in bot adoption and environment provider-token fallback are retired. Registry receivers and signed administration APIs remain. Retired internal routes return 404; provider callbacks use only authenticated v2 bindings.

Historical migration files and recorded QA evidence remain as history. They do not import deleted application modules, synthesize current runtime authority or contact providers.

## Data cleanup

Use `python -m scripts.legacy_schema_cleanup` for a dry run in an explicitly isolated, unversioned Codespace. `--apply` is a separate operation requiring its database safety guards. Versioned databases upgrade through revision `20261107z001` with explicit `-x retire_original_schema=true` after backup and review.

Cleanup uses a fixed allowlist, validates unexpected inbound references, locks the affected schema and applies transactional `DROP ... RESTRICT`. It never cascades into modern business data. Singleton merchant settings are transferred to the canonical default Store settings; conflicting values block the operation. Historical customer links must already agree with canonical same-Store customer membership before the old link table can be retired.

Existing modern orders, customers, financial receipts, Store ownership, owner password/MFA/recovery data, sessions and Workflow Runs must retain their IDs and values. Historical bot rows that still own modern records are audit identities; they grant no live Runtime/Action/credential authority. Old workflow bridge bindings are disabled and obsolete fallback settings normalize to `ignore` while Runs/revisions remain auditable.

## Acceptance requirements

- Fresh PostgreSQL bootstrap twice: zero bots/credentials; stable Store/UoM/admin access.
- Populated retirement fixture: modern business and owner security values unchanged.
- Unexpected inbound foreign key, conflicting merchant settings or unconverted customer links: transaction blocked without partial deletion.
- Explicit Registry credentials, provider identity, Store ACLs, wallet adjustments, independent Bale inquiry, durable receipts and concurrent workers remain enforced.
- Real `/bots` browser and Server Action through Codespaces metadata; retired routes inaccessible.
- Full Python/Next suites, Typecheck/Lint/Build and independent source review.

No live provider sends/payments, public ingress change or customer workflow activation is authorized by these checks.
