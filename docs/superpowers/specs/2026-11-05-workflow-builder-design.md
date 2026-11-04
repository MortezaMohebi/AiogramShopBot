# Bot Experience Studio — Layer 1 design

The supplied [implementation brief](../../planning/BOT_EXPERIENCE_STUDIO_PHASE1_BRIEF.md)
authorizes implementation, integration and the test/fix/retest loop. This design
records implementation choices within that scope. It does not authorize live
workflow activation, a production Runtime, an MCP server or provider calls.

## Audit and boundaries

- Base: PR #14 head `f423a7489c8cc0659ece37d1320026770668696a`.
- Isolated branch: `feat/bot-experience-workflow-builder`.
- `dashboard-next/package.json`: Next 16.4.3, React 19.2, TypeScript, Tailwind 4,
  existing semantic light/dark tokens and self-hosted Vazirmatn.
- `dashboard-next/lib/bridge.ts`, `dashboard/admin_control_app.py` and
  `services/shop_store_context.py`: revocable signed sessions, exact request
  HMAC and current-Store writes/active-Store reads. Reuse these boundaries.
- `models/shop_multibot.py`: Store owns many registered Bots, independent of
  Worker topology. No new global Store/Bot/Worker count restriction.
- Existing menus/FSM and commerce services are not a general graph engine.
  They remain the customer-facing behavior. Studio adds no dispatch hook.
- `db.py` explicitly imports metadata; tests discover shared shop models.
  New tables use SQLAlchemy metadata, with no Alembic revision or reset.

## Approach

Use React Flow (`@xyflow/react`) as the controlled visual canvas, with a
portable Python-owned schema. A bespoke canvas would duplicate keyboard,
selection and connection behavior. Persisting React Flow JSON would bind the
business definition to a renderer. Neither alternative fits the brief.
The library supplies drawing; Backend services own definitions, validation,
versions and the isolated simulator. These are implementation choices, not
additional requirements attributed to the user.

## Storage and service contracts

`ShopWorkflow` owns identity, Store, key, metadata, draft/archive/delete state
and current revision. `ShopWorkflowRevision` is append-only and stores a
canonical definition plus separate layout, actor, operation ID and SHA-256.
Every mutation creates a new immutable revision. Rename/archive/delete are
auditable; restoring a prior definition creates a new draft revision.

Canonical definition includes schema version, assignment (`selected` or
`all_eligible`), target platforms, entry points, typed variables, nodes, edges,
error/timeout policies and bounded explicit loop policies. Positions/viewport
belong only to layout. Session state is never persisted in a definition.
No arbitrary code, expressions, URLs containing provider tokens or executable
scripts are accepted. Node configurations use strict allowlisted typed models.

Updates use expected revision plus an operation UUID. Exact retries resolve
to the recorded revision; reused operation IDs with different payloads fail.
The UI reconciles uncertain saves through the recorded operation, preserving
local changes on conflicts. A 256 KiB signed request budget is retained.
Graph/input resource budgets protect the interpreter, not platform capacity.

`workflows.read` is available to authenticated staff with Store read access;
`workflows.write` belongs to content/superadmin plus current-Store editor
membership. Reads and child revisions include explicit Store predicates.
Workflow and revision models also join existing ORM Store record rules.
Bot assignments are checked against the same owning Store; no client Store
header can grant ownership. Definitions expose no credentials.

APIs under `/internal/admin/v1/workflows` provide list/create/read/update,
archive/delete/duplicate, catalog, bot/media choices, validate, simulate,
revisions, comparison, restore and operation reconciliation. The Next BFF
accepts only those allowlisted routes, uses existing session/CSRF protections
and signs requests. Shared Python services are the future MCP entry point.

## Validation, capabilities and actions

Structural validation rejects malformed/unknown types and unsafe values.
Drafts may contain incomplete graphs; semantic findings identify missing
Start/terminal paths, duplicates, dangling/unreachable nodes, invalid ports,
variables/conditions and uncontrolled cycles. The catalog supplies field
schemas, defaults, conditional fields and action-contract availability.

Platform contracts distinguish official limits from current adapter limits.
Both support 4096-character text and 64-byte callbacks. Telegram captions are
1024; Bale documents 4096 but the existing adapter truncates at 1024, so
Studio flags the adapter constraint. Both official APIs describe media groups;
the current shared adapters lack that executor and it is marked unavailable.
Media references use Store-owned ProductMedia identities, never hard-coded
provider URLs. Each target platform is validated, including typed overrides.

Commerce node contracts name existing services; business-process nodes without
services carry an explicit unavailable contract. Every action is simulator-only
in Layer 1. Activation always returns `workflow_runtime_unavailable`; no status
toggle impersonates publishing. Callback configuration stores stable keys and
targets, never sensitive state; the future Runtime must mint opaque scoped
server-resolved capabilities and recheck Backend authorization.

## Editor and simulator

Reading order: Studio navigation, heading/actions/save state; searchable node
palette; canvas; selected node properties; validation panel. Canvas is LTR for
technical geometry; Persian labels/forms remain RTL. Semantic tokens cover
both themes. Mobile/tablet offer a step list, properties and explicit connection
controls, with optional canvas, rather than compressing four columns.

Support drag/drop and keyboard add; connection validation; zoom/pan/minimap;
selection/copy/paste/delete; bounded undo/redo; align/automatic layout; typed
variables, safe conditions and dynamic button rows; autosave, unsaved navigation
guard, loading/error/conflict states and version compare/restore. Inspector
forms consume the catalog schema rather than per-workflow hard-coded forms.

The Backend simulator replays bounded input/button/back/cancel events against
an immutable draft revision. It uses simulated context and virtual time only;
it never imports or invokes a provider/payment/inventory mutation executor.
Commerce and unavailable actions show labeled fixtures/stubs. History includes
active node, messages, variable changes, retries and terminal/error state.
The preview selects an eligible Store-owned Bot and platform. Successful
simulation is explicitly not production Runtime acceptance.

A nonpublished Return Request template demonstrates simulated orders/products,
reason branching, optional description/photo, summary/confirm, back/cancel and
the unavailable return action. It creates no real return/customer record.

## Verification and non-goals

Python tests cover schema, operators/cycles, simulator purity, CRUD, signed HTTP,
Store/Bot/media ownership, permissions, idempotency, optimistic races, immutable
versions and restoration. Node tests cover reducer/history/layout/connections,
serialization and save reconciliation. Runtime E2E covers create/edit/connect,
save/reload/autosave/conflict, both platform previews, revision compare/restore,
mobile/keyboard/themes and publish denial. Run full existing suites, lint,
typecheck and production build; use actual PostgreSQL and Next MCP/browser
where configured. Record exact PASS/FAIL/BLOCKED, never infer execution.

No live dispatcher replacement, Action Registry executor, production Runtime,
MCP transport, live provider activation, GitHub Actions enablement or data reset.
