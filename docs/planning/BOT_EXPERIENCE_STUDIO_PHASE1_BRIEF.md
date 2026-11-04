# Implementation Prompt — Bot Experience Studio / Phase 1: Visual Workflow Builder

## Role

Act as a **Senior Full-Stack Architect, Workflow Engine Designer, Next.js Engineer, and Telegram/Bale Bot Platform Architect**.

You are working on the existing `AiogramShopBot` repository.

Your task is to design, implement, integrate, and thoroughly test **Layer 1 — Visual Workflow Builder**, the first component of the future **Bot Experience Studio**.

This must be a real, maintainable, production-quality implementation — not a UI mockup or a disconnected prototype.

## 1. Project Context

The platform is a multi-store, multi-bot e-commerce system supporting:

- Telegram bots
- Bale bots
- Multiple bots per store
- Multiple Cloudflare Workers
- Store and Bot Registry
- `BotContext`
- Per-bot product and category access
- Catalog, Cart, Checkout, Orders, Customers, and Broadcast
- Next.js administration dashboard
- Shared Backend business logic

The system must not impose arbitrary limits on the number of bots, stores, or workers.

The platform is currently in Beta, without production customer data requiring historical migration.

Do not introduce unnecessary backward-compatibility layers or legacy migrations.

Inspect the repository before assuming which features or services exist.

## 2. Primary Objective

Build a visual, drag-and-drop Workflow Builder inside the Next.js dashboard.

Administrators must be able to create and edit customer-facing bot experiences without writing Python, JavaScript, or manually editing Telegram/Bale callback handlers.

A workflow must represent a structured customer interaction consisting of:

- Entry points
- Steps
- Messages
- Buttons
- Inputs
- Conditions
- Branches
- Actions
- Transitions
- Completion and cancellation states

The visual editor must produce a validated, portable, versioned workflow definition.

**Important architectural boundary:**

The Workflow Builder defines workflows.

The existing Backend remains responsible for business logic.

The future Workflow Runtime will execute workflows.

The future MCP Server will manage workflows through the same Backend services.

Do not implement a separate business-logic system inside the Next.js dashboard.

---

## 3. Mandatory Initial Investigation

Before coding:

1. Inspect repository structure, active branches, and existing documentation.
2. Identify the Next.js version, routing architecture, UI component library, authentication model, and API patterns.
3. Inspect Backend models, service boundaries, Store/Bot relationships, and `BotContext`.
4. Locate the existing Telegram and Bale menu and callback implementations.
5. Identify existing workflow-like structures or reusable components.
6. Inspect existing role-based permissions and multi-tenant isolation.
7. Identify existing test infrastructure and Codespaces setup.
8. Read all relevant installed development skills.

Use these skills if available:

- `web-design-guidelines`
- `next-dev-loop`
- Relevant frontend quality and systematic debugging skills

Consult the official documentation for the installed library versions before integrating new dependencies.

Prefer `@xyflow/react` if it fits the existing frontend architecture, but first evaluate the installed libraries and existing conventions.

Avoid unnecessary dependencies and parallel implementations of existing functionality.

---

# 4. Visual Workflow Editor

Create a new dashboard section:

**Bot Experience Studio → Workflows**

Required pages:

1. Workflow List
2. Create Workflow
3. Workflow Editor
4. Workflow Preview / Simulator
5. Workflow Versions
6. Workflow Settings

### Main Editor Layout

The editor should provide four primary regions:

**A. Workflow Header**

Display:

- Workflow name
- Store
- Assigned bots
- Current version
- Draft status
- Validation status
- Last saved time
- Save
- Validate
- Preview
- Version history

Support unsaved-change indicators and concurrent-edit conflict detection.

**B. Node Palette**

A searchable, categorized panel containing the available workflow nodes.

Users can drag nodes onto the canvas or add them through keyboard-accessible controls.

**C. Visual Canvas**

Support:

- Drag and drop
- Node connections
- Zoom
- Pan
- Fit to view
- Minimap
- Multi-selection
- Copy and paste
- Undo and redo
- Delete
- Alignment and automatic layout
- Connection validation
- Keyboard navigation

**D. Properties Panel**

Selecting a node should display its editable configuration.

Forms must be driven by a typed configuration schema rather than hard-coded separately for each workflow.

Support field-level errors, defaults, help text, and conditional settings.

### UX Requirements

Use the existing dashboard design system.

Support Persian RTL text while preserving natural usability for technical identifiers and workflow diagrams.

The editor must work well on desktop.

Provide a usable responsive alternative for mobile and tablet rather than forcing a cramped full-canvas layout.

Handle loading, empty, invalid, saving, error, and conflict states.

Avoid decorative or nonfunctional buttons.

---

# 5. Workflow Node Types

Design an extensible node schema with stable type identifiers.

Implement the following initial node families.

## Entry and Control Nodes

- `start`
- `end`
- `cancel`
- `condition`
- `switch`
- `wait_for_input`
- `delay`
- `go_to_step`

Every workflow requires exactly one Start node.

Multiple valid terminal nodes may be supported.

## Message Nodes

- `send_text`
- `send_photo`
- `send_video`
- `send_document`
- `send_media_group`, only where supported

Message settings must include appropriate platform capabilities and constraints.

Media should reference the existing media infrastructure rather than hard-coded URLs.

## Interaction Nodes

- `show_buttons`
- `ask_text`
- `ask_number`
- `ask_phone`
- `ask_email`
- `ask_photo`
- `ask_document`
- `ask_choice`
- `confirm`

Support required/optional fields, retry behavior, error messages, and cancellation.

## Commerce Nodes

Define integration contracts for:

- `show_categories`
- `show_products`
- `show_product_details`
- `select_product`
- `select_quantity`
- `add_to_cart`
- `view_cart`
- `start_checkout`
- `show_order_status`

Reuse existing Backend commerce services.

Do not reimplement Cart, Checkout, Inventory, pricing, or product visibility logic.

## Business Process Nodes

Define extensible contracts for:

- `create_support_request`
- `create_return_request`
- `request_admin_approval`
- `notify_admin`
- `request_wholesale_access`

A node must never be presented as executable when its Backend action is unavailable.

Implement schema, configuration UI, and validation for these nodes.

Backend execution contracts may remain unavailable until the relevant Action Registry or Runtime exists.

---

# 6. Workflow Definition and Persistence

Create a canonical, versioned workflow definition.

The persisted format must be independent of the React Flow rendering model.

The canonical schema should support:

- Workflow ID
- Store ID
- Workflow key
- Name
- Description
- Status
- Schema version
- Workflow revision
- Assigned Bot IDs
- Entry-point definitions
- Nodes
- Edges
- Typed node configurations
- Conditions
- Variable declarations
- Error handling
- Timeout policies
- Platform constraints
- Creation and modification metadata

Maintain a clean separation between:

1. Workflow business definition
2. Visual editor layout metadata
3. Runtime session state, introduced later

Do not store execution state in the workflow definition.

Do not put executable JavaScript, Python, or arbitrary code in workflow configuration.

Use stable node IDs and deterministic serialization.

Provide Backend APIs for creating, listing, reading, editing, deleting drafts, validating, and managing workflow versions.

Persistent storage must use the existing Backend architecture and database conventions.

Do not rely on browser local storage as the source of truth.

---

# 7. Multi-Store and Multi-Bot Support

Every workflow belongs to exactly one Store.

A workflow may be assigned to:

- One bot
- Multiple selected bots
- All eligible bots within its Store

Use the existing Bot Registry and Store relationships.

Never assume there are only two bots.

Allow both Telegram and Bale bots to use the same workflow definition where their capabilities permit it.

A bot from another Store must never be assignable.

Integrate authorization with the authenticated administrator's Store permissions.

The future Runtime must be able to resolve the correct workflow through `BotContext`.

Do not bind a workflow to a specific Cloudflare Worker deployment.

Worker topology must remain independent from workflow ownership.

---

# 8. Telegram and Bale Capability Awareness

Introduce or reuse a centralized Platform Capability contract.

The editor must understand which node configurations are supported by each platform.

Consider:

- Inline keyboards
- Reply keyboards
- Callback payload constraints
- Text length limits
- Media types
- Media size limits
- File upload/download behavior
- Message editing
- Button types
- Platform-specific payment integrations

Verify actual Telegram and Bale capabilities against their official documentation and existing adapters.

Do not assume feature parity.

When assigned bots have different capabilities:

1. Clearly identify incompatibilities.
2. Allow platform-specific configuration overrides when appropriate.
3. Validate each target platform independently.
4. Prevent activation of incompatible workflow versions.

Do not store sensitive business state inside callback payloads.

Keep callbacks compact, server-resolvable, and tamper-resistant.

---

# 9. Dynamic Buttons and Menu Configuration

Implement a visual button editor.

Each button may contain:

- Label
- Stable key
- Button type
- Target node or supported action
- Visibility condition
- Platform-specific configuration

Support:

- Adding and removing buttons
- Reordering
- Button rows
- Branching
- Conditional visibility
- Back
- Cancel
- Main menu

A button may point to another workflow step.

Buttons must not bypass Backend authorization or business rules.

Keep the workflow navigation model independent from platform-specific keyboard serialization.

Entry-point definitions must prepare for future integration with `/start`, commands, menu items, and internal workflow transitions.

Do not automatically replace the existing customer-facing menu system during this phase.

---

# 10. Variables, Conditions, and Validation

Implement a safe, typed workflow variable model.

Supported initial types:

- String
- Integer
- Decimal
- Boolean
- Date
- Datetime
- Enum
- Supported structured references, such as product, order, or customer IDs

Avoid arbitrary objects and unrestricted expressions.

Provide a visual condition builder supporting typed operators, including:

- Equal
- Not equal
- Greater than
- Less than
- Contains
- Exists
- Is empty
- AND
- OR

Only allow whitelisted operations.

Never use `eval` or arbitrary JavaScript expression execution.

Variables must be scoped appropriately.

Do not expose another customer’s information or administrative secrets.

Provide graph validation for:

- Missing Start node
- Duplicate Start nodes
- Unreachable nodes
- Dangling connections
- Invalid transition targets
- Missing required configuration
- Unsupported platform capabilities
- Missing Backend action contracts
- Invalid variable references
- Invalid condition types
- Missing terminal paths
- Unsafe or unintended cycles
- Invalid Store or Bot assignment

Cycles should be supported only when explicitly controlled by safe exit, retry, or iteration policies.

Show validation errors directly on affected nodes and in a centralized validation panel.

---

# 11. Workflow Preview and Simulator

Build a simulator into the dashboard.

The simulator should render a realistic customer conversation.

Provide platform selection:

- Telegram
- Bale

Allow selection of:

- Store
- Bot
- Workflow draft
- Simulated customer context

The simulator must support:

- Message rendering
- Button navigation
- User input
- Conditional branches
- Step history
- Back/cancel behavior
- Validation failures
- Unsupported action feedback

Show the currently active graph node as the simulation progresses.

Use a deterministic, isolated simulation interpreter.

Never execute real payment, inventory mutation, outbound Broadcast, or customer-affecting operations during simulation.

For Backend actions not yet implemented, show explicit simulation stubs.

Do not imply that a successful simulation proves real-world Runtime compatibility.

---

# 12. Drafts, Versions, and Publishing Readiness

Implement workflow draft management with explicit revision control.

Required capabilities:

- Create draft
- Save draft
- Duplicate workflow
- Rename
- Archive draft
- List revisions
- Compare revisions
- Restore an earlier definition as a new draft revision

Use optimistic concurrency protection.

Avoid silent overwrites during simultaneous edits.

The persistence model must prepare for immutable published versions and rollback.

**Do not activate newly designed workflows in live customer bots during Phase 1.**

If the production Workflow Runtime is not implemented, publishing must remain disabled with a clear explanation.

Do not implement fake publishing that merely changes the status label.

---

# 13. Backend and API Requirements

Use existing application services and authentication mechanisms.

The Next.js application must not directly bypass Backend authorization or database policies.

Backend validation is mandatory even when client-side validation succeeds.

Enforce:

- Store isolation
- Bot ownership
- Role-based authorization
- Input validation
- CSRF protections where applicable
- Safe serialization
- Revision conflicts
- Audit logging
- Request size limits
- Explicit error codes

Do not expose bot tokens, API keys, payment credentials, or other secrets in workflow definitions.

Make workflow operations idempotent where appropriate.

Preserve a clear foundation for future MCP tools such as:

- `workflow.create_draft`
- `workflow.update`
- `workflow.validate`
- `workflow.simulate`
- `workflow.compare_versions`

MCP must use the same Backend services as the dashboard.

Do not implement the actual MCP Server in this phase.

---

# 14. Example Workflow for Acceptance Testing

Implement one sample **Return Request Workflow** as a nonpublished draft fixture.

Expected behavior:

1. Customer selects "Request Return".
2. The workflow displays eligible orders.
3. Customer selects an order.
4. Customer selects a product.
5. Customer selects a return reason.
6. Customer adds an optional description.
7. Customer uploads an optional photo.
8. The workflow displays a summary.
9. Customer confirms or cancels.
10. The workflow reaches a completion state.

For actions unavailable in the current Backend, explicitly mark those steps as simulator-only.

The sample must demonstrate:

- Multiple node types
- Branching
- Variables
- Input validation
- Back/cancel
- Platform compatibility checks
- Visual preview

Do not create real customer return requests during this phase.

---

# 15. Testing and Quality Gates

Use the repository's existing test frameworks.

Implement meaningful automated coverage.

### Backend Tests

Verify:

- Workflow CRUD
- Schema validation
- Store isolation
- Bot assignment
- Revision conflicts
- Version restoration
- Permission enforcement
- Malformed graph rejection

### Frontend Tests

Verify:

- Canvas loading
- Node creation
- Node editing
- Connections
- Node deletion
- Undo/redo
- Autosave
- Validation indicators
- Version handling
- Unsaved changes
- Error handling

### End-to-End Tests

Cover:

1. Create a workflow.
2. Add Start and End.
3. Add message and buttons.
4. Add a conditional branch.
5. Save and reload.
6. Validate the graph.
7. Preview as Telegram.
8. Preview as Bale.
9. Modify and save a new revision.
10. Restore a previous revision.
11. Verify that cross-Store access is rejected.
12. Verify that unsupported nodes cannot be activated.

Run:

- Type checking
- Linting
- Unit tests
- Integration tests
- Relevant E2E tests
- Production build

Use Codespaces if available and properly configured.

Execute a **Test → Debug → Fix → Retest** loop until the relevant acceptance gates pass.

Never report a test as PASS unless it actually ran successfully.

---

# 16. Implementation Sequence

Execute the work in this order:

**Step 1 — Architecture Audit**

Inspect existing code, dependencies, and business-service contracts.

**Step 2 — Canonical Workflow Schema**

Define versioned data structures and validation rules.

**Step 3 — Backend Persistence and APIs**

Implement workflow storage, permissions, revision control, and validation.

**Step 4 — Visual Workflow Editor**

Implement the canvas, node palette, configuration panels, and editor interactions.

**Step 5 — Platform-Aware Configuration**

Connect Bot Registry and platform capability validation.

**Step 6 — Workflow Simulator**

Implement deterministic, side-effect-free previews.

**Step 7 — Versions and Draft Management**

Implement revision history, comparison, and restoration.

**Step 8 — Full Testing**

Run automated checks, fix failures, and retest.

**Step 9 — Documentation**

Document architecture, supported nodes, API contracts, limitations, and extension points.

Do not defer the working implementation to a future phase.

---

# 17. Repository and Git Rules

Create an isolated feature branch named:

`feat/bot-experience-workflow-builder`

Base it on the appropriate latest project development branch after inspecting repository state.

Do not discard unrelated changes.

Do not overwrite existing business logic.

Keep commits logically organized.

Preserve existing Telegram and Bale customer workflows.

Do not activate new workflows in production.

Do not enable GitHub Actions solely for this implementation.

---

# 18. Definition of Done

The phase is complete only when:

- The Workflow List works.
- Workflows can be created and persisted.
- The visual canvas is functional.
- Nodes and edges can be configured.
- The editor supports validation.
- Store and Bot assignment is enforced.
- Telegram/Bale compatibility is checked.
- The preview simulator works without real side effects.
- Workflow revisions can be inspected and restored.
- Unsupported Backend actions are clearly identified.
- Existing bot behavior remains unchanged.
- Relevant tests and the production build pass.
- The architecture is ready for Action Registry, Workflow Runtime, and MCP integration.

A visually attractive but nonfunctional editor is not an acceptable result.

---

# 19. Final Report

After implementation, report:

1. Branch name and final commit hash.
2. Implemented functionality.
3. Backend models, services, and endpoints added.
4. Frontend pages and components added.
5. Supported workflow nodes.
6. Telegram/Bale compatibility coverage.
7. Test results with exact commands and outcomes.
8. Remaining limitations.
9. Integration contracts required for Phase 2 — Action Registry.
10. Any architectural risks or intentionally deferred functionality.

**Proceed with implementation, testing, debugging, and retesting. Do not stop after writing the architecture plan. Do not claim that the complete Bot Experience Studio is implemented when only Layer 1 is finished.**