# IMPLEMENTATION PROMPT
# Bot Experience Studio — Layer 3
# Production Workflow Runtime for Telegram and Bale

## Role

Act as a Senior Distributed Systems Architect, Workflow Runtime Engineer,
Backend Engineer, Telegram Bot Engineer, Bale Bot Engineer, Security Engineer,
and Reliability Engineer.

You are working inside the existing `AiogramShopBot` repository.

Your task is to fully implement Layer 3:

1. Immutable Published Workflow Versions
2. Workflow Entry-Point Binding
3. Persistent Customer Workflow Runs
4. Deterministic Workflow Interpreter
5. Telegram/Bale Event Normalization
6. Action Registry Execution
7. Runtime Session Persistence
8. Idempotent Event Processing
9. Transactional Outbound Delivery
10. Timeout/Retry/Cancellation/Recovery
11. Publication and Rollback
12. Runtime Dashboard and Observability
13. Safe coexistence with legacy bot flows

This is a production implementation.

Do not build a demo state machine.

Do not connect workflow drafts directly to live bots.

---

# 1. Mandatory Progress Reporting Protocol

Report Layer 3 progress throughout implementation.

Use:

LAYER 3 PROGRESS: XX%
Completed:
- ...
Currently working on:
- ...
Remaining critical work:
- ...
Current blockers:
- None / ...

Progress must be based on completed and verified milestones.

Never raise the percentage merely because code was written.

If tests reveal a critical regression in a previously completed milestone,
reduce the reported progress when necessary.

## Layer 3 Progress Milestones

0%:
- Phase started.

5%:
- Layer 1/2, BotContext, current Telegram/Bale routing, session handling,
  Workers, queues, locks, scheduler, and tests audited.

10%:
- Runtime architecture and legacy coexistence plan finalized.

20%:
- Immutable publication/version model and publication readiness implemented.

30%:
- Entry-point bindings, feature flags, rollback, and safe legacy fallback
  implemented.

40%:
- Workflow Run/Event/Wait/Callback persistence implemented.

50%:
- Platform-neutral inbound/outbound event models and Telegram/Bale adapters
  integrated.

60%:
- Deterministic interpreter, typed Runtime variables, and state transitions
  implemented.

70%:
- Layer 2 Action execution, idempotent event processing, concurrency controls,
  and callback security implemented.

80%:
- Transactional outbox, retries, timeouts, cancellation, and recovery
  implemented.

85%:
- Runtime dashboard, publication UI, rollback UI, and observability
  implemented.

90%:
- Runtime unit/integration/adapter/security tests passing.

95%:
- Full relevant E2E/regression tests, type checking, linting, and production
  build passing.

100%:
- Definition of Done verified.
- Legacy bot behavior verified.
- Final diff reviewed.
- Final commit created.
- Working tree clean.

Do not report 100% if a Runtime-critical test remains skipped, flaky, blocked,
or failing.

---

# 2. Prerequisites

Verify real Layer 1 support for:

- Workflow definitions
- Revisions
- Validation
- Visual Builder
- Simulator
- Platform capabilities

Verify real Layer 2 support for:

- Typed Action Registry
- Action descriptors
- Input/output schemas
- Permission policies
- Side-effect policies
- Idempotency
- Execution receipts
- Dry-run
- Simulation
- Approval contracts

Do not duplicate these layers.

If a direct contract is missing:

- Add the minimum reusable fix.
- Add a regression test.
- Document it.

---

# 3. Project Context

The platform supports:

- Multiple Stores
- Multiple Telegram bots
- Multiple Bale bots
- Multiple Cloudflare Workers
- Bot Registry
- BotContext
- Product/category access
- Catalog
- Cart
- Checkout
- Orders
- Customers
- Wallets/payment
- Broadcast
- Next.js dashboard

Rules:

- Runtime ownership belongs to Store/Bot, not Worker.
- Existing bots must continue to function.
- New Runtime is opt-in initially.
- No historical Runtime backfill is required.
- Schema migrations are allowed.
- GitHub Actions remain disabled.

---

# 4. Initial Investigation

Inspect:

1. Git state.
2. Correct completed Layer 2 base.
3. Layer 1 workflow schema.
4. Layer 2 Action Registry.
5. Telegram inbound routing.
6. Bale inbound routing.
7. Existing callbacks.
8. Existing customer sessions.
9. BotContext resolution.
10. Store/Bot flags.
11. Cloudflare Worker role.
12. Queue infrastructure.
13. Scheduler.
14. Cache.
15. Locks/concurrency.
16. Transactions.
17. Existing outbox.
18. Delivery retry behavior.
19. Logging/metrics.
20. Codespaces/tests.

After this audit emit:

LAYER 3 PROGRESS: 5%

---

# 5. Git Rules

Create:

`feat/bot-experience-layer3-workflow-runtime`

Base it on the final verified Layer 2 commit.

Do not:

- Discard unrelated work.
- Enable GitHub Actions.
- Remove legacy handlers.
- Couple Runtime ownership to Workers.

---

# 6. Immutable Published Versions

Extend lifecycle:

- draft
- invalid
- ready
- published
- retired
- archived

Published workflow versions must be immutable.

A Workflow Run is permanently pinned to the exact published version with which
it started.

Editing after publication creates a new draft revision.

Never mutate a published definition.

---

# 7. Publication Readiness

Before publication verify:

- Layer 1 structural validity
- Reachability
- Terminal paths
- Variables
- Conditions
- Platform compatibility
- Bot assignment
- Entry points
- Action keys
- Action versions
- Action availability
- Required permissions
- Required integrations
- Customer confirmations
- Operator approvals
- Runtime compatibility
- Callback constraints
- Message/media limits
- No unresolved simulator-only Action
- No unsafe cycle
- No unsupported terminal path

Publishing must fail with structured errors otherwise.

---

# 8. Publish and Rollback

Implement:

- Publish preview
- Definition diff
- Bot assignment diff
- Entry-point diff
- Action dependency summary
- Platform compatibility summary
- Risk summary
- Explicit approval
- Activation
- Audit receipt

Rollback:

- Activates an earlier immutable version for new Runs.
- Does not mutate history.
- Does not migrate existing Runs automatically.

After publication/version tests pass emit:

LAYER 3 PROGRESS: 20%

---

# 9. Workflow Entry Points

Support where applicable:

- Bot command
- Main-menu item
- Start/deep-link parameter
- Internal workflow transition
- Legacy menu bridge
- Administrator test entry point

Binding fields include:

- Store
- Bot
- Platform
- Workflow
- Version policy
- Entry-point type
- Stable key
- Priority
- Enabled
- Eligibility condition
- Fallback

Reject cross-Store Bot assignment.

Prevent conflicting bindings.

---

# 10. Legacy Coexistence

Runtime must initially be opt-in.

Use:

- Store feature flag
- Bot feature flag
- Entry-point binding
- Emergency kill switch

Routing order:

1. Resolve BotContext.
2. Evaluate Runtime feature flags.
3. Check active Workflow Run.
4. Check matching entry point.
5. Use Workflow Runtime where applicable.
6. Otherwise invoke existing legacy behavior.

Do not break:

- /start
- Catalog
- Product details
- Cart
- Checkout
- Payment
- Order status
- Broadcast callbacks
- Telegram menus
- Bale menus

Emergency disable must immediately return applicable routing to legacy handlers
without deleting workflow data.

After entry points and fallback tests pass emit:

LAYER 3 PROGRESS: 30%

---

# 11. Runtime Persistence

Implement:

## Workflow Run

Include:

- Run ID
- Store ID
- Bot ID
- Platform
- Customer reference
- Workflow ID
- Published version ID
- Entry point
- Current node
- Status
- Typed variable state
- Lock/version counter
- Started timestamp
- Updated timestamp
- Completed timestamp
- Cancelled timestamp
- Expiration
- Last inbound event
- Last outbound delivery
- Correlation ID

Statuses:

- active
- waiting_input
- waiting_action
- waiting_approval
- waiting_timeout
- completed
- cancelled
- failed
- expired
- suspended

## Workflow Event

Include:

- Event ID
- Run
- Event type
- Platform event identifier
- Node
- Timestamp
- Processing status
- Redacted payload summary
- Stable error
- Correlation ID

## Runtime Wait

Include:

- Expected input type
- Timeout
- Retry count
- Resume node
- Timeout node
- Cancellation node

## Callback Token

Must be:

- Short
- Opaque
- Server-resolvable
- Bound to trusted Runtime state

Never store complete Runtime state inside platform callback payloads.

After persistence and migration tests pass emit:

LAYER 3 PROGRESS: 40%

---

# 12. Event Normalization

Create one platform-neutral inbound model.

Normalize events such as:

- Command
- Callback
- Text
- Number
- Phone/contact
- Email
- Photo
- Document
- Choice
- Confirmation
- Cancellation
- Timeout
- Internal action completion

Telegram adapter:

Telegram update → normalized Runtime event

Bale adapter:

Bale update → normalized Runtime event

Runtime output:

Platform-neutral output → Telegram/Bale rendering

Do not pass raw platform SDK objects throughout Runtime.

After both adapters pass focused normalization tests emit:

LAYER 3 PROGRESS: 50%

---

# 13. Deterministic Interpreter

Support Layer 1 nodes.

Control:

- Start
- End
- Cancel
- Condition
- Switch
- Go-to
- Wait
- Set variable

Messages:

- Send text
- Send photo
- Send video
- Send document
- Media group where supported

Inputs:

- Ask text
- Ask number
- Ask phone
- Ask email
- Ask choice
- Ask photo
- Ask document
- Confirm

Navigation:

- Buttons
- Menu
- Back
- Main menu

Actions:

- Execute only through Layer 2

Interpreter advances until:

- Customer input boundary
- Action boundary
- Approval boundary
- Timeout boundary
- Terminal node
- Safe maximum automatic-transition count

Do not use unlimited recursion.

Reject infinite loops safely.

---

# 14. Runtime Variables

Persist only declared typed values:

- String
- Integer
- Decimal
- Boolean
- Date
- Datetime
- Enum
- Product reference
- Category reference
- Customer reference
- Order reference

Trusted Runtime context remains separate from workflow variables.

Workflows must not modify:

- Store identity
- Bot identity
- Customer identity
- Permission scopes
- Approval state
- Secrets

After interpreter tests pass emit:

LAYER 3 PROGRESS: 60%

---

# 15. Action Execution Through Layer 2

Runtime must:

- Resolve exact Action/version.
- Build trusted invocation context.
- Map typed input.
- Validate availability.
- Validate permission.
- Enforce customer confirmation.
- Enforce operator approval.
- Generate/provide idempotency key.
- Record execution receipt.
- Map typed output.
- Follow success/failure/retry/pending transitions.

Never call domain service methods directly from Runtime Action nodes.

---

# 16. Idempotent Inbound Processing

Handle duplicate platform delivery safely.

Prevent duplicate:

- Run creation
- Transition
- Action execution
- Cart mutation
- Order mutation
- Return request
- Outbound intent

Do not claim impossible global exactly-once semantics.

Implement practical:

- At-least-once processing
- Deduplication
- Idempotent transitions
- Layer 2 Action idempotency
- Transactional outbox
- Delivery receipts

---

# 17. Concurrency

Handle:

- Two simultaneous callbacks
- Callback + text race
- Timeout + input race
- Retry + original execution race
- Multiple workers consuming one event
- Multiple active customer interactions

Use existing DB locks or optimistic concurrency.

Never silently drop valid customer input.

---

# 18. Callback Security

Callback tokens must be:

- Opaque
- Short
- Store-bound
- Bot-bound
- Customer-bound where appropriate
- Run-bound
- Node-bound
- Time-limited
- Tamper-resistant
- Single-use where required

Never trust callback data for:

- Price
- Product authorization
- Order ownership
- Approval
- Workflow state
- Customer identity

Revalidate everything server-side.

After Action integration, concurrency, deduplication, and callback security tests
pass emit:

LAYER 3 PROGRESS: 70%

---

# 19. Transactional Outbox

Separate:

1. Runtime state transition
2. Outbound intent
3. External delivery
4. Delivery receipt

Persist outbound intent transactionally.

Support:

- pending
- sent
- failed
- retryable
- dead_letter

Use bounded retries/backoff.

Keep Bot tokens outside outbox payloads.

Store necessary platform message IDs for safe edits/callback handling.

---

# 20. Timeout, Retry, Cancellation, Recovery

Handle:

- Input timeout
- Action timeout
- Telegram failure
- Bale failure
- Backend transient failure
- Retryable Action failure
- Cancellation
- Customer restart
- Expired callback
- Disabled Bot
- Retired workflow
- Missing media
- Runtime exception

Use existing scheduler/worker infrastructure.

Do not leave runs permanently active without policy.

Operator recovery capabilities:

- Inspect
- Retry failed step
- Resume suspended run
- Cancel run
- Mark failed

High-risk recovery must be audited.

---

# 21. Back / Cancel / Main Menu

Back:

- Return to a safe prior interactive state.
- Never automatically reverse an irreversible business Action.

Cancel:

- Mark run cancelled.
- Send configured cancellation output.
- Do not undo business mutations unless explicit compensating Action exists.

Main Menu:

- End/suspend/leave according to explicit policy.
- Never leave ambiguous active Runs.

After recovery/outbox tests pass emit:

LAYER 3 PROGRESS: 80%

---

# 22. Runtime Dashboard

Add:

Bot Experience Studio → Runtime

Views:

1. Published Workflows
2. Entry-Point Bindings
3. Active Runs
4. Failed/Suspended Runs
5. Run Detail
6. Outbound Delivery
7. Publish/Rollback History

Run Detail:

- Store
- Bot
- Platform
- Workflow/version
- Current node
- Status
- Safe variables
- Events
- Action receipts
- Outbound intents/messages
- Errors
- Retries
- Correlation ID

Redact sensitive values.

After dashboard and observability tests pass emit:

LAYER 3 PROGRESS: 85%

---

# 23. Observability

Metrics/logs:

- Runs started
- Runs completed
- Runs cancelled
- Runs failed
- Completion duration
- Node transitions
- Input validation errors
- Action failures
- Timeouts
- Duplicate events
- Outbox retries
- Dead letters
- Telegram delivery failures
- Bale delivery failures
- Active Runs per workflow/version

Propagate correlation ID through:

Inbound → Runtime → Action → Outbound

Never log sensitive payloads.

---

# 24. Security

Prevent:

- Cross-Store Run access
- Cross-Bot callbacks
- Cross-customer access
- Callback replay
- Event replay
- Arbitrary transitions
- Runtime variable injection
- Unauthorized Action invocation
- Infinite loops
- Oversized Runtime state
- Unsafe file/media
- Platform-payload trust

Enforce:

- Input limits
- Media limits
- MIME/type checks
- Variable limits
- Run-duration limits
- Event-history limits
- Rate limits
- Redaction

---

# 25. Acceptance Workflows

Use fake providers.

## Wholesale Access

1. Start
2. Name
3. Phone
4. Business
5. City
6. Purchase estimate
7. Optional document
8. Review
9. Confirm
10. wholesale.create_application
11. Complete

## Return Request

Where real Backend support exists:

1. Start
2. Eligible orders
3. Order select
4. Product select
5. Reason
6. Optional description
7. Optional photo
8. Review
9. Confirm
10. returns.create_request
11. Complete

Never message real customers in automated tests.

---

# 26. Mandatory Tests

Interpreter:

- Start/end
- Conditions
- Switch
- Variables
- Input validation
- Back
- Cancel
- Timeout
- Retry
- Action transitions
- Transition limits
- Invalid node

Runtime integration:

- Start
- Resume
- Version pin
- Duplicate event
- Concurrent event
- Action idempotency
- Callback validation
- Timeout race
- Outbox retry
- Completion
- Cancellation
- Recovery

Adapters — test Telegram and Bale independently:

- Text
- Buttons
- Callback
- Photo
- Document
- Unsupported media
- Platform limits
- Delivery failure
- Duplicate update

Security:

- Cross-Store
- Cross-Bot
- Cross-customer
- Expired callback
- Replay
- Unauthorized publish
- Unregistered Action

After focused suites pass emit:

LAYER 3 PROGRESS: 90%

E2E:

1. Publish valid workflow.
2. Bind test Bot.
3. Start workflow.
4. Complete inputs.
5. Execute Actions.
6. Verify persistence.
7. Verify outbound.
8. Complete Run.
9. Replay duplicate update.
10. Verify no duplicate side effect.
11. Publish second version.
12. Verify old Run remains pinned.
13. Roll back for new Runs.
14. Disable Runtime.
15. Verify legacy fallback.

Run:

- Formatting
- Linting
- Type checking
- Unit
- Integration
- Adapter
- Security
- E2E
- Production build

Run Test → Debug → Fix → Retest until clean.

After complete regression/build pass emit:

LAYER 3 PROGRESS: 95%

---

# 27. Non-Goals

Do not implement:

- MCP Server
- AI workflow editing
- Customer-facing LLM
- Arbitrary Action execution
- Arbitrary code
- Automatic publication without approval
- Silent active-Run migration
- Immediate removal of legacy flows
- Worker-owned workflow state
- Real payment in tests
- GitHub Actions enablement

---

# 28. Definition of Done

100% requires:

- Immutable published versions.
- Safe publication.
- Rollback.
- Safe entry points.
- Telegram normalization.
- Bale normalization.
- Persistent Runs.
- Version pinning.
- Deduplication.
- Concurrency safety.
- Deterministic interpreter.
- Layer 2-only business Action execution.
- Typed variables.
- Secure callbacks.
- Transactional outbox.
- Timeouts.
- Retries.
- Cancellation.
- Failure recovery.
- Runtime opt-out/kill switch.
- Legacy fallback.
- Runtime dashboard.
- Observability.
- Security tests.
- Runtime tests.
- Adapter tests.
- E2E tests.
- Type checking.
- Linting.
- Production build.
- Existing bot behavior verified.
- GitHub Actions disabled.
- Final diff reviewed.
- Final commit created.
- Working tree clean.

Only then emit:

LAYER 3 PROGRESS: 100%
STATUS: COMPLETE — READY FOR LAYER 4

---

# 29. Final Layer 3 Report

Provide:

1. Base branch
2. Feature branch
3. Final commit
4. Progress = 100%
5. Runtime models
6. Publication implementation
7. Entry points
8. Supported nodes
9. Telegram coverage
10. Bale coverage
11. Action integration
12. Outbox/retry
13. Legacy coexistence
14. Exact tests/results
15. Remaining limitations
16. Required Layer 4 contracts
17. Known risks

Do not start Layer 4 inside this prompt.
