# Layer 2 implementation plan

Design: ../specs/2026-11-05-action-registry-design.md.
Requirement: ../../planning/BOT_EXPERIENCE_LAYER2_BRIEF.md.
Execution: native implementation, test/debug/fix/retest; independent review.

## 1. Descriptor, registry and pure schemas (20–30%)
Files: services/shop_actions/{contracts,registry,simulation}.py; tests/test_action_contracts.py.
Interfaces: ActionDescriptor, Invocation, ActionResult, Registry.register/resolve/catalog.
- [x] RED duplicate/unknown/version/deprecation, strict descriptor, bounded nested input,
  validation/output filtering/redaction, safe error and deterministic simulation tests.
- [x] Implement explicit allowlist and complete versioned descriptors/policies.
- [x] GREEN contracts and pure simulation; commit.

## 2. Trusted invocation, ownership and availability (40%)
Files: services/shop_actions/context.py, policies.py; tests/test_action_security.py.
Interfaces: customer_principal(db, verified_bot, platform_user_id), staff_principal(db,scope,actor,bot_id), availability.
- [x] RED cross-Store/Bot/customer, disabled/revoked/blocked identity and missing scope.
- [x] Reload trusted Bot/actor/customer bindings and feature policies; no request scope claims.
- [x] GREEN; commit.

## 3. Atomic receipts, approval and invocation service (50–60%)
Files: models/shop_action.py; services/shop_actions/execution.py, approvals.py.
Interfaces: invoke(db,principal,Invocation), issue_authorization(...), receipt_view(...).
- [x] RED changed-input key reuse, exact replay, concurrent duplicate, rollback,
  token purpose/input/expiry/actor/single-use and safe persisted summaries.
- [x] Add additive models to current ORM imports; implement atomic claim/execute/receipt.
- [x] Enforce timeout/retry/transaction policies; never auto-retry unsafe errors.
- [x] Resume pending approvals with the same operation; proofs/timing excluded from request hash.
- [x] Emit bounded safe status/duration/retry/unavailable/dedup metrics and redacted logs; test emissions.
- [x] Separate dry-run and deterministic simulation; GREEN; commit.

## 4. Reuse commerce adapters (70%)
Files: services/shop_actions/adapters.py; services/shop_cart.py,
shop_customer_search.py, shop_customer_support.py; tests/test_action_adapters.py.
- [x] RED real ACL search, price/UOM, cart quantity/read/remove/clear, order ownership,
  checkout missing requirements, support create and missing-service availability.
- [x] Extract minimal UoW-safe cart/support primitives shared with legacy callers.
- [x] Register initial typed Actions; missing services remain explicitly unavailable.
- [x] GREEN adapters and legacy regressions; commit.

## 5. Workflow bindings and safe Simulator (80%)
Files: services/shop_action_bindings.py; workflow schema/catalog/validation/simulator;
tests/test_workflow_action_bindings.py; dashboard-next/lib/workflows/types.ts.
- [x] RED unknown Actions, wrong versions/types/variables, context traversal, unavailable
  platform, missing transitions and pure fake preview typed results.
- [x] Add one catalog-driven Action node with exact versions and typed field mapping.
- [x] Integrate validation/context availability and pure simulation only; GREEN; commit.

## 6. Catalog API, dashboard and inspector (85%)
Files: dashboard/shop_action_api.py; app router include; dashboard-next/lib/actions;
components/actions; studio/actions page; action BFF and inspector.
- [x] RED actual signed HTTP scope/receipt/dry-run/path/body checks and Node client tests.
- [x] Add safe paged catalog/detail/context and limited noncustomer dry-run; no live execute.
- [x] Build RTL/theme/responsive catalog, filters, detail/policies, availability and mappings.
- [x] GREEN frontend, typecheck/lint; commit.

## 7. Integrated acceptance, review and docs (90–100%)
Files: scripts/action_registry_e2e.py, action_registry_browser.mjs;
docs/ACTION_REGISTRY_LAYER2.md, docs/qa/ACTION_REGISTRY_LAYER2_ACCEPTANCE.md.
- [x] Real PostgreSQL concurrent dedup and rollback/approval checks.
- [x] Real signed HTTP and browser catalog/filters/detail/dry-run/binding roundtrip.
- [x] Existing Bot journeys and Layer 1 safe Simulator remain operational with fakes.
- [x] Full Python, Relay, Next tests; format/typecheck/lint/build in Codespace.
- [x] Final independent code/security review and fixes/retest.
- [ ] Verify GitHub Actions disabled, publish evidence/docs, clean tracked tree and Draft PR.

Verification: 968 Python, 99 Next, 14 Relay, 11 Action PostgreSQL, 4 Workflow
PostgreSQL, 35 browser checks/64 layout combinations; build PASS. Evidence/docs
are published with the branch. Progress remains 85% under the blocker rule:
the saved repository Actions setting is enabled, and automatic approval review
rejected saving Disabled without more explicit user permission. No workaround or
PR-triggered workflow is attempted. Prepared Draft PR base is the Layer 1 branch.

## Review focus

- Pending duplicate transaction must wait for winner without expiring trusted principal.
- Sensitive output validation failure must roll back business writes and consumed proof.
- Exact replay must still revalidate live Store/Bot/customer access.
- Preview must not call a production adapter or create an Action receipt.
- Catalog dry-run must not create, select or impersonate a customer.
