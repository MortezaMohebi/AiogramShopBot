# P5 — Relay / Worker Pool (Multi-Bot)

**Repository:** `MortezaMohebi/AiogramShopBot`
**Branch:** `feat/multibot-relay-worker-pool-20261104` (stacked after P4 / PR #9)
**Status:** **Source implemented / Acceptance pending — NO tests have been run.**

## Architectural contract

- One shop can own many Telegram and Bale bots. The pool handles **outbound Telegram Bot API traffic** for registered Telegram bots. The Bale adapter continues with its existing direct `https://tapi.bale.ai` transport, including its own wallet/media restrictions; it is not forwarded through Telegram's Cloudflare upstream.
- A single Cloudflare Worker can serve many Telegram bots with **independent scoped keys**. A single bot can have multiple assigned Workers with explicit priority. There is **no per-bot container**.
- The new data model uses `shop_relay_workers`, `shop_bot_relay_routes`, `shop_relay_credentials` and append-only `shop_relay_events`. Migration `20261104t001` adds tables after `20261103s001` and does not change customer, wallet or payment data.
- Every credential is bound cryptographically to `(bot_id, worker_id, version)` with an HMAC duplicate-key guard. Every route and status mutation has strict authorization. API responses never contain key material, ciphertext or token fingerprints.
- The Worker accepts `X-Relay-Bot-ID`, `X-Relay-Version`, and `X-Relay-Key`, then verifies the **Telegram Bot API token hash** in the fixed Telegram URL against the corresponding bot's configured record. It only forwards to `https://api.telegram.org`; arbitrary upstream URLs, proxy authentication, cookies and relay headers are stripped.
- Cloudflare `RelayQuota` Durable Object stores a global per-second budget and per-bot budget, plus bounded concurrent network leases. The quota persists across Worker isolates; failures are fail-closed. Actual limits must be configured correctly in the Worker secret binding. Dashboard capacity entries are planning constraints, not substitutes for Worker quotas.
- **Failover is permitted only for read-only `getMe`, `getWebhookInfo`, `getUpdates`, and `getFile` on network failure.** All send, invoice, refund, webhook mutation and other unknown methods use one selected route once. An ambiguous external result may have succeeded; never blindly resend through another Worker.
- File downloads stay on the selected Worker origin, with no cross-origin secret forwarding or replay. Old Telegram/Bale bot credentials and the old relay remain unchanged unless an operator performs the separate opt-in cutover.
- `SHOP_RELAY_POOL_ENABLED=false` by default. With flag enabled, an active registry Telegram bot **requires** an assigned, active, permitted route and credential; no silent direct fallback is made.

## Provisioning — explicit, non-automated

1. Back up PostgreSQL and apply migrations through `20261104t001` only after P1–P4 acceptance. Do not run live provider migration implicitly.
2. Deploy the Cloudflare Worker code and its Durable Object binding from `cloudflare/telegram-relay/wrangler.toml`. Every request requires `RELAY_CLIENTS_JSON` plus the Durable Object quota; shared-key authentication is rejected before forwarding.
3. Allowlist each exact public Worker HTTPS **origin** in `TELEGRAM_WORKER_ALLOWED_ORIGINS` on the Python server. No local/IP/unknown domain should receive a Bot API token.
4. Configure `RELAY_CLIENTS_JSON` as a **Cloudflare encrypted secret**, not in Git, environment templates, logs or Worker source. The format is:

```json
{
  "11111111-1111-4111-8111-111111111111": {
    "token_sha256": "<sha256-hex-of-the-corresponding-telegram-token>",
    "keys": { "1": "<distinct-32-plus-character-random-key>" },
    "rps": 5,
    "max_inflight": 5
  }
}
```

The keys in this example are placeholders, not usable secrets. For each bot, obtain the SHA-256 of the bot token through an approved local secure process without printing/recording the token itself. Set `RELAY_GLOBAL_RPS` and `RELAY_GLOBAL_INFLIGHT` in the Worker deployment (default declared 20/20) and verify they do not exceed the provider-approved limit.
5. Register each Worker at `/relay-workers` (name, slug, allowlisted origin and declared limits); the record starts in `draft`. On a Telegram bot's `/bots/{id}` page assign one or more Workers with distinct priorities; they start in `staged`.
6. Stage the matching secret for each `(bot, worker)` combination through the signed admin interface. The key must already be provisioned at Cloudflare with matching version and bot token digest. The key is not recoverable from the dashboard.
7. Use the **explicit MFA-gated Activate** action. The server performs *read-only* `getMe` through that exact Worker and checks the verified Provider Bot ID before committing active status. A successful probe is not proof of end-to-end payment/checkout readiness.
8. Activate the pool and P4 runtime flags **only after real QA**, with staged cutover and approval. Operator may pause a Worker or Route; this only affects **future route selection**, not updates or receipts already processed.

### Rotation / revocation

1. Add a **new** version to the encrypted `RELAY_CLIENTS_JSON` binding while retaining the old version.
2. Stage the same new secret in the dashboard (never reuse a key across bots or Workers).
3. Activate the staged version using MFA + read-only `getMe`. The old version becomes `retiring` in PostgreSQL; future outbound requests use the new version.
4. Remove the old version from Cloudflare's encrypted secret configuration; only then revoke the retiring version in the admin interface. **Database revocation alone cannot revoke a secret already installed in a remote Worker.**
5. If an outcome is uncertain, disable the route and reconcile manually. There is no automatic replay of network mutations.

## Scope boundaries and operational safety

- P5 does **not** introduce a Bale proxy. Bale remains direct; no Telegram Worker is allowed to forward Bale credentials to `api.telegram.org`.
- The Broadcast Worker resolves each campaign’s explicit Registry bot and credential version. Every send rechecks Store, bot, receiver, consent and quota; relay setup does not enable campaign dispatch or paid Bale Business mode.
- P5 does not auto-rotate Bot API tokens. Worker auth versions rotate independently; Bot API token rotations also require updating the Worker token fingerprint and a separate verified receiver procedure.
- Worker quota violations return HTTP 429; the client **does not** retry a send, because an upstream outcome may be ambiguous. Read-only operations can choose the next active route only for transport failures.
- For read-only `getUpdates`, the P4 receipt ledger and persisted offsets still provide per-bot duplicate protection. There is no system-managed duplicate Webhook/Polling owner.
- Route activation and Worker provisioning cannot run without an existing registered, verified bot and fresh MFA. No Worker can be implicitly activated just by its creation.
- Outbound routing comes from each registered bot’s reviewed relay routes. A shared environment setting cannot select its bot, relay credential or key version.

## QA — everything below is NOT RUN

- [ ] `python -m pytest -q tests/test_relay_pool_offline.py` and P1–P4 tests.
- [ ] `node --test cloudflare/telegram-relay/test/*.test.mjs` including v1 compatibility.
- [ ] `npm --prefix dashboard-next run typecheck && npm --prefix dashboard-next run lint && npm --prefix dashboard-next run build`.
- [ ] Alembic `s001 → t001` against a **backed-up PostgreSQL snapshot**, with all customer/credit/refund/order counts intact and twice-run Codespace bootstrap.
- [ ] Superadmin vs non-admin RBAC, CSRF, recent-session enforcement, MFA replay and stale version negative probes.
- [ ] Two Telegram bots on one Worker with independent keys/token digests; same bot on two Workers with distinct ordered routes.
- [ ] Worker 429 quota, concurrent Durable Object requests, streaming media, missing DO binding and invalid secret mapping. Verify no plaintext token or key in exceptions or logs.
- [ ] Disconnect Worker A while **read-only** `getMe` / `getUpdates` is in progress; verify Worker B is allowed only under the reviewed safe-method allowlist.
- [ ] Disconnect Worker A after an ambiguous `sendMessage` / `sendInvoice`; verify **no** second API request is dispatched.
- [ ] Manual two-phase key rotation, rollback, operator pause/resume, external Cloudflare revocation, restart recovery.
- [ ] Provider-live Telegram and Bale checkout, refunds, settlement, media and callback isolation with four test bots; no production bot traffic until approved.
- [ ] Capacity test under realistic workloads and quotas; reconcile Worker-side settings against dashboard-stored planning limits.
- [ ] Signed review and explicit permission for staged rollout; GitHub PR remains Draft until QA passes.

**Conclusion:** P5 source implementation is committed. It is **not production verified** and should not be merged or enabled before operational acceptance.
