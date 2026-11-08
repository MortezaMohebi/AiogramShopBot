# IMPLEMENTATION PROMPT
# Bot Experience Studio — Layer 4
# MCP Workflow Designer and Management Server

## Role

Act as a Senior MCP Architect, AI Tooling Engineer, Backend Engineer,
Security Engineer, Workflow-System Designer, Multi-Tenant SaaS Architect,
and Next.js Engineer.

You are working inside the existing `AiogramShopBot` repository.

Your task is to fully implement Layer 4:

1. Standards-compliant Remote MCP Server
2. Workflow Discovery
3. Typed Workflow Management Tools
4. AI-Assisted Workflow Creation and Editing
5. Action/Platform Capability Discovery
6. Validation and Simulation
7. Durable Change Sets
8. Human Approval
9. Automatic continuation after approval
10. Publication and Rollback tools
11. Runtime inspection/control tools
12. Authentication and Scopes
13. Quotas and Rate Limits
14. Audit
15. MCP Administration UI

The MCP Server must allow authorized AI clients to safely create, inspect,
modify, validate, simulate, compare, publish, roll back, and inspect
customer-facing bot workflows.

MCP is an adapter.

Backend services remain authoritative.

Never build a generic remote-code-execution server.

---

# 1. Mandatory Progress Reporting Protocol

Report progress during Layer 4.

Use:

LAYER 4 PROGRESS: XX%
Completed:
- ...
Currently working on:
- ...
Remaining critical work:
- ...
Current blockers:
- None / ...

Percentages are earned only by verified milestones.

Do not use elapsed time, file count, LOC, or subjective effort to calculate
progress.

A critical security or compatibility failure may require lowering the reported
percentage.

## Layer 4 Progress Milestones

0%:
- Phase started.

5%:
- Layer 1/2/3, Backend services, auth/RBAC, Gateway, audit, quotas, Runtime,
  publication, and MCP-related existing code audited.

10%:
- Current official MCP specification/SDK/transport/auth approach verified and
  MCP architecture finalized.

20%:
- MCP server foundation, transport, authentication, session identity, scopes,
  and tenant isolation implemented.

30%:
- Context, Store, Bot, platform, and Action discovery tools/resources
  implemented.

40%:
- Workflow read/create/edit/revision/typed patch tools implemented.

50%:
- Durable Change Sets, optimistic concurrency, diffing, validation, and
  simulation tools implemented.

60%:
- Human approval, exact hash binding, durable pending operations, and
  automatic continuation implemented.

70%:
- Publish, rollback, Runtime inspection/control, and approval-aware operations
  implemented.

80%:
- MCP resources, prompt templates, rate limits, quotas, output-safety, audit,
  and administration dashboard implemented.

85%:
- MCP contract/tenant/security/approval tests passing.

90%:
- Supported MCP client compatibility and integrated AI workflow scenario
  passing.

95%:
- Full relevant regression suite, lint, type checking, and production build
  passing.

100%:
- Definition of Done verified.
- Security review completed.
- Final diff reviewed.
- Final commit created.
- Working tree clean.

Do not report 100% if MCP behavior has only been tested through direct internal
service calls rather than the MCP interface.

---

# 2. Prerequisites

Verify actual Layer 1:

- Workflow definitions
- Visual Builder
- Revisions
- Validation
- Simulator

Verify actual Layer 2:

- Action Registry
- Action schemas
- Side effects
- Idempotency
- Execution receipts
- Approval contracts

Verify actual Layer 3:

- Published versions
- Runtime
- Entry points
- Telegram/Bale execution
- Workflow Runs
- Publication/rollback
- Runtime inspection

Do not trust documentation alone.

Do not bypass a missing Backend service in the MCP adapter.

Fix the smallest reusable Backend contract if necessary.

---

# 3. Project Context

The platform supports:

- Multiple Stores
- Multiple Telegram bots
- Multiple Bale bots
- Multiple Workers
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
- Bot Experience Studio
- Workflow Runtime
- Next.js dashboard

Rules:

- MCP must not be Worker-owned.
- MCP must reuse application services.
- MCP must not directly access ORM/database.
- MCP must enforce Store/Bot permissions.
- MCP must not expose credentials.
- GitHub Actions remain disabled.

---

# 4. Initial Investigation

Before implementation inspect:

1. Git status.
2. Correct Layer 3 base.
3. Workflow services.
4. Revision services.
5. Validation.
6. Simulation.
7. Action Registry.
8. Publication/rollback.
9. Runtime inspection.
10. Approval contracts.
11. Authentication.
12. RBAC.
13. Store/Bot ownership.
14. Gateway/deployment model.
15. Rate limiting.
16. Quotas.
17. Audit.
18. Any existing MCP implementation.
19. Codespaces/tests.
20. Installed engineering skills.

Also consult the current official MCP specification and official maintained SDK
documentation.

Verify:

- Current protocol version
- Remote transport
- Authentication recommendations
- Tool behavior
- Resource behavior
- Prompt behavior
- Elicitation/interaction behavior where supported
- Session semantics
- Error handling

Do not implement a custom protocol that only resembles MCP.

After audit emit:

LAYER 4 PROGRESS: 5%

After current MCP architecture decisions are documented emit:

LAYER 4 PROGRESS: 10%

---

# 5. Git Rules

Create:

`feat/bot-experience-layer4-mcp-workflow-designer`

Base it on final verified Layer 3 commit.

Do not:

- Discard unrelated work.
- Enable GitHub Actions.
- Bypass approval because a client lacks native approval UI.
- Add direct database access to MCP handlers.

---

# 6. Required Architecture

AI Client
    ↓
Remote MCP Transport
    ↓
Authentication / Identity / Scopes
    ↓
MCP Tool, Resource, Prompt Adapters
    ↓
Existing Backend Application Services
    ├── Workflow Service
    ├── Revision Service
    ├── Validation Service
    ├── Simulation Service
    ├── Action Registry
    ├── Publication Service
    ├── Approval Service
    └── Runtime Inspection Service
    ↓
Existing Persistence / Runtime

MCP handlers must remain thin.

Do not duplicate domain rules in MCP.

---

# 7. Authentication and Identity

Each session/request resolves:

- User
- Tenant/organization
- Accessible Stores
- Role
- Permission scopes
- MCP connection
- Client identity
- Correlation ID

Support revocable credentials.

Do not trust tool parameters for authoritative:

- User identity
- Store ownership
- Administrator role
- Permission scopes

Requested Store/Bot IDs must always be checked against authenticated access.

Suggested scopes:

- workflow:read
- workflow:write
- workflow:validate
- workflow:simulate
- workflow:publish
- workflow:rollback
- runtime:read
- runtime:control
- actions:read
- bots:read
- audit:read

Publishing must require stronger permission than draft editing.

After MCP transport/auth/scope tests pass emit:

LAYER 4 PROGRESS: 20%

---

# 8. MCP Tool Principles

Every tool must have:

- Stable name
- Precise description
- Strict schema
- Structured response
- Stable error model
- Correlation ID
- Pagination
- Request-size limit
- Tenant checks
- Secret redaction
- Idempotency where appropriate

Never expose:

- execute_sql
- execute_python
- execute_javascript
- run_command
- call_any_url
- call_backend_method
- invoke_action_by_method_name
- edit_database

Do not expose raw ORM objects.

---

# 9. Context and Discovery Tools

Implement equivalents of:

## Identity / Store

- context.get_profile
- context.list_accessible_stores
- context.get_store

## Bots

- context.list_bots
- context.get_bot

## Platforms

- platform.list
- platform.get_capabilities
- platform.compare_capabilities

## Actions

- action.list
- action.get
- action.check_availability

Return safe metadata only.

Never expose:

- Bot tokens
- Payment secrets
- Internal credentials

After discovery tools/resources tests pass emit:

LAYER 4 PROGRESS: 30%

---

# 10. Workflow Read Tools

Implement equivalents of:

- workflow.list
- workflow.get
- workflow.get_definition
- workflow.list_revisions
- workflow.get_revision
- workflow.compare_revisions
- workflow.list_assignments
- workflow.get_validation
- workflow.get_publication_status

Use pagination.

Return compact summary by default.

---

# 11. Workflow Mutation Tools

Implement equivalents of:

- workflow.create_draft
- workflow.duplicate
- workflow.update_metadata
- workflow.assign_bots
- workflow.archive
- workflow.restore_revision
- workflow.apply_patch
- workflow.replace_definition

Prefer typed patch operations:

- add_node
- update_node
- remove_node
- add_edge
- update_edge
- remove_edge
- add_variable
- update_variable
- remove_variable
- add_entry_point
- update_entry_point
- remove_entry_point
- assign_bot
- unassign_bot
- update_platform_override

Every mutation requires:

- Expected revision
- Idempotency key
- Optional change summary

Reject stale revisions.

Never silently overwrite.

After mutation/revision tests pass emit:

LAYER 4 PROGRESS: 40%

---

# 12. Durable Change Sets

Implement Change Set fields:

- ID
- Store
- Workflow
- Base revision
- Proposed operations
- Proposed definition hash
- Diff summary
- Validation
- Platform compatibility
- Action dependencies
- Risk classification
- Creator
- MCP connection
- Created time
- Expiration
- Status

Statuses:

- draft
- validated
- invalid
- pending_approval
- approved
- rejected
- applied
- expired
- cancelled

A Change Set is bound to exact proposed changes.

Approval of one Change Set cannot authorize another.

---

# 13. Validation and Simulation Tools

Implement:

- workflow.validate
- workflow.validate_change_set
- workflow.simulate
- workflow.simulate_change_set
- workflow.explain_validation_issue

Simulation may accept:

- Platform
- Bot
- Simulated customer context
- Input sequence
- Selected branches
- Action simulator fixtures

Return:

- Conversation transcript
- Visited nodes
- Variable changes
- Simulated Action results
- Validation errors
- Platform warnings
- Terminal state

Simulation remains side-effect-free.

Never call:

- Real payment
- Real Telegram delivery
- Real Bale delivery
- Real cart mutations
- Real order mutations
- Real notifications

After Change Set + validation + simulation suites pass emit:

LAYER 4 PROGRESS: 50%

---

# 14. Natural-Language Workflow Design Contract

The AI client handles natural-language reasoning.

The MCP Server provides safe structured operations.

Do not create:

`workflow.do_whatever_user_asks`

or another unrestricted tool.

Expected AI workflow:

1. Discover accessible Store.
2. Discover Bots.
3. Discover Telegram/Bale capabilities.
4. Discover registered Actions.
5. Read existing workflow if editing.
6. Create draft or Change Set.
7. Apply typed operations.
8. Validate.
9. Simulate.
10. Inspect exact diff.
11. Request approval.
12. Publish exact approved revision.
13. Return receipt.

This supports requests such as:

- Build a return mechanism.
- Build warranty registration.
- Build wholesale onboarding.
- Edit product discovery.
- Add conditional menus.
- Add file upload.
- Make a step optional.
- Restrict to selected Bots.
- Create Telegram/Bale-specific presentation overrides.

If the required Action does not exist:

- Report the missing capability.
- Do not invent executable behavior.

---

# 15. Human Approval

Require approval for at least:

- Publish
- Rollback
- Change active entry points
- Enable Runtime on Bot
- Sensitive Runtime retry
- Sensitive Runtime cancellation
- High-risk Change Set
- Future irreversible operations

Approval must be:

- Request-bound
- User-bound
- Store-bound
- Workflow-bound
- Revision-bound
- Change-Set-bound
- Definition-hash-bound
- Time-limited
- Single-use where appropriate
- Audited

Approval view shows:

- Store
- Workflow
- Bots
- Platforms
- Current revision
- Proposed revision
- Exact diff
- Validation
- Compatibility
- Action dependencies
- Risk
- Customer impact
- Approve
- Reject

Never use generic approval for unknown future changes.

---

# 16. Automatic Continuation After Approval

Required preferred flow:

1. Tool reaches approval boundary.
2. Exactly one approval request is created.
3. User approves/rejects.
4. Original durable operation resumes automatically.
5. Final result returns where client capabilities allow.

Persist:

- Original tool request
- Normalized arguments
- Change Set
- Requested operation
- Approval request
- Expiration
- Resume state
- Correlation ID

After approval revalidate:

- Current workflow revision
- User permissions
- Store access
- Bot state
- Change Set hash
- Platform compatibility
- Action availability

If anything relevant changed:

- Do not publish.
- Return stale/conflict.
- Require new preview and approval.

If MCP client supports interactive approval/elicitation, use it.

Otherwise provide durable operation status and polling fallback.

Never force the user to manually reconstruct the original request.

After approval/auto-resume replay/staleness tests pass emit:

LAYER 4 PROGRESS: 60%

---

# 17. Publication Tools

Implement equivalents:

- workflow.prepare_publish
- workflow.request_publish
- workflow.get_publish_request
- workflow.cancel_publish_request
- workflow.prepare_rollback
- workflow.request_rollback

prepare_publish returns:

- Exact revision
- Definition hash
- Diff
- Validation
- Platform compatibility
- Action dependencies
- Entry-point changes
- Runtime readiness
- Risk classification

request_publish must only operate on:

- Exact validated revision, or
- Exact validated Change Set

Never accept an arbitrary unvalidated definition.

---

# 18. Runtime Tools

Read-only:

- runtime.list_runs
- runtime.get_run
- runtime.get_run_timeline
- runtime.list_failures
- runtime.get_metrics

Controlled operations:

- runtime.prepare_retry
- runtime.request_retry
- runtime.prepare_cancel
- runtime.request_cancel

Operations affecting business/customer state must use approval.

Return redacted information only.

After publication/rollback/Runtime tools pass emit:

LAYER 4 PROGRESS: 70%

---

# 19. MCP Resources

Expose authenticated resources such as:

- Workflow schema
- Node catalog
- Action catalog
- Platform capabilities
- Validation-code catalog
- Workflow examples
- Store workflow summaries
- Published version summaries
- Runtime summaries

Resources must be tenant-isolated.

Never expose credentials.

---

# 20. MCP Prompt Templates

Where supported provide:

- Design a customer workflow
- Review workflow completeness
- Convert manual bot flow
- Compare Telegram/Bale compatibility
- Pre-publication review
- Diagnose Runtime failure

Templates should instruct the client to:

- Discover first.
- Use registered Actions only.
- Create a draft.
- Validate.
- Simulate.
- Show changes.
- Never publish without approval.
- Never invent Store/Bot/Product/Action/platform capabilities.

Prompts are guidance, not authorization.

---

# 21. Tool Output Safety and Prompt Injection

Treat as untrusted:

- Product descriptions
- Customer messages
- Order notes
- Workflow user-authored descriptions
- Uploaded files
- External integration data

Differentiate:

- Trusted server metadata
- Administrator-authored content
- Customer-authored content
- External content

Never convert untrusted content into internal MCP instructions.

Return minimum necessary customer data.

---

# 22. Rate Limits / Quotas / Concurrency

Implement limits for:

- Requests per connection
- Requests per user
- Requests per Store
- Concurrent simulation
- Concurrent validation
- Concurrent publication
- Workflow definition size
- Patch operation count
- Response size
- Pagination
- Approval requests

Return structured rate-limit errors.

Prevent one tenant from monopolizing resources.

---

# 23. MCP Administration Dashboard

Add:

Bot Experience Studio → MCP

Views:

1. MCP Connections
2. Connection Detail
3. Permission Scopes
4. Store Access
5. Active Sessions
6. Approval Requests
7. Audit
8. Usage/Quotas
9. Revoke Connection

Display:

- Connection name
- Client type
- User
- Stores
- Scopes
- Created
- Last used
- Safe connection metadata
- Request count
- Approval count
- Revocation status

Never display raw token after creation.

Revocation must take effect immediately.

---

# 24. Audit

Audit:

- Authentication
- Connection creation
- Revocation
- Workflow reads when policy requires
- Draft creation
- Mutation
- Change Set
- Validation
- Simulation
- Approval request
- Approval decision
- Publication
- Rollback
- Runtime control
- Permission failure
- Cross-tenant attempt
- Rate-limit violation

Record:

- User
- Connection
- Store
- Workflow
- Tool
- Correlation ID
- Result
- Stable error
- Timestamp

Redact secrets and sensitive customer data.

After resources/prompts/limits/admin/audit are complete emit:

LAYER 4 PROGRESS: 80%

---

# 25. Stable MCP Error Model

Support:

- authentication_required
- permission_denied
- store_not_accessible
- bot_not_accessible
- workflow_not_found
- revision_conflict
- invalid_workflow
- unsupported_platform_capability
- action_unavailable
- approval_required
- approval_pending
- approval_rejected
- approval_expired
- change_set_stale
- rate_limited
- request_too_large
- runtime_unavailable
- internal_error

Return safe remediation where deterministic.

Never return raw stack traces.

---

# 26. Mandatory Tests

## MCP Contract

- Tool discovery
- Resource discovery
- Prompt discovery where supported
- Input schemas
- Output schemas
- Pagination
- Structured errors
- Authentication
- Scopes

## Tenant Isolation

- Cannot list another Store
- Cannot access another Store's workflow
- Cannot assign another Store's Bot
- Cannot publish another Store's workflow
- Cannot read another Store's Runtime Runs
- User-provided Store ID cannot bypass auth

## Draft / Change Set

- Create draft
- Typed patches
- Revision conflict
- Validation
- Expiration
- Stale Change Set
- Idempotent repetition

## Approval

- Exact hash binding
- Replay rejection
- Expiration
- Reject stops operation
- Approval auto-resumes
- Concurrent workflow modification creates conflict
- Approval cannot authorize second publication

## Simulation

- No side effect
- Telegram simulation
- Bale simulation
- Platform incompatibility
- Invalid workflow

## Security

- Arbitrary Action impossible
- Arbitrary URL impossible
- Arbitrary code impossible
- Prompt injection remains untrusted
- Oversized request rejected
- Sensitive data redacted
- Revoked connection rejected immediately

After these tests pass emit:

LAYER 4 PROGRESS: 85%

---

# 27. Client Compatibility

Test using available supported tooling:

- Official MCP inspection tooling
- Supported ChatGPT MCP integration path
- At least one supported developer-agent MCP client where available

Do not fake client compatibility if the environment cannot actually run it.

Report BLOCKED with exact reason where external client testing is impossible.

Do not call blocked testing PASS.

---

# 28. Integrated Acceptance Scenario

Through MCP:

1. Authenticate Store admin.
2. List Stores.
3. List Telegram/Bale Bots.
4. Read platform capabilities.
5. Read Action Catalog.
6. Create product-inquiry workflow.
7. Add:
   - Start
   - Customer question
   - Category choice
   - Product search Action
   - Product display
   - Contact request
   - Confirmation
   - Completion
8. Assign Telegram/Bale Bots.
9. Validate.
10. Introduce/detect one compatibility issue.
11. Fix using typed patch.
12. Simulate Telegram.
13. Simulate Bale.
14. Create Change Set.
15. Show exact diff.
16. Prepare publication.
17. Create exactly one human approval.
18. Approve.
19. Automatically continue.
20. Revalidate exact hash.
21. Publish.
22. Return publication receipt.
23. Start fake Runtime test.
24. Inspect Runtime Run through MCP.
25. Verify Action receipt.
26. Verify audit.
27. Verify no unauthorized tenant data.

After integrated MCP scenario/client compatibility passes emit:

LAYER 4 PROGRESS: 90%

---

# 29. Full Regression Gate

Run all relevant:

- Formatting
- Linting
- Type checking
- Unit tests
- Integration tests
- Workflow tests
- Runtime tests
- MCP contract tests
- Approval tests
- Security tests
- E2E
- Production build

Use:

Test → Debug → Fix → Retest

Do not disable failing tests.

Do not mark flaky failures PASS without root-cause investigation.

After complete regression/build pass emit:

LAYER 4 PROGRESS: 95%

---

# 30. Non-Goals

Do not implement:

- Customer-facing generative AI
- LLM inference inside Telegram/Bale Runtime
- Arbitrary code execution
- Arbitrary SQL
- Arbitrary HTTP execution
- Generic Backend method invocation
- Automatic publication
- Direct MCP database access
- Secret exposure
- Ordinary workflow access to Bot tokens
- Payment capture through MCP
- Worker-specific MCP ownership
- GitHub Actions enablement

---

# 31. Layer 4 Definition of Done

100% requires:

- Standards-compliant Remote MCP Server.
- Current supported MCP SDK/transport documented.
- Authentication.
- Revocable credentials.
- Scope enforcement.
- Store isolation.
- Bot isolation.
- Context discovery.
- Platform discovery.
- Action discovery.
- Workflow reads.
- Draft creation/editing.
- Typed patching.
- Revision conflict handling.
- Validation through MCP.
- Side-effect-free simulation.
- Durable Change Sets.
- Exact approval binding.
- Approval replay protection.
- Automatic continuation.
- Stale approval prevention.
- Publication.
- Rollback.
- Runtime inspection.
- Controlled Runtime operations.
- MCP resources.
- MCP prompts.
- Prompt-injection-safe output.
- Quotas.
- Rate limits.
- Audit.
- Administration UI.
- Connection revocation.
- MCP contract tests.
- Tenant tests.
- Approval tests.
- Security tests.
- Supported client compatibility verified or explicitly BLOCKED where external
  environment prevents it.
- E2E acceptance.
- Regression suite.
- Type checking.
- Linting.
- Production build.
- Existing bot/dashboard behavior operational.
- GitHub Actions disabled.
- Final diff reviewed.
- Final commit created.
- Working tree clean.

Only after all locally controllable mandatory gates pass emit:

LAYER 4 PROGRESS: 100%
STATUS: COMPLETE

If a required external compatibility test is genuinely impossible because the
environment lacks that external client, do not falsely claim PASS. Report the
exact item as BLOCKED in the final report while distinguishing it from the
implemented Layer 4 code status.

---

# 32. Final Layer 4 Report

Provide:

1. Base branch
2. Feature branch
3. Final commit
4. Final progress percentage
5. MCP specification version
6. MCP SDK/version
7. Transport
8. Authentication
9. Scopes
10. Tools
11. Resources
12. Prompt templates
13. Change Sets
14. Approval flow
15. Auto-resume behavior
16. Runtime tools
17. Dashboard pages
18. Rate limits/quotas
19. Audit coverage
20. Client compatibility
21. Exact test commands/results
22. Remaining limitations
23. Deferred capabilities
24. Known security/architecture risks

Do not stop after architecture planning.

Do not declare 100% while mandatory locally executable tests fail.

Do not bypass human approval to make an acceptance test pass.
