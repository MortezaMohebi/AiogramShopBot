# IMPLEMENTATION PROMPT
# Bot Experience Studio — Layer 2
# Typed Action Registry and Safe Execution Layer

## Role

Act as a Senior Software Architect, Backend Engineer, Security Engineer,
Workflow-System Designer, Next.js Engineer, and Telegram/Bale Commerce
Platform Engineer.

You are working inside the existing `AiogramShopBot` repository.

Your task is to inspect the current implementation and fully implement
Layer 2 of Bot Experience Studio:

1. Typed Action Registry
2. Safe Action Invocation Contracts
3. Action Permission and Tenant Policies
4. Side-Effect Classification
5. Idempotency and Execution Receipts
6. Dry-Run and Simulation Adapters
7. Approval Policy Contracts
8. Workflow Node → Action Binding
9. Action Catalog in the Next.js dashboard
10. Contracts required by the future Workflow Runtime and MCP Server

This must be a real, tested, production-quality implementation.

Do not stop after architecture, models, schemas, or frontend mockups.

Proceed through:

Inspect → Design → Implement → Test → Debug → Fix → Retest → Verify

until the complete Layer 2 acceptance gate passes.

---

# 1. Mandatory Progress Reporting Protocol

You MUST report Layer 2 progress throughout execution.

Progress is milestone-based, not time-based.

Never invent progress percentages based on effort, elapsed time, or number of
files modified.

Only increase progress when the corresponding milestone has genuinely been
completed and verified.

Use this exact format between major implementation steps:

LAYER 2 PROGRESS: XX%
Completed:
- ...
Currently working on:
- ...
Remaining critical work:
- ...
Current blockers:
- None / ...

If a blocker exists, keep the percentage unchanged until the blocker is
resolved.

Do not report 100% until:

- All mandatory Layer 2 features exist.
- Relevant unit tests pass.
- Integration tests pass.
- Frontend tests pass.
- Security tests pass.
- Type checking passes.
- Linting passes.
- Production build passes.
- No unintended regression is found.
- Existing Telegram/Bale behavior remains operational.
- GitHub Actions remain disabled.
- Final diff has been reviewed.
- Working tree is clean after the final commit.

## Layer 2 Progress Milestones

0%:
- Phase started.

5%:
- Repository, branch, Layer 1, Backend services, BotContext, permissions,
  database, frontend, and tests inspected.

10%:
- Layer 2 architecture and reuse plan finalized.
- Existing business services mapped to candidate Actions.

20%:
- Canonical Action Descriptor and Action Registry implemented.

30%:
- Invocation Context, Result Contract, stable errors, availability model,
  and side-effect classification implemented.

40%:
- Permission, tenant isolation, Store/Bot/customer ownership enforcement
  implemented.

50%:
- Idempotency, execution receipts, transaction policies, retries, and
  timeout policies implemented.

60%:
- Dry-run, simulation adapters, confirmation policies, and approval
  contracts implemented.

70%:
- Initial Catalog, Cart, Order, Checkout, and supported business Actions
  integrated with real Backend services.

80%:
- Layer 1 workflow action binding and action availability validation
  integrated.

85%:
- Next.js Action Catalog and safe contextual inspection UI implemented.

90%:
- Focused unit/integration/frontend/security tests passing.

95%:
- Relevant regression tests, type checking, linting, and production build
  passing.

100%:
- Definition of Done verified.
- Final diff reviewed.
- Documentation updated.
- Final commit created.
- Working tree clean.

You may emit intermediate values such as 23% or 67% only when backed by
completed sub-items inside the current weighted milestone.

---

# 2. Prerequisites

Layer 1 should already provide:

- Canonical Workflow Definition
- Workflow persistence
- Immutable workflow revisions
- Visual Workflow Builder
- Typed variables
- Safe conditions
- Workflow validation
- Platform capability validation
- Side-effect-free workflow simulator
- Node Registry
- Draft/invalid/ready/archive lifecycle

Before coding, verify the real Layer 1 implementation.

Do not assume functionality exists merely because documentation says it does.

If Layer 1 has a direct blocker:

- Fix only the smallest compatible gap.
- Add a regression test.
- Document the compatibility fix.
- Do not redesign Layer 1.

---

# 3. Project Context

The platform supports:

- Multiple Stores
- Multiple Telegram bots
- Multiple Bale bots
- Multiple Cloudflare Workers
- Bot Registry
- Secret Management
- BotContext
- Per-bot product access
- Per-bot category access
- Catalog
- Product media
- UOM-aware products
- Cart
- Checkout
- Orders
- Customers
- Wallet/payment configuration
- Broadcast
- Next.js administration dashboard
- Shared Backend application/domain services

Important architectural rules:

- A Worker may serve multiple Bots.
- Actions belong to Backend capabilities, not Workers.
- Actions must reuse existing business services.
- Actions must not bypass Store/Bot access restrictions.
- Telegram and Bale must not be assumed to have feature parity.
- No legacy production-data migration is needed.
- Schema migrations required by Layer 2 are allowed.
- GitHub Actions must remain disabled.

---

# 4. Initial Investigation

Before implementation:

1. Inspect Git status and current branch.
2. Identify the correct completed Layer 1 base.
3. Inspect Layer 1 schemas, services, APIs, simulator, and tests.
4. Inspect existing Backend application/domain services.
5. Inspect Store and Bot models.
6. Inspect BotContext.
7. Inspect Product/Category access logic.
8. Inspect Cart and Checkout.
9. Inspect Orders and Customers.
10. Inspect Media.
11. Inspect Wallet/payment implementations.
12. Inspect Broadcast.
13. Inspect tenant isolation and RBAC.
14. Inspect transaction patterns.
15. Inspect existing idempotency patterns.
16. Inspect logging/audit infrastructure.
17. Inspect Telegram and Bale adapters.
18. Inspect Codespaces and test commands.
19. Inspect installed engineering skills.

Search for existing:

- Command buses
- Service registries
- Job registries
- Event buses
- Action abstractions
- Idempotency utilities
- Audit utilities

before introducing new abstractions.

After investigation emit:

LAYER 2 PROGRESS: 5%

with the findings.

---

# 5. Git Rules

Create:

`feat/bot-experience-layer2-action-registry`

Base it on the correct completed Layer 1 commit or development branch.

Do not:

- Discard unrelated changes
- Enable GitHub Actions
- Force-push unrelated history
- Replace working business logic unnecessarily

Keep commits logically organized.

---

# 6. Strict Layer Boundaries

Layer 1 defines:

- Workflow nodes
- Edges
- Variables
- Conditions
- Visual definition
- Validation

Layer 2 defines:

- Business Actions
- Action schemas
- Permission rules
- Side-effect rules
- Confirmation requirements
- Approval requirements
- Idempotency
- Dry-run
- Simulation
- Execution receipts

Layer 3 will define:

- Workflow Runs
- Customer session state
- Event routing
- Telegram/Bale Runtime execution

Layer 4 will define:

- MCP tools/resources/prompts
- AI-assisted workflow editing
- Change Sets
- Approval-aware publication

Do not put Runtime session state into Layer 2.

Do not implement MCP in Layer 2.

---

# 7. Typed Action Descriptor

Create a canonical versioned Action Descriptor.

Each Action must define:

- Stable action key
- Action version
- Display name
- Description
- Category
- Input schema
- Output schema
- Stable error schema
- Required context
- Allowed actor types
- Required permissions/scopes
- Side-effect classification
- Idempotency policy
- Retry policy
- Timeout policy
- Customer confirmation policy
- Operator approval policy
- Supported platforms
- Store availability policy
- Bot availability policy
- Simulator strategy
- Dry-run support
- Sensitive input fields
- Sensitive output fields
- Audit policy
- Deprecation status
- Replacement Action when deprecated

Suggested stable keys include:

- catalog.list_categories
- catalog.search_products
- catalog.get_product
- catalog.validate_product_visibility

- cart.get
- cart.add_item
- cart.update_quantity
- cart.remove_item
- cart.clear

- order.list_customer_orders
- order.get_status
- order.list_return_eligible_orders

- checkout.validate
- checkout.prepare

- support.create_request
- returns.create_request
- wholesale.create_application
- notification.notify_admin

Public Action keys must not depend on Python class names or internal method names.

They must remain stable across refactors.

---

# 8. Central Action Registry

Implement one central allowlisted registry.

It must:

- Reject duplicate Action key/version combinations.
- Validate descriptors.
- Resolve Actions explicitly.
- Support versioning.
- Support deprecation.
- Expose safe metadata.
- Check contextual availability.
- Reject unknown Actions.
- Prevent arbitrary imports.
- Prevent arbitrary getattr invocation.
- Prevent arbitrary service/method names.

Every executable Action must have an explicit adapter.

Never expose generic Actions such as:

- execute_python
- execute_javascript
- execute_command
- run_sql
- call_url
- invoke_service
- call_method
- call_backend_method

After registry implementation and tests emit approximately:

LAYER 2 PROGRESS: 20%

---

# 9. Action Invocation Context

Create a typed Action Invocation envelope containing where applicable:

- Invocation ID
- Action key
- Action version
- Store ID
- Bot ID
- Platform
- Customer ID
- Administrator ID
- Workflow ID
- Workflow revision/version
- Workflow Run ID
- Node ID
- Correlation ID
- Request ID
- Locale
- Timezone
- Input payload
- Idempotency key
- Dry-run flag
- Simulation flag
- Approval receipt
- Customer-confirmation receipt
- Timestamp

Trusted fields must be constructed or independently verified by Backend.

Never trust workflow/dashboard/future-MCP input as authoritative for:

- Store identity
- Bot ownership
- Customer ownership
- Administrator permissions
- Approval state
- Platform identity
- Secret references

---

# 10. Action Result Contract

Use one consistent typed envelope.

Support statuses equivalent to:

- succeeded
- failed
- retryable
- pending_approval
- pending_external
- skipped
- unavailable

Include:

- Typed output
- Stable error code
- Safe error message
- Retryability
- Retry-after information
- Execution receipt
- Side-effect receipt
- Correlation ID
- Timing metadata
- Redacted audit metadata

Never expose:

- Stack traces
- Database internals
- Tokens
- Credentials
- Payment secrets

---

# 11. Side-Effect Classification

Every Action declares exactly one:

- none
- read_only
- reversible
- business_mutation
- external_mutation
- irreversible

Examples:

Product search:
read_only

Add to cart:
business_mutation

Create support request:
business_mutation

Notify administrator:
external_mutation

Capture payment:
irreversible

Do not automatically expose payment capture merely to complete this phase.

After contracts and side-effect system are complete emit approximately:

LAYER 2 PROGRESS: 30%

---

# 12. Permission and Tenant Enforcement

Enforce server-side:

- Store isolation
- Bot ownership
- Customer ownership
- Role permissions
- Action-specific scopes
- Product access
- Category access
- Platform availability
- Bot enabled state
- Feature configuration

Frontend hiding is not authorization.

Prevent:

- Cross-Store invocation
- Cross-Bot invocation
- Cross-customer order access
- User-controlled permission context
- Secret access
- Arbitrary Action resolution

After the permission test suite passes emit:

LAYER 2 PROGRESS: 40%

---

# 13. Idempotency and Execution Receipts

Each mutating Action declares:

- not_applicable
- recommended
- required

For required idempotency:

- Persist idempotency key.
- Bind it to Store, actor, Action key/version, and normalized input hash.
- Reject same key with different input.
- Prevent concurrent duplicate side effects.
- Return previous safe result when appropriate.

Create Action Execution Receipt containing:

- Invocation ID
- Action key/version
- Store
- Bot when relevant
- Safe actor reference
- Workflow/run/node references
- Idempotency key
- Input hash
- Status
- Side-effect class
- Start/end timestamps
- Retry count
- Correlation ID
- Redacted result summary
- Stable error code

Do not persist sensitive raw values unnecessarily.

---

# 14. Transaction and Retry Policies

Each Action declares:

- Transaction behavior
- Timeout
- Retryability
- Maximum retries
- Backoff
- Whether retry requires idempotency
- Retryable error codes

Never automatically retry:

- Validation errors
- Permission failures
- Approval failures
- Customer-input failures
- Unsafe irreversible non-idempotent operations

After idempotency and transaction tests pass emit:

LAYER 2 PROGRESS: 50%

---

# 15. Customer Confirmation and Operator Approval

Distinguish:

Customer Confirmation:
- Clear cart
- Submit checkout
- Submit return request
- Submit wholesale application

Operator Approval:
- Sensitive admin mutation
- Large Broadcast
- Destructive operation
- Future MCP publication
- Other high-risk operations

Support policies:

- none
- customer_confirmation
- operator_approval
- both

Approval receipts must be:

- Request-bound
- Store-bound
- Actor-bound
- Operation-bound
- Input-hash-bound
- Time-limited
- Single-use where appropriate
- Audited

Never accept a raw Boolean `approved=true` as proof.

---

# 16. Dry-Run and Simulation

Implement separate modes.

Dry-run:

- Uses real validation.
- Uses real availability checks.
- Performs no side effects.
- May return "exact preview unavailable".

Simulation:

- Uses deterministic simulator adapters.
- Performs no side effects.
- Never calls production external providers.

Simulation must not:

- Send Telegram messages
- Send Bale messages
- Capture payment
- Mutate inventory
- Mutate cart
- Create real orders
- Create real customers
- Notify real admins

After approval contracts and simulation tests pass emit:

LAYER 2 PROGRESS: 60%

---

# 17. Initial Action Families

Implement only Actions backed by real Backend services.

Missing services must be:

- Reported as unavailable, or
- Left unregistered

Never fake production success.

## Catalog

Implement:

- List Bot-visible categories
- Search Bot-visible products
- Get product details
- Validate product visibility
- Read price/UOM data

Respect Store, Bot, category access, product access, active state, and UOM.

## Cart

Implement:

- Get cart
- Add item
- Update quantity
- Remove item
- Clear cart

Reuse current pricing/UOM/availability/cart rules.

## Orders

Implement:

- List current customer's orders
- Get order status
- List return-eligible orders where real logic exists

Never expose another customer's order.

## Checkout

Implement:

- Validate readiness
- Prepare checkout
- Return missing requirements

Do not perform payment capture in dry-run/simulation.

## Business Processes

Where real services exist:

- Create support request
- Create return request
- Create wholesale application
- Notify administrator

After real service integration and tests emit:

LAYER 2 PROGRESS: 70%

---

# 18. Action Availability

An Action may be registered but unavailable.

Availability may depend on:

- Store
- Bot
- Platform
- Bot enabled state
- Integration
- Permissions
- Payment provider
- Business service
- Product/category access
- Platform capability
- Feature flags

Return structured reasons.

Layer 1 validation must be able to query Layer 2 availability.

---

# 19. Workflow Node → Action Binding

A workflow Action node references:

- Action key
- Action version constraint
- Typed input mapping
- Typed output mapping
- Success transition
- Error transition
- Retry transition
- Pending approval transition
- Unavailable transition

Inputs may come from:

- Workflow variables
- Typed constants
- Explicit allowlisted trusted Runtime context

Outputs may write only to declared workflow variables.

Never allow:

- Arbitrary expression execution
- Arbitrary object traversal
- Arbitrary Runtime-context access
- Secret mapping into workflow variables

Validate bindings before workflow status becomes ready.

After Layer 1 integration passes emit:

LAYER 2 PROGRESS: 80%

---

# 20. Action Catalog Dashboard

Add:

Bot Experience Studio → Action Catalog

Display:

- Action
- Key
- Version
- Category
- Description
- Inputs
- Outputs
- Side-effect class
- Confirmation policy
- Approval policy
- Idempotency policy
- Retry policy
- Supported platforms
- Availability
- Simulator support
- Deprecation state

Support contextual availability inspection by:

- Store
- Bot
- Platform

Safe dry-run may be exposed only where appropriate.

Never allow arbitrary identity/context impersonation.

After frontend implementation and focused frontend tests emit:

LAYER 2 PROGRESS: 85%

---

# 21. Security Requirements

Enforce:

- Tenant isolation
- Store isolation
- Bot ownership
- Customer ownership
- Schema validation
- Output filtering
- Sensitive-field redaction
- Request-size limits
- Schema-depth limits
- Rate limits where applicable
- Idempotency
- Approval verification
- Auditability

Prevent:

- Prototype pollution
- Unsafe object merging
- Secret leakage
- Approval replay
- Idempotency-key abuse
- Arbitrary Actions
- Arbitrary service calls
- Error-message leakage

---

# 22. Observability

Record safe metrics/logs:

- Correlation ID
- Action key/version
- Store
- Bot
- Platform
- Side-effect class
- Status
- Duration
- Retry count
- Stable error code

Metrics:

- Invocations
- Success
- Failure
- Retry
- Pending approval
- Duration
- Unavailable Action
- Idempotency deduplication

Never log secrets or sensitive documents.

---

# 23. Mandatory Testing

Registry:
- Duplicate rejection
- Descriptor validation
- Version resolution
- Deprecation
- Unknown Action rejection

Schema:
- Valid/invalid inputs
- Output validation
- Sensitive redaction
- Size/depth limits

Permissions:
- Cross-Store
- Cross-Bot
- Cross-customer
- Missing scope
- Disabled Bot

Idempotency:
- Duplicate call
- Concurrent duplicate
- Same key/different input
- Previous-result return

Simulation:
- No mutation
- No external calls
- Deterministic result

Integration:
- Product search
- Bot visibility
- Cart add
- Cart quantity
- Cart read
- Order status
- Checkout preparation
- Supported business-process Action
- Unavailable Action
- Unauthorized Action

Frontend:
- Action Catalog
- Filters
- Detail
- Availability
- Side-effect labels
- Deprecated Actions
- Dry-run

After focused tests pass emit:

LAYER 2 PROGRESS: 90%

Run:

- Formatting
- Linting
- Type checking
- Unit tests
- Integration tests
- Security tests
- Frontend tests
- Relevant E2E
- Production build

Use Codespaces where available.

Run:

Test → Debug → Fix → Retest

until the relevant suite passes.

After the complete regression/build gate passes emit:

LAYER 2 PROGRESS: 95%

---

# 24. Non-Goals

Do not implement:

- Live Workflow Runtime
- Customer workflow sessions
- Telegram/Bale workflow routing
- MCP Server
- AI workflow generation
- Arbitrary HTTP Actions
- Arbitrary code
- Arbitrary SQL
- Automatic payment capture
- Automatic Broadcast
- Worker-owned Actions
- GitHub Actions enablement

---

# 25. Layer 2 Definition of Done

Layer 2 reaches 100% only when:

- Typed Action Registry exists.
- Descriptors are versioned.
- Explicit adapters exist.
- Existing business services are reused.
- Store isolation works.
- Bot isolation works.
- Customer ownership works.
- Side effects are classified.
- Required idempotency works.
- Execution receipts work.
- Dry-run performs no mutation.
- Simulation performs no mutation.
- Approval contracts are request-bound.
- Workflow nodes safely reference Actions.
- Layer 1 validation detects invalid bindings.
- Action Catalog works.
- Security tests pass.
- Unit/integration/frontend tests pass.
- Type checking passes.
- Linting passes.
- Production build passes.
- Existing bot behavior remains operational.
- GitHub Actions remain disabled.
- Final diff reviewed.
- Documentation updated.
- Final commit created.
- Working tree clean.

Only then emit:

LAYER 2 PROGRESS: 100%
STATUS: COMPLETE — READY FOR LAYER 3

---

# 26. Final Layer 2 Report

Provide:

1. Base branch
2. Feature branch
3. Final commit
4. Progress = 100%
5. Registered Actions
6. Unavailable/deferred Actions
7. Models/migrations
8. Application services
9. APIs
10. Dashboard pages
11. Side-effect policies
12. Approval policies
13. Idempotency implementation
14. Exact test commands/results
15. Remaining limitations
16. Layer 3 contracts
17. Architectural/security risks

Do not start Layer 3 inside this prompt.
```