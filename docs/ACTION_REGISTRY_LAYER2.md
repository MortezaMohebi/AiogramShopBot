# Typed Action Registry — Layer 2

Layer 2 adds a typed, tenant-scoped Backend boundary for reviewed business
capabilities. Workflow definitions can reference these capabilities, validate
their mappings and preview deterministic synthetic results. Customer Workflow
Runtime, customer sessions, messenger routing and MCP are reserved for later
layers.

Base: `feat/bot-experience-workflow-builder` at
`c3c6e79796f864f09df4deb0462cd36f221dbf9e` (Layer 1, Draft PR #15).
Feature: `feat/bot-experience-layer2-action-registry`.

## Registered contracts

Every initial contract is pinned to `1.0.0` and declares both Telegram and Bale.
Availability still depends on the actual Store, Bot, actor and feature policy.
An exact semantic version is the supported version constraint; version ranges
require a future explicit resolution/migration policy.

| Action | Live adapter | Effect | Confirmation |
| --- | --- | --- | --- |
| `catalog.list_categories` | Yes | Read only | None |
| `catalog.search_products` | Yes | Read only | None |
| `catalog.get_product` | Yes | Read only | None |
| `catalog.validate_product_visibility` | Yes | Read only | None |
| `catalog.get_price_uom` | Yes | Read only | None |
| `cart.get` | Yes | Read only | None |
| `cart.add_item` | Yes | Business mutation | None |
| `cart.update_quantity` | Yes | Business mutation | None |
| `cart.remove_item` | Yes | Business mutation | None |
| `cart.clear` | Yes | Business mutation | Customer |
| `order.list_customer_orders` | Yes | Read only | None |
| `order.get_status` | Yes | Read only | None |
| `checkout.validate` | Yes | Read only | None |
| `checkout.prepare` | Yes | Read only | None |
| `support.create_request` | Yes | Business mutation | None |
| `order.list_return_eligible_orders` | Unavailable: return policy absent | Read only | None |
| `returns.create_request` | Unavailable: service incomplete | Business mutation | Customer |
| `wholesale.create_application` | Unavailable: service absent | Business mutation | Customer |
| `notification.notify_admin` | Unavailable: safe service absent | External mutation | None |

An unavailable definition never fabricates live success. These four contracts
remain discoverable for planning and validation; Workflow preview follows the
`unavailable` transition without assigning a successful output. There is no
payment-capture, refund, arbitrary message or Broadcast Action in this registry.

## Application boundary and reuse

`services/shop_actions/contracts.py` defines `ActionDescriptor`, `Invocation`,
`ActionResult`, bounded JSON and redaction. `Registry` registers explicit
`ActionSpec` objects, verifies their model-derived schemas and rejects duplicate,
unknown and unsupported versions. User data never chooses an import, method,
SQL statement, code fragment, shell command or HTTP destination.

`definitions.py`, `schemas.py` and `simulation.py` are pure. The Workflow
validator/Simulator can import them without loading the database or live
adapters. `catalog.py` is the explicit Backend adapter composition root.

| Capability | Reused implementation |
| --- | --- |
| Product/category visibility | `shop_bot_catalog_acl` SQL policy |
| Search | Shared `shop_customer_search.query_products` |
| Price and UoM | Existing Rial/UoM services and owned product resolution |
| Cart | `ShopCartFlow` quote and flush-only mutation primitives |
| Orders | Existing customer identity cluster and owned order records |
| Checkout | Current quote, checkout policy and terms readiness services |
| Support | Shared flush-only ticket/message primitives |
| Staff identity | Existing revocable sessions, central RBAC and StoreContext |

Legacy cart/search/support callers retain their UI/commit responsibilities.
Action adapters only flush; the invocation boundary owns the transaction.
Removing a line from an invalid cart remains possible: the response marks
`quote_available=false`, returns `null` monetary totals and only owned
`unquoted_items` identifiers/quantities. It does not reveal denied names/prices
or claim a checkout-ready quote.

## Trusted identity and permission policy

`customer_principal(db, verified_bot=..., platform_user_id=...)` accepts an
already transport-verified Bot/user pair and resolves an existing customer.
It does not enroll or impersonate customers. `staff_principal` independently
reloads a live revocable staff session and current Store grants. Session
version, expiry, revocation and idle lifetime are checked.

Every invocation refreshes identity, intersects retained/fresh scopes, verifies
required context, Store/Bot/platform ownership and the operational Bot gate.
The operational gate also covers legacy Bots disabled through
`ShopBotOperations`; catalog/cart feature policies add their own restrictions.
Replaying a receipt does not preserve access after identity or Bot revocation.
Order IDs and product IDs grant no ownership by themselves.

## Transactions, idempotency and unknown outcomes

`invoke(db, principal, invocation, registry=...)` requires a **dedicated
session without unrelated pending writes**. Mutating Actions require an
idempotency key. A unique Store/actor/key hash and locked receipt serialize
duplicates; the request hash binds normalized typed input, Action/version,
Store/Bot/platform/actor/customer and optional workflow/revision/run/node.
Proof tokens, correlation IDs and retry timing do not alter this identity.

Exact successful retries return the previous safe result, including when their
delivery-attempt counter exceeds the execution budget. Changed input or operation
under the same key conflicts. Business mutation, proof consumption, output
validation and the safe receipt commit together. Invalid outputs roll back the
business effect. Lost commit acknowledgment returns `pending_external` with
`action_outcome_unknown`; retry the **same** operation to reconcile its receipt.

Initial adapters all use `max_retries=0`; the boundary performs no automatic
retry. Descriptors declare retry codes, backoff, budget, idempotency and adapter
timeout for a future scheduler. Validation, permission, input and approval
failures are not blindly retried. The adapter timeout covers its work/output
validation; database/commit outcomes must retain the receipt reconciliation
semantics above.

PostgreSQL policy serialization uses `FOR NO KEY UPDATE` on the Bot row. It
still conflicts with ACL writers while remaining compatible with the foreign-key
`KEY SHARE` locks of independent receipts. A real concurrent cart regression
reproduced and verified the previous lock-upgrade deadlock.

## Confirmation and approval

Policies are `none`, `customer_confirmation`, `operator_approval` and `both`.
`issue_authorization` is an internal trusted service, absent from HTTP. Its
caller must first obtain the actual customer interaction or operator decision.
An operator needs central `actions.approve`, a live staff session and management
rights for the subject Store. Customer and operator proofs are distinct.

Proofs bind actor, Store, Bot, Action/version, operation, normalized input hash,
purpose, issuer and expiry. Only a token hash is stored. Lifetime is 1–900
seconds (300 by default). All required proofs are locked and validated before
any is consumed. A missing proof produces `pending_approval`; the same operation
can resume with proofs. `cart.clear` also binds the reviewed cart revision.
An `approved=true` field is never authority. There is no approval-minting or
live customer-execution button in the dashboard.

## Dry-run, Simulator and Workflow binding

Dry-run applies real validation, authorization and availability with read-only
preflight functions. It creates no cart, order, customer, proof or receipt.
Where exact preview cannot be produced it returns `skipped` with
`action_exact_preview_unavailable`. Dashboard dry-run is restricted to permitted
Catalog reads and never accepts a customer selector.

Simulation uses deterministic synthetic typed data with the selected platform.
Workflow preview does not call `invoke`, live adapters or external providers.
All emitted preview messages are marked `simulation_only`.

The new `action` node pins Action/version and maps inputs from typed constants,
declared variables or four public context keys: `context.platform`,
`context.customer_name`, `context.store_name`, `context.bot_name`. There is no
path traversal or expression evaluation. Outputs target compatible declared
variables only. Arbitrary strings cannot narrow into date/datetime/enum targets;
literal enum outputs must fit every target choice. Explicit reference mappings
are restricted to their matching ID fields.

All five outcomes must be connected: `success`, `error`, `retry`,
`pending_approval`, `unavailable`. An incomplete binding stays an editable
invalid draft. Validation enriches findings from actual assigned Bot policies;
equivalent finite policy states are grouped in SQL, without truncating Bot lists.
Existing 36 node types keep their meanings; the catalog now has 37 types.

## Signed API and dashboard

All routes below are under `/internal/admin/v1/actions` and require the existing
Signed Bridge, live session, `workflows.read` and appropriate Store access.

| Method/path | Behavior |
| --- | --- |
| `GET /` | Filtered/paged descriptor metadata and contextual availability |
| `GET /bots` | Paged Bot choices from the current Store |
| `GET /{key}/{version}` | Exact descriptor and context |
| `POST /dry-run` | Permitted Catalog read; strict payload and no customer authority |
| `GET /receipts/{invocation_id}` | Redacted current-Store receipt; audit and manager grants |

The Next BFF at `/api/admin/actions/[[...path]]` uses a closed method/path/query
allowlist, current session and same-origin CSRF checks. There is no live
`invoke`, proof issue, arbitrary PATCH/DELETE or generic forwarding route.
`/studio/actions` adds search/category/effect/deprecation filters, policies,
schemas, contextual availability and safe dry-run. The Workflow inspector uses
the same Backend catalog for typed binding forms. Store/permission changes
remount context; old async responses cannot authorize a new selection.

Redis atomically enforces per-minute session+Store / staff / Store limits:
inspection **120/240/600**, dry-run **15/30/60**. Redis failure closes the gate.
Invocation JSON is bounded to 64 KiB, depth 8 and 5,000 items; schemas impose
field-specific limits as well. Query duplicates/unknown authority fields fail.

## Storage and observability

Additive tables `shop_action_executions` and `shop_action_authorizations` are
imported by the ORM metadata. The isolated fresh PostgreSQL schema was built
through the existing bootstrap. No legacy data migration or reset is required
for this beta; no production migration/deployment was performed.

Receipts contain operation/trace IDs, Store/Bot/actor references, hashes,
status/effect/timing/retries/correlation and a validated redacted summary. Raw
idempotency/proof tokens and private support bodies are not stored in receipts.
Structured completion logs omit request bodies/credentials. Process-local
bounded descriptor labels provide counts, durations, retries, statuses and
deduplication; `observability.snapshot()` is available for a future monitoring
exporter. Multi-process aggregation and retention/cleanup policy remain
deployment concerns.

## Contracts for Layer 3 and boundaries

Layer 3 should create principals only after authenticating the real messenger
transport, pin immutable workflow revisions, resolve typed inputs, call `invoke`
with a dedicated session, persist the same invocation/key across recovery,
honor pending/unknown results and feed only validated outputs to variables.
It must obtain real customer/operator decisions before proof issuance and honor
retry/backoff/idempotency policy. External mutation requires a reviewed durable
outbox/reconciliation adapter before being made available.

Layer 4 can reuse the same registry/validation/application services; it gains no
permission from natural-language requests or supplied scope claims. This phase
does not start either layer, activate customer routing, collect payments, send
real messages, run Broadcast, merge or deploy.

See [the acceptance report](qa/ACTION_REGISTRY_LAYER2_ACCEPTANCE.md) for exact
commands, evidence, fixes and outstanding gates.
