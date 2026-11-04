# Visual Workflow Builder Implementation Plan

> Implement inline in this isolated branch with superpowers:executing-plans.
> The supplied implementation brief explicitly requests implementation through
> acceptance, without stopping at the architecture plan. Review major boundaries
> and final changes independently; preserve the existing customer dispatcher.

**Goal:** A persisted, Store-scoped visual workflow editor, simulator and version history.

**Architecture:** Strict portable Python schema and immutable SQLAlchemy revisions;
shared service layer behind the existing signed Admin boundary; controlled React
Flow editor and a deterministic Backend simulator with no business side effects.

**Tech Stack:** Python 3.12+, SQLAlchemy 2, Pydantic 2, FastAPI, Next 16.4.3,
React 19.2, TypeScript, Tailwind 4, React Flow 12, existing PostgreSQL QA.

**Spec:** `docs/superpowers/specs/2026-11-05-workflow-builder-design.md` and the linked complete brief.

## Global constraints

- No live Runtime, provider calls, publishing, MCP server, database reset or new Alembic revision.
- Backend owns Store/Bot/media scope, typed graph validation, revision conflicts and action contracts.
- Preserve current customer menus, checkout, inventory, payment and consent services.
- Canonical definitions, visual layout and simulated session state remain separate.
- Keep Persian RTL/accessibility/themes and existing session/HMAC/CSRF boundaries.
- Use bounded resource limits per document/event replay; no global Bot/Store/Worker count limit.
- PEP 8/257; exact observed acceptance evidence, no inferred PASS.

## Review focus

1. A guessed child revision/media/Bot ID must not leak another Store's content.
2. Two tabs saving the same revision must preserve one winner and the loser's local edits.
3. Unknown network outcomes must reconcile operation IDs before any mutation replay.
4. Type coercion, nested conditions and cycles must not turn simulator inputs into code or infinite work.
5. Incomplete drafts/unavailable actions must remain editable, with no fake publish success.

### Task 1 — Canonical schema, node catalog and validation

Files: `services/shop_workflow_schema.py`, `shop_workflow_catalog.py`,
`shop_workflow_validation.py`, `shop_workflow_conditions.py`,
`shop_platform_capabilities.py`, `tests/test_workflow_schema.py`.

Interfaces: `Definition`, `EditorLayout`, `validate_definition(definition,
platforms) -> ValidationReport`, `node_catalog() -> dict`, typed conditions
and `evaluate_condition(condition, declarations, values) -> bool`.

- [ ] RED: malformed types/unknown fields, Start count, reachability/dangling ports,
  typed operators/references, safe cycles, media/caption/override incompatibilities.
- [ ] Implement strict schema/catalog, deterministic JSON and bounded validation.
- [ ] GREEN; commit the tested schema boundary.

### Task 2 — Persistence, role/Store isolation and signed APIs

Files: `models/shop_workflow.py`, `services/shop_workflows.py`,
`dashboard/shop_workflow_api.py`; extend `db.py`, Store ORM rules,
Admin permission/router registration, and tests in `test_workflow_api.py`.

Interfaces: `create_draft`, `read_workflow`, `save_draft`, `list_revisions`,
`compare_revisions`, `restore_revision`, `duplicate_workflow`, `set_status`,
`operation_result`; require trusted `StoreContext`, actor and operation UUID.

- [ ] RED signed HTTP CRUD, foreign Store/Bot/media denial, current-Store writes,
  read-only role denial, request limits, revision conflict, exact retry and restore.
- [ ] Add immutable revision storage and canonical snapshots, no schema reset.
- [ ] Implement scoped services/API and always-denied activation; GREEN; commit.

### Task 3 — Deterministic simulator and Return Request draft

Files: `services/shop_workflow_simulator.py`, `shop_workflow_templates.py`,
`tests/test_workflow_simulator.py`; connect `/simulate` through Task 2 services.

Interfaces: `simulate(definition, platform, context, events) -> SimulationResult`,
`return_request_template() -> (Definition, EditorLayout)`.

- [ ] RED both platforms: typed input/retries/branches/buttons/history/back/cancel,
  virtual delay, terminal/loop budgets and explicit unavailable action stubs.
- [ ] Add isolated interpreter with no executor imports, transactional purity tests.
- [ ] GREEN; commit.

### Task 4 — Dashboard data boundary and visual editor

Files: `dashboard-next/lib/workflows/{types,state,client}.ts`,
`components/workflows/{editor,canvas,inspector,condition-editor,button-editor}.tsx`,
`app/api/admin/workflows/[...path]/route.ts`, Studio pages, navigation and styles.

Interfaces: controlled editor state serializes `{definition,layout}` only;
`workflowRequest` uses an allowlisted CSRF/session BFF. Catalog drives inspector.

- [ ] RED reducer add/edit/connect/delete, clipboard, undo/redo/layout, deterministic
  serialization and conflict/save reconciliation in existing Node test runner.
- [ ] Add pinned React Flow after official/version compatibility check; implement
  responsive step-list alternative, variable/button/condition editors and canvas.
- [ ] Add autosave/unsaved guard/error/conflict recovery; GREEN/typecheck/lint; commit.

### Task 5 — Simulator, versions and settings screens

Files: `components/workflows/{simulator,versions,settings,list,create}.tsx`,
Studio preview/versions/settings routes; tests for client state and BFF.

- [ ] RED route/CSRF/path allowlist, out-of-order saves and version handling.
- [ ] Integrate conversation replay, active-node highlighting, fixtures/stub labels,
  metadata/assignment, history/compare/restore, duplicate/archive/delete recovery.
- [ ] GREEN; commit.

### Task 6 — Integrated acceptance, review and documentation

Files: `scripts/workflow_studio_e2e.py`, `workflow_studio_browser.mjs`,
`docs/qa/WORKFLOW_STUDIO_PHASE1_ACCEPTANCE.md`, architecture/API reference.

- [ ] Run fresh metadata/real PostgreSQL CRUD and simultaneous-save tests with fakes.
- [ ] Run browser create/connect/save/reload/validate, Telegram+Bale previews,
  revisions/restore, unsupported publish denial, desktop/mobile/themes/keyboard.
- [ ] Check Next MCP routes/React/runtime/compiler; fix failures and rerun affected gates.
- [ ] Run full Python/Relay/Next tests, typecheck/lint/build; independent review.
- [ ] Commit evidence/docs; create Draft PR on the verified base; no merge/deploy.

## Baseline

The unchanged base application was verified in the preceding acceptance cycle:
784 Python, 14 Relay, 48 Next, typecheck/lint/build and actual PostgreSQL/native
fakes passed; final 18-route browser/MCP run exited 0. The new worktree starts
clean at that exact documentation head. Do not repeat unrelated baseline checks
until the feature changes warrant full regression acceptance.
