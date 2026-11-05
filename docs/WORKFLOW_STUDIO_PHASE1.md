# Bot Experience Studio — Phase 1

The Studio stores and previews customer conversation definitions. It does not
register routes in the Telegram/Bale dispatcher, change customer menus, execute
business actions, publish workflows, or expose an MCP server.

## Dashboard

Open **Bot Experience Studio** in the administration sidebar.

| Screen | Behavior |
| --- | --- |
| `/studio/workflows` | Search, status filters and paginated Store-scoped records |
| `/studio/workflows/new` | Create a blank draft or the nonpublished Return Request sample; copy an owned source with `?source=UUID` |
| `/studio/workflows/UUID` | Catalog palette, desktop canvas, accessible step list, schema-driven inspector, validation and confirmed saves |
| `…/preview` | Select an eligible same-Store Bot and platform; replay synthetic customer events against one saved revision |
| `…/versions` | Inspect immutable snapshots, compare domain/layout changes, restore as a new draft revision |
| `…/settings` | Metadata, platform/Bot assignment, entry points, typed variables, error/timeout policies and lifecycle actions |

A desktop canvas supports pan/zoom/fit/minimap, snapping, connections,
multiselection, copy/paste, undo/redo, deletion, alignment and automatic layout.
On smaller screens, select a step and configure its outgoing destinations in the
inspector. The canvas remains an optional view. Copy/paste uses a snapshot,
including internal transitions, and remaps copied node IDs.

Message text supports `{{variable_name}}` and the public presentation context:
`context.platform`, `context.customer_name`, `context.store_name`,
`context.bot_name`. These are typed substitutions, not expressions. Conditions
use allowlisted operators and bounded AND/OR groups; no code or `eval` is accepted.

### Save and recovery

Each mutation carries an operation UUID and an explicit expected revision. A
successful response confirms an immutable snapshot; a newer local edit is kept
when an earlier save returns. A different stale operation receives HTTP 409.

If a connection fails, the dashboard retains the exact pending request. Use
**بررسی رسید ذخیره** to read its operation receipt. **تکرار همان عملیات** replays
only that same operation ID and payload. A historic receipt never silently
adopts a newer server head as the local save base. Export the local JSON before
loading a conflicting remote version. Undo keeps the previous local document.

Dirty drafts and unknown operations guard anchor, browser history and Store
context navigation. Browser reload/close uses its native unsaved-change prompt.
These are transient browser safeguards; the database remains the source of truth.

## Portable model

`Definition` in `services/shop_workflow_schema.py` contains:

- `schema_version`, target platforms and same-Store Bot assignment;
- entry points, typed nodes, named edges and variable declarations;
- bounded error/timeout policies.

`EditorLayout` separately contains node coordinates and camera geometry.
React Flow node objects, dimensions, handles, selection, undo history, customer
sessions and preview values are never persisted in `Definition`.

The catalog in `shop_workflow_catalog.py` owns all 36 initial node types, config
schemas, defaults, form descriptors, port names and action-contract metadata.
Platform overrides are partial copy/media overrides. Topology, variables,
buttons, conditions and action bindings remain shared across platforms.

| Family | Initial node types |
| --- | --- |
| Control | `start`, `end`, `cancel`, `condition`, `switch`, `wait_for_input`, `delay`, `go_to_step` |
| Messages | `send_text`, `send_photo`, `send_video`, `send_document`, `send_media_group` |
| Interaction | `show_buttons`, `confirm`, `ask_text`, `ask_number`, `ask_phone`, `ask_email`, `ask_photo`, `ask_document`, `ask_choice` |
| Commerce | `show_categories`, `show_products`, `show_product_details`, `select_product`, `select_quantity`, `add_to_cart`, `view_cart`, `start_checkout`, `show_order_status` |
| Requests | `create_support_request`, `create_return_request`, `request_admin_approval`, `notify_admin`, `request_wholesale_access` |

All of these are draft/simulation nodes in this phase. Commerce/request results
are explicitly synthetic; unavailable executors and media adapters remain visible
as capability findings rather than working live actions.

Validation reports structural/semantic graph errors separately from unavailable
future executors. Incomplete drafts are editable and can be saved; invalid raw
shapes, secrets and foreign Store/Bot/media references are rejected. Simulation
requires a semantically valid graph. All live activation remains unavailable.

Per-document limits bound request/replay work: 200 nodes, 800 edges, 100 variables,
500 interpreted steps, 100 supplied events and a 256 KiB signed request ceiling.
The normalized graph/layout is bounded below that ceiling. These limits do not
cap the number of registered Bots, Stores or Workers. Choice APIs are paginated.

## Server boundary

The existing Signed Bridge, revocable staff session and effective `StoreContext`
protect `/internal/admin/v1/workflows`. Every child revision/receipt is read
through its owning parent and Store. Writes require `workflows.write`, an editor
or manager membership, and the owning current Store; read-only staff can validate
and simulate. The dashboard BFF accepts only an explicit route/query allowlist,
checks same-origin CSRF and counts actual streamed bytes. The shared challenge endpoint binds authenticated CSRF to the verified signed
session, so another dashboard tab does not invalidate an in-flight request.
Workflow Web Locks additionally serialize its own challenge/dispatch sequence.

| Method and relative path | Contract |
| --- | --- |
| `GET /workflows` | Filter/search/page visible records |
| `POST /workflows` | Client-generated identity, operation ID, metadata and template |
| `GET/PATCH/DELETE /workflows/UUID` | Read, compare-and-swap save, soft delete |
| `GET /workflows/catalog`, `/bots`, `/media` | Typed descriptors and paged same-Store choices |
| `POST /workflows/UUID/validate` | Saved or supplied definition, no mutation |
| `POST /workflows/UUID/simulate` | Pinned revision, Bot, platform, synthetic context and replay events |
| `GET /workflows/UUID/revisions[/N]` | Immutable metadata or snapshot |
| `GET /workflows/UUID/compare?left=N&right=N` | Domain and layout differences |
| `GET /workflows/UUID/operations/UUID` | Scoped reconciliation receipt |
| `POST /workflows/UUID/duplicate` | Distinct same-Store identity; receipt binds the source |
| `POST /workflows/UUID/archive`, `/restore` | Lifecycle CAS; restore appends a new draft |
| `POST /workflows/UUID/publish` | Always HTTP 409 `workflow_runtime_unavailable` |

The executable request contracts are
[`shop_workflow_requests.py`](../services/shop_workflow_requests.py); shared
response interfaces are in
[`types.ts`](../dashboard-next/lib/workflows/types.ts). In particular, creation
uses `id`, `operation_id`, `key`, `name`, `description` and `template`; saving uses
`operation_id`, `expected_revision`, metadata, `definition` and `layout`; restoring
uses `operation_id`, `expected_revision` and the source `revision`. Simulation
uses a pinned `revision`, owned `bot_id`, `platform`, synthetic `context` and
bounded `events`.

Malformed typed requests return 422; an incomplete but well-shaped graph is saved
with validation findings. Reads outside visible Stores return 404, unauthorized
roles return 403, wrong-current-Store or revision conflicts return 409, and the
streamed body limit returns 413. None of these failures authorizes an automatic
mutation retry with a new operation ID.

`ShopWorkflow` stores the head; `ShopWorkflowRevision` stores append-only canonical
snapshots and integrity/request hashes. Successful mutations append the revision
and existing admin audit event in the same SQL transaction. Exact concurrent
retries reconcile after rollback, explicitly refreshing expired ORM identities.
Archive/delete preserve history and do not require obsolete Bot/media references
to remain usable. Saving/restoring/simulating still enforce live owner bindings.

Public shared services and strict request models are the intended boundary for a
future authenticated MCP adapter. Such an adapter must construct a trusted actor
and StoreContext server-side, call these same services and honor operation IDs.
It must not implement independent validation, SQL access or business executors.

## Simulation and platform capability

The interpreter replays in memory. Back restores a prior checkpoint, cancellation
terminates the preview, and Tick advances virtual time without sleeping or
scheduling. Customer data, orders/products, file metadata and action results are
explicitly synthetic. Preview never creates an order/cart/payment/ticket/return
or imports a business executor. Choice and numeric/text bounds are checked before
simulation; rendered messages and traversal are bounded.

The Return Request sample demonstrates order/product choices, reason, optional
text/photo, a conditional photo branch, summary, confirmation and an explicitly
unavailable return-action stub. It creates no return request.

`shop_platform_capabilities.py` separates official support from current adapter
support. Sources reviewed for this phase: [Telegram Bot API](https://core.telegram.org/bots/api)
and [Bale Bot API](https://docs.bale.ai/). In particular, Bale's official caption
limit differs from the current adapter's 1024-character behavior. Media groups
are documented API capabilities but lack a current adapter executor; the editor
uses a conservative ten-item document limit, without claiming Bale documents
that official count ceiling. Runtime availability is always reported separately.

## Isolated QA

Use a separate checkout and `compose.workflow-qa.yml`; it has independent
PostgreSQL/Redis/assets volumes, loopback API port 8092 and explicit Workflow QA
mode. Never point these runners at a deployment database or populate providers.

```bash
python3 -m scripts.beta_qa_environment
docker compose -f compose.workflow-qa.yml up -d api
# Wait for /healthz on 127.0.0.1:8092 before running HTTP acceptance.
docker compose -f compose.workflow-qa.yml exec -T api \
  python -m scripts.beta_storefront_e2e --stage seed
docker compose -f compose.workflow-qa.yml exec -T api \
  python -m scripts.workflow_studio_e2e
bash scripts/beta_storefront_acceptance.sh
```

The QA environment generator defaults its Next bridge to port 8091 for older
Beta runs. Set `SHOP_FASTAPI_INTERNAL_URL=http://127.0.0.1:8092` for this separate
Next dev instance on port 3002. Keep private environment files out of Git.

The PostgreSQL runner uses real separate AsyncSessions and a two-writer barrier;
its scoped signed HTTP session is revoked in `finally`. The browser runner uses
an isolated Playwright context, normal password/MFA authentication, synthetic
fixtures and the running Next MCP endpoint. Playwright 1.64.1 is a QA-only tool;
it adds no dashboard runtime dependency. Install it in an isolated tools prefix:

```bash
npm --prefix /tmp/workflow-qa-browser install --save-exact playwright@1.64.1
PLAYWRIGHT_BROWSERS_PATH=/tmp/workflow-qa-browsers \
  /tmp/workflow-qa-browser/node_modules/.bin/playwright install chromium
PLAYWRIGHT_BROWSERS_PATH=/tmp/workflow-qa-browsers \
WORKFLOW_PLAYWRIGHT_MODULE=/tmp/workflow-qa-browser/node_modules/playwright-core/index.mjs \
WORKFLOW_BROWSER_STAGE=all node scripts/workflow_studio_browser.mjs
```

The browser permits requests only to the isolated localhost Next origin. Network
recovery tests abort a save; they never fabricate a successful save response.
See the acceptance report for the exact commands, observed results, limitations
and reviewed source head.
