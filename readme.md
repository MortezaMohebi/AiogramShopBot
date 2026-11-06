# Telegram + Bale Shop and Workflow Studio

One shared FastAPI backend and Next.js administration dashboard manage independently registered Telegram and Bale bots. Each bot belongs to a Store, owns encrypted credentials and has explicit catalog, commerce and receiver policies. Register bots from **Dashboard → Bots**; fresh installations contain no bots or provider credentials.

The application includes Store-scoped products/UoM, carts/orders, customer support, merchant credit, verified payment accounts, digital delivery, consent-based campaigns, and Workflow Studio with typed Actions, revisions, safe simulation and durable sessions/inbox/outbox. Workflow publication, external side effects and approvals retain their explicit authorization gates.

## Runtime

- Backend: `python -m uvicorn scripts.secure_app:app --host 0.0.0.0 --port 5000`.
- Dashboard: `dashboard-next/` (Next.js 16.4.3, React 19.2).
- Shared Registry receiver supervisor: authenticated per-bot polling or `POST /webhooks/v2/{binding_id}/{route_secret}`.
- Shared durable workers: Workflow Runtime, customer notifications, digital delivery and optional approved campaign dispatch.
- PostgreSQL stores business data and receipts; Redis handles ephemeral coordination/rate limits.

There is no SQLAdmin interface, environment-owned bot, original Telegram dispatcher, automatic webhook registration, global bot-mode controller or cryptocurrency wallet subsystem. Every customer/financial operation requires explicit bot and Store ownership. Uncertain external delivery outcomes remain quarantined for review.

## Codespaces

```bash
bash scripts/setup_codespace.sh init
bash scripts/setup_codespace.sh start
bash scripts/setup_codespace.sh status
bash scripts/setup_codespace.sh auth-smoke
```

Open the private Dashboard port from Codespaces **Ports**. Complete the owner's normal password/MFA flow, create a bot draft, stage its credential, verify provider identity and review its receiver settings. Registering a draft does not activate a receiver or grant product access. Keep the internal backend and Dashboard private; expose only the webhook gateway when external delivery is explicitly intended.

Codespaces bootstrap creates an explicitly isolated fresh schema and default Store/UoM/staff grants. It does not replay historical SQLite migrations or create built-in bots. See [Codespaces setup](docs/CODESPACES_LIVE_SETUP.fa.md).

## Existing database cleanup

Back up the database first. For the unversioned isolated beta environment:

```bash
python -m scripts.legacy_schema_cleanup
python -m scripts.legacy_schema_cleanup --apply
```

The default is a read-only plan. Apply requires the exact isolated database guards, inventories external foreign keys and uses a transaction without `CASCADE`. Modern staff/MFA/sessions, Store/customer/product/order/payment/workflow data are preserved. Conflicting settings or unconverted customer links block cleanup. Versioned installations use the reviewed Alembic retirement revision and its explicit acknowledgement; see [retirement contract](docs/REGISTRY_ONLY_RETIREMENT.md).

## Validation

```bash
python -m pytest -q
cd dashboard-next
npm ci
npm test
npm run typecheck
npm run lint
npm run build
```

Use isolated PostgreSQL and Fake Providers for acceptance. Test helpers never authorize live messages, payments, public exposure or customer workflow activation. Current acceptance reports live in `docs/qa/`; earlier reports describe their recorded source commits.

## Deployment

Copy `.env.template` and `.env.next-admin.example` to the matching private environment files. Generate independent database, Redis, bridge, session and MFA encryption secrets; use matching bridge secrets on both sides. Configure the exact HTTPS Dashboard origin. `scripts/deploy.sh info` describes the explicit build/migration/start flow. Existing deployments require a reviewed migration plan; a fresh Codespace uses its dedicated schema bootstrap.

License and third-party notices are retained in the repository and Dashboard runner.
