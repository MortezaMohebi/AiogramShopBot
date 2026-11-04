# Beta storefront P0–P6 — acceptance results

**Date:** 2026-11-04 (Asia/Tehran)

**PR:** [#14](https://github.com/MortezaMohebi/AiogramShopBot/pull/14), kept Draft

**Branch:** `feat/beta-customer-experience-p0-p6-20261104`

**Verified application commit:** `da9a232419cec67ca825d81369e3a0499d101784`

**Overall:** PASS — offline, actual PostgreSQL/native fakes and running browser; live-provider gates remain BLOCKED.

PASS below means an executed offline or native-fake-provider check. It does
not mean that a real Telegram/Bale payment, public receiver, broadcast or
production rollout has been accepted. No real provider credentials or
financial operations were used.

## Phase matrix

| Phase | Result | Verified behavior |
|---|---|---|
| P0 — Store/Bot security | PASS | Negative catalog/callback/media/refund/campaign Store scope; same numeric IDs in different Bots; signed Admin HMAC/session denial; lease, webhook secret, receipt deduplication and token rotation; actual polling offset recovery. |
| P1 — Home and search | PASS | Both native adapters expose all six Home actions; Persian/SKU search, private forms, cancellation, callback byte bounds and foreign-product denial. |
| P2 — Account | PASS | Contact ownership, address book, Wishlist, every Account callback, two-sided verified linking, historical orders, six-session enrollment races and four-Bot numeric identity isolation. |
| P3 — Cart and checkout | PASS | Manual/Instant gates and complete versioned terms; atomic double-tap Telegram mixed split; independent IRR/XTR receipts/refunds; frozen price/file snapshots; invoice timeout without reissue; independent fake Bale inquiry; idempotent internal-credit ledger. |
| P4 — Support and fulfillment | PASS | Paginated customer/staff ticket threads and foreign denial; atomic staff reply/outbox; shipment transitions; native pinned-file and unique-license delivery; exact settlement required; refund/delivery lock interleavings; unknown sends quarantined without replay. |
| P5 — Notifications | PASS | Per-Bot opt-in/out, operational versus marketing notices, stock subscription/cancel/rearm, concurrent claims, crash/timeout behavior; Registry broadcast across three Bots/two Stores with two workers, pacing and safe cleanup. |
| P6 — Final unification | PASS (bounded QA scope) | Full Python/Relay/Next suites, production build, real PostgreSQL, legacy/Registry regressions, signed HTTP, scoped independent review and 18 desktop RTL routes, the same 18 mobile dark routes, closed-drawer keyboard navigation, four popup viewports and zero MCP errors. |

## Executed gates

| Gate | Environment | Result |
|---|---|---|
| `bash scripts/beta_storefront_acceptance.sh` | Codespace detached checkout `98bf71d`; final local full run `e142400` | PASS (exit 0): 784 Python + 14 Relay + 48 Next; typecheck/lint/build passed. See commit provenance below. |
| Python compile and `python3 -m pytest -q tests` | Local and Codespace | 784 PASS, zero failures/skips; three collection warnings. |
| `node --test cloudflare/telegram-relay/test/*.test.mjs` | Local and Codespace | 14 PASS, zero failures/skips. |
| `npm --prefix dashboard-next run typecheck` | Local and Codespace | PASS. |
| `npm --prefix dashboard-next run lint` | Local and Codespace | PASS, no ESLint errors/warnings. |
| `npm --prefix dashboard-next run test` | Local and Codespace | 48 PASS, zero failures/skips. |
| `npm --prefix dashboard-next run build` | Local and isolated Codespace build checkout | PASS, including the final mobile CSS. |
| Fresh PostgreSQL metadata | Actual PostgreSQL 18 | PASS: 115 tables, 910 columns, 281 indexes, 1,316 constraints. |
| `scripts.beta_storefront_e2e` | Actual PostgreSQL + native Telegram/Bale fakes | PASS: fresh additive seed and both six-menu journeys. |
| `scripts.beta_commerce_e2e` | Actual PostgreSQL + native fakes | PASS: split payments, snapshots, inquiries, digital workers, ambiguity, independent refunds. |
| `scripts.beta_digital_refund_e2e` | Actual PostgreSQL + native fakes | PASS: both order-lock interleavings observed using PostgreSQL blocking PIDs. |
| `scripts.beta_account_notifications_e2e` | Actual PostgreSQL + native fakes | PASS: races, linking, credit, shipment, stock, consent and paginated support. |
| `scripts.beta_broadcast_e2e` | Actual PostgreSQL + native fakes | PASS: 3 sent, 1 opt-out skipped, 1 unknown quarantined; 8 rate slots, 5 connections closed, 3 synthetic receivers paused. |
| `scripts.beta_receiver_admin_e2e` | Actual PostgreSQL, real HTTP, native fakes | PASS: both webhook/polling receivers, lease/dedup/rotation, Store A/B CRUD, multi-Store reads/current-Store writes, HMAC tampering and revoked-session denial. |
| `node scripts/beta_dashboard_browser.mjs` | Running Next 16.4.3 / agent-browser 0.41.2 | PASS (exit 0): activation/fragment scrubbing, real MFA login, all 18 desktop/mobile routes, keyboard close/Tab, four popup sizes and close, zero MCP runtime/compiler errors. |
| Next `/_next/mcp` | Running Codespace dev server | PASS: tool discovery, route map and Turbopack compilation introspection; configuration errors 0, session errors 0, compilation issues 0 (streamed RPC results).. |
| Independent final fix review | Read-only review plus 46 related tests | PASS: no Critical, Important or Minor findings. Earlier whole-branch review also completed; popup CSS had no blocking review findings and its viewport-label metadata finding was corrected. |

### Commit provenance

- Full Codespace offline runner, transactional PostgreSQL probe and native-fake/HTTP integration cycle: `98bf71d`.
- Final UI source plus complete local offline runner: `e142400` (exit 0). Python 784, Relay 14, Next 48, typecheck/lint/build all passed.
- Final browser driver: `da9a232`, which changes only the bounded QA MFA read deadline. Its Backend and UI match the verified commits above; no dependency, lockfile, schema or migration changed in these two final QA commits.
- Runtime browser, UI and MCP results below refer to the same final UI files. Driver-only tooling failures (stale browser daemon, Docker deadline, SSE EOF wait) are recorded separately from product failures and were not counted as passing executions. The final complete browser run on `da9a232` returned exit 0.

The acceptance runner discovers **all** `tests/`, including the six requested
Digital Delivery/Mixed Checkout files. Its own regression test verifies that
new filenames cannot be omitted and that a Python failure stops the gate.
No test was marked PASS merely because source or a commit existed.

## Fresh schema and data preservation

The initial isolated QA stack bootstrapped a new PostgreSQL schema from
SQLAlchemy metadata. The final probe on the unchanged Backend also verified the installed public
schema, created a uniquely named empty schema inside a transaction, set its
local search path, ran `Base.metadata.create_all(checkfirst=False)`, and
compared all ORM columns plus named indexes/constraints. It rolled back the
transaction and confirmed that the temporary schema no longer existed.
Existing public rows and deployment volumes were preserved; no Alembic
revision, database reset or destructive cleanup was needed.

The original Codespace checkout and its prior browser artifacts were kept.
Production build output was isolated from the running Next dev server. A
symlinked dependency directory was replaced in our disposable build checkout
with a local copy of the same installed dependencies because Turbopack
correctly rejects packages outside its project root.

## Failures reproduced and corrected

| Failure | Cause and correction | Verification |
|---|---|---|
| Import-time SyntaxError / missing Index | Literal backslash-newline source and missing ORM import; restore importability and full-model harness. | Full compile and entire Python suite. |
| Private webhook origin accepted; receipts lost after rotation | URL validation branch and credential-version receipt identity. | Negative origin tests and actual duplicate/rotation receiver E2E. |
| Next build/type/runtime issues | Fulfillment types, activation fragment state, Store switcher state and mobile bounds. | Typecheck/lint/unit/build plus browser and MCP gates. |
| Incomplete terms; concurrent first enrollment conflict | Truncated presentation and flush outside conflict recovery. | Complete terms pages and real PostgreSQL enrollment races. |
| Registry broadcasts stranded | Worker consumed only legacy bot identities. | Native Registry adapters, three-Bot/two-worker PostgreSQL run. |
| Cross-Store child and admin mutations | Missing parent scope, selected-read Store confused with write Store. | Signed HTTP negative tests, exact parent ownership and explicit current-Store guards. |
| Polling silently ignored sender then advanced offset | Aiogram serialized `from_user` rather than native `from`. | Alias serialization regression and actual Telegram/Bale polling replay tests. |
| Paginated support acceptance failed | Test expected a combined thread after UI changed to separate message pages. | Real next/previous callback traversal, foreign denial and one outbox notice on both providers. |
| Category/shipping/coupon denial became HTTP 500 | ORM rejection escaped the mounted legacy app after its response began. | Six RED regressions became green; nine scoped cases, 70 related tests, full 784 tests and real PostgreSQL signed HTTP passed. |
| Final MCP reader timed out | SSE returned the RPC response within 0.5 s but kept the connection open. Consume matching complete events and cancel the stream after the result; support JSON and bound reads. | Open-stream/fragmented-CRLF/JSON/EOF regressions; direct runtime/compilation errors were empty. |
| QA MFA read timed out | Cold ORM imports took 16.3 s, beyond the driver's 15 s Docker deadline. Raise the synthetic-account read budget to a bounded 45 s without changing server MFA checks. | Actual six-digit read verified without disclosure. |
| Phone Store popup clipped | A 350 px panel anchored at x=318 extended 32 px beyond the screen. Phone positioning now uses viewport/header side insets and a scrollable height budget; desktop anchoring is preserved. | Bounds checked at 320/390/768/1440 px, including short phone height. |
| Closed mobile navigation retained keyboard focus | Translation alone kept offscreen links focusable. The closed drawer is now invisible below the desktop breakpoint. | Native keyboard open/close/Tab regression; desktop navigation stays visible. |

## Remaining gates and deliberate limits

| Item | State | What remains |
|---|---|---|
| Real Telegram/Bale client delivery and external webhook routing | BLOCKED — not executed | Bot-owner credentials and an explicitly authorized provider run are required. Fake adapters cannot establish remote delivery or public network reachability. |
| Real Stars/Bale settlement, refund receipts and balances | BLOCKED — not executed | Separate authorization and suitable provider test/live credentials. No real invoice, payment or refund was performed. |
| Live notification worker or broadcast activation | BLOCKED — not executed | Explicit rollout approval and provider checks. All deployed QA receiver/payment/notification/broadcast flags remained off. |
| Mixed physical/digital Bale checkout | Deliberately unsupported | Cart, stale checkout, native payment and Store Credit gates reject it. A historical paid receipt is retained for fulfillment/refund review rather than granting an unsafe delivery. Telegram mixed splitting is implemented. |
| Staff account lifecycle | Intentional global control plane | `staff.manage`/superadmin account administration is global. Store-manager membership alone never grants it. Business records remain Store-scoped; this is not a claim of tenant-isolated staff administration. |
| Automated carrier integration | Outside current scope | Manual shipment events/tracking are tested; no unprovided carrier API contract is asserted. |
| Accessibility certification | Not asserted | Browser RTL/responsive checks are bounded; they do not establish a complete WCAG audit. |

The three Python collection warnings concern imported production classes
named `Testimonial` / `TestimonialPatch`; they are not skipped tests. Node's
module-format notices are non-failing tooling warnings. No open known
Critical/Important code-review finding is being hidden behind these notes.

## Reproduce the isolated provider gates

Use the existing private QA environment and pinned dependencies. Do not
substitute deployment credentials, activate workers or recreate volumes.
Build in a separate checkout when Next dev is running.

```bash
bash scripts/beta_storefront_acceptance.sh
# Each module below executes inside the guarded compose.beta-qa.yml API.
docker compose -f compose.beta-qa.yml exec -T api python -m scripts.beta_broadcast_e2e --cleanup
docker compose -f compose.beta-qa.yml exec -T api python -m scripts.beta_storefront_e2e --stage all
docker compose -f compose.beta-qa.yml exec -T api python -m scripts.beta_commerce_e2e
docker compose -f compose.beta-qa.yml exec -T api python -m scripts.beta_digital_refund_e2e
docker compose -f compose.beta-qa.yml exec -T api python -m scripts.beta_account_notifications_e2e
docker compose -f compose.beta-qa.yml exec -T api python -m scripts.beta_broadcast_e2e
docker compose -f compose.beta-qa.yml exec -T api python -m scripts.beta_receiver_admin_e2e
# Run with the documented worktree-scoped agent-browser session and Next dev.
node scripts/beta_dashboard_browser.mjs
```

Commerce intentionally changes only its synthetic product price/file version;
seed a new additive fixture before repeating that module. The broadcast
runner pauses only its proven synthetic receivers in `finally` and never
deletes rows. Browser credentials remain in process memory and private QA
files; no secrets are included in this report or its JSON summary.

Official API rules were checked against the current
[Telegram Stars guide](https://core.telegram.org/bots/payments-stars),
[Telegram Bot API](https://core.telegram.org/bots/api) and
[Bale Bot API](https://docs.bale.ai/): XTR digital invoices, successful-payment
before fulfillment, short callbacks/precheckout handling, independent Bale
transaction inquiry, 10 MB multipart photos/50 MB other uploads and per-Bot
file IDs. This is a bounded compatibility review, not a claim to implement
every endpoint in either API.

## QA commits since `07737fc`

| Commit | Change |
|---|---|
| `4ce38b3` | fix: restore transport imports and full-suite ORM test initialization |
| `946a047` | fix: reject private webhook origins and preserve receipts across token rotation |
| `5390cc4` | test: run complete beta suites and add guarded Codespace QA stack |
| `c634151` | test: bring legacy fixtures through full Store customer and checkout contracts |
| `04dc7ed` | test: compose production admin authorization in the isolated QA runtime |
| `06eca5c` | fix: unblock Next builds and synchronize activation and Store selection state |
| `6e9e680` | test: add real PostgreSQL raw-dispatch Telegram and Bale QA scenarios |
| `038d1c4` | fix: build isolated beta runtime with branch-pinned dependencies |
| `21439fe` | test: exercise native mixed payments and private delivery in real PostgreSQL |
| `7663303` | fix: preserve complete sales terms and recover concurrent customer enrollment |
| `8015bd4` | test: verify live Next dashboard login, RTL routes and mobile rendering |
| `d357a35` | fix: bind private delivery to exact settlement and serialize Stars refunds |
| `29329ce` | fix: expose isolated health routes before fallback and use valid dev origin |
| `e77717b` | feat: dispatch approved Registry broadcasts through scoped durable workers |
| `f25b26a` | fix: guard unsupported mixed Bale payments and show frozen payment currencies |
| `19f4149` | fix: unify customer form cancellation and durable notification generations |
| `80edd46` | fix: enforce Store ownership for campaigns, media, refunds and order summaries |
| `bf89086` | fix: preserve provider sender aliases before polling offsets advance |
| `e6e4870` | fix: honor expiring customer restrictions across account, orders and notices |
| `7394f47` | test: fail closed if any beta QA provider worker is enabled |
| `0f7101d` | fix: unify legacy support, paid notices, restriction expiry and QA cleanup |
| `7f3823c` | fix: keep mobile Store selection visible and expand browser acceptance |
| `b334986` | test: follow paginated support replies in provider acceptance |
| `98bf71d` | fix: map Store write denials before legacy catalog policy mutations |
| `e142400` | fix: bound mobile overlays and finish browser checks on MCP response |
| `da9a232` | test: allow bounded cold-start time for Codespace QA MFA reads |

Machine-readable results: [BETA_STOREFRONT_P0_P6_RESULTS.json](BETA_STOREFRONT_P0_P6_RESULTS.json).

**Disposition:** Keep PR #14 Draft. No merge, deployment, public bot
activation, real payment or broadcast has been authorized by these results.
