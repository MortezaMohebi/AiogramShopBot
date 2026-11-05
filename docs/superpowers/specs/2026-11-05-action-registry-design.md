# Layer 2 — typed Action Registry

Base: c3c6e79796f864f09df4deb0462cd36f221dbf9e (completed Layer 1, Draft PR 15).
Branch: feat/bot-experience-layer2-action-registry.
The user selected complete Layer 2 implementation; Layer 3/4 remain outside scope.

## Intent and approach

Reuse the shared Python application services, existing SQLAlchemy transactions,
Signed Bridge, revocable staff identity and Next.js dashboard. A central explicit
registry exposes versioned typed descriptors, never dynamic imports or service
names. A separate command bus would duplicate this boundary; SDK-specific Actions
would duplicate commerce logic and tie Actions to delivery. The chosen approach
is one Python registry with small explicit service adapters and no provider I/O.

Layer 1 remains a portable definition/editor/simulator. Layer 2 owns invocation
validation, authorization, availability, approval contracts, receipts and safe
execution. It stores no customer Runtime session, starts no provider listener,
registers no dispatcher routing and exposes no live execute HTTP endpoint.

## Contracts

Strict Pydantic descriptors provide stable key and exact semantic version,
input/output/error schemas, actor/scopes, context requirements, side-effect class,
idempotency/retry/timeout/transaction policy, confirmation/approval policy,
platforms, availability, simulation/dry-run support, sensitive field paths,
audit and deprecation/replacement metadata. Registry rejects duplicates and
unsafe keys; only explicitly registered adapters are resolvable.

An Invocation contains client operation identity, action key/version, typed input,
mode and bounded optional workflow/run/node/correlation metadata. Trusted Store,
Bot, platform, identity/customer and staff grants come from Backend factories and
are rechecked at invocation. Request bodies cannot supply authoritative scopes,
roles, Store ownership or approval booleans. Staff inspection never impersonates
a customer. Runtime/customer invocation stays an internal application boundary.

Results distinguish succeeded/failed/retryable/pending_approval/pending_external/
skipped/unavailable, carry stable safe errors, timing, correlation, receipt IDs
and redacted audit summaries. Output model validation filters unexposed fields.
Raw exceptions, provider secrets, private contacts and support text do not enter
logs, receipt summaries or catalog metadata.

## Availability and adapters

- Catalog list/search/detail/visibility/price-UOM reuse catalog ACL and shared
  customer query/presentation logic. Both active Store and Bot policy apply.
- Cart get/add/update/remove/clear reuse ShopCartFlow cart ownership, product
  entitlement, price, stock, max-lines and pending-order rules. Extract a public
  unit-of-work-safe mutation helper; legacy UI keeps its existing commit/reply.
- Orders list/status reuse verified identity clusters and historical ownership.
- Checkout validation/preparation reuse quote, policy, digital supply and mixed
  checkout validation; preparation returns requirements and no Order/payment.
- Support create extracts and reuses the existing ticket creation primitive.
- Returns/wholesale/admin notification/return eligibility remain truthfully
  unavailable when no complete application contract exists. No payment capture
  or broadcast Action is introduced.

Every adapter declares one side effect. Mutations require idempotency; customer
cart clear requires a request-bound confirmation and expected_cart_revision,
rechecked under the cart lock before consuming the proof. Descriptors can require operator
approval or both; no current operator write is exposed just to exercise approval.

## Transaction and receipts

The application invocation owns commit/rollback on a dedicated caller session.
All local business writes, successful execution receipt and consumed approvals
commit atomically. No adapter commits. Required idempotency is unique by Store,
actor and supplied key, and its request hash additionally binds Bot/platform,
Action version, normalized input and workflow/node references. Identical retries
return a previous safe result; changed input/context conflicts. PostgreSQL insert
uniqueness and row locks serialize concurrent duplicates. Lock timeout/deadlock
errors are bounded retryable outcomes; no blind automatic replay occurs.

Receipts contain only safe actor/context IDs, input hash, side effect, status,
retry count, timestamps, correlation, output-safe replay data and stable errors.
Sensitive output replay is omitted or explicitly redacted rather than retained.
Approval/confirmation rows store hashed opaque tokens, purpose, exact actor/Store/
Bot/action/operation/input digest, expiry and consumed invocation. Issuance is an
internal trusted API with independently verified approver identity; consumption
is atomic and exact idempotent replay precedes single-use checks. A pending receipt
is resumable under the same invocation/key after valid proof; its hash excludes
bearer proofs, timestamps, correlation and retry attempt while binding the exact
business request and workflow/run/node. A locked pending row transitions once. No HTTP route
accepts approved=true or issues customer/operator proofs from admin inspection.

Dry-run performs actual typed input, authorization and object availability checks
without creating any row. Where exact prediction needs a business mutation, the
result explicitly states exact_preview_unavailable. Simulation uses independent
pure deterministic typed adapters, labels every synthetic output and makes no DB
or provider call. Workflow preview imports only these pure contracts/adapters.

## Workflow bindings

Add a typed business Action node to the existing node catalog without changing
existing node meanings. Its configuration references an exact version, bounded
field-to-variable/constant/allowlisted-public-context input mappings and bounded
output-field-to-declared-variable mappings. There is no expression evaluation,
object traversal or secret mapping. Ports cover success/error/retry/pending_approval/
unavailable. Validation checks registry resolution, primitive/reference types,
required inputs, output targets, platform/deprecation and contextual Bot/Store
availability. Structurally incomplete drafts remain editable; invalid bindings
never become ready. All live publishing stays denied until Layer 3.

The existing Simulator replays the same bindings through pure simulation only.
No new Runtime interpreter is introduced.

## Administration UI and API

Studio Action Catalog lists descriptors, filters category/side effect/deprecation,
shows typed schemas and policies and inspects selected same-Store Bot/platform.
Read-only actors can inspect. Safe dry-run is limited to noncustomer Catalog
reads under authenticated staff permissions. No arbitrary customer/actor field
exists. Inspector provides Action selection, typed mappings and named ports.
Use existing bounded Signed HTTP/CSRF/session BFF; explicit allowed paths only.
Catalog, detail, contextual availability, receipt reads and limited dry-run are
protected by existing workflows read permission and Store grants. Receipt reads
are staff manager-only and never expose private bodies. An explicit Store/session rate gate protects inspection/dry-run;
existing middleware request limits apply; schema size/depth is bounded before recursive parsing.

## Observability

Emit bounded safe invocation/status/duration/retry/unavailable/dedup counters and
structured completion logs. Labels contain only registered key/version, platform,
side-effect class, status and stable error; identifiers stay in safe structured
logs. Never label raw input, output, idempotency keys, proof tokens or PII. Tests
assert emitted metrics/log records omit sensitive values.

## Verification and risks

TDD registry/contracts, adversarial inputs, cross-Store/Bot/customer/scope denial,
expiry/replay/changed-input/parallel-idempotency, rollback/output failure, pure
simulation, real service adapters and workflow bindings. Real PostgreSQL checks
prove concurrency and atomicity. Actual Signed HTTP checks verify auth/path/body
boundaries. Browser tests verify Catalog filters/details/context/dry-run and
builder binding save/reload/preview in RTL, mobile and themes. Full Python/Relay/
Next regressions, formatting, typecheck, lint, production build and independent
review complete acceptance. Use isolated Codespace QA with synthetic records and
empty provider credentials; preserve original stack/data. Check GitHub Actions
state and leave workflows disabled. No live Bots/payments/broadcast or deployment.

Main risks: hidden service commits; approval replays; stale identity grants;
receipt hashing scope; type narrowing of mappings; DB isolation on retry; unsafe
error/redaction paths. Every risk has an explicit regression/integration gate.
