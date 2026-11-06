# Layer 4 — Workflow Designer through WPMCP

Date: 2026-11-06. Bot base: `8c220af7b7cedc6c2c5ff717780e50625b433796`.
Bot branch: `feat/bot-experience-layer4-mcp-workflow-designer`.
Gateway repository: `MortezaMohebi/ai-wordpress-builder`.
Gateway base: staging `a12d65fa8a7304ddc0b7ad1e37fc5d68b0358ba4`.
Gateway integration branch: `feat/universal-gateway-bot-workflows`.
Requirements: [original execution brief](BOT_EXPERIENCE_LAYER4_BRIEF.md), subject
to the later owner direction below.

## Owner direction and scope

The owner directed that human approvals connect to WPMCP, which is intended to
become a universal MCP gateway. Use the shared gateway as the public MCP entry
point, authentication and human approval authority. This replaces the earlier
proposal for a bot-owned OAuth server, approval decision store and approval UI.
The bot application remains authoritative for Store membership, staff privileges,
workflow revisions, validation, business policies, publication and Runtime effects.

The full execution brief and instruction to continue authorize Layer 4. The
public gateway boundary is our engineering interpretation of the universal
gateway direction, not a separately confirmed choice. Future Odoo adapters,
platform renaming, a broad WordPress rewrite, merge, deployment and live customer
operations are outside scope. GitHub Actions and the integration stay default OFF.
Existing in-progress gateway login/CLI work in another checkout stays untouched.

## Verified baseline and current gap

The bot baseline is 1,154 Python PASS, with three inherited collection warnings.
Layers 1–3 provide strict definitions, CAS revisions, pure simulation, typed
Actions, immutable publication, durable sessions and receipts. Store is the
native tenant boundary. Staff roles and explicit Store memberships are separate
checks; no organization-wide administrator wildcard is invented.

Current WPMCP uses the official TypeScript MCP SDK, OIDC, PostgreSQL workspaces
and one authoritative approval transition, `aiwb.apply_approval_decision`.
Dashboard and request-bound MCP App surfaces share that decision authority.
Operation schema, approval authorization and signing depend on WordPress
connections, WordPress actor IDs and /wp-json/ paths. Bot requests cannot use
those contracts unchanged.

Add a provider-neutral connection boundary to the existing gateway. Reuse the
existing operation/approval tables and final decision authority. Preserve all
WordPress ownership/lease checks. Do not create a fake WordPress site for a bot,
or a second approval decision store in the bot database.

## Responsibilities

| Component | Responsibility |
| --- | --- |
| WPMCP public MCP | Existing standards transport, authentication, scoped discovery and namespaced tools/resources/prompts |
| WPMCP control plane | Workspace/connection authority, quotas, canonical review, decisions, durable continuation, central audit |
| Bot private adapter | Strict contracts, current native grants, Store/Bot isolation, shared services and redacted projections |
| Bot domain services | CAS, Change Sets, validation, simulation, publication, Runtime policies and effect receipts |
| Telegram/Bale Runtime | Existing Layer 3 pinned workflows and typed Actions |

Use shared services, not a container per customer. MCP handlers never access the
bot ORM or arbitrary URLs, SQL, shell, Python, Backend methods or generic Actions.

## Protocol and compatibility

Primary protocol and SDK references were verified:
https://modelcontextprotocol.io/specification/2026-07-28,
https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.3.0 and
https://py.sdk.modelcontextprotocol.io/run/authorization/.

The gateway already pins `@modelcontextprotocol/server` 2.3.1 and uses a stateless
server factory. Reuse its actual standards transport and compatibility support.
Do not introduce the previously proposed Python MCP sidecar, dependency upgrades
or another authorization server. Exercise real MCP HTTP with maintained SDK
clients. Do not advertise unsupported Tasks or fictitious transport sessions.
Unavailable external ChatGPT/Inspector checks are explicitly BLOCKED.

## Provider-neutral connection identity

Introduce a connection identity keyed by tenant, workspace and UUID with a
server-registered provider (wordpress or bot_workflows), bounded display name,
status and owner. Existing WordPress connections remain their native extension
with credentials, site claims and leases. Bot connections contain installation
and opaque native grant IDs. Origins come only from deployment configuration.

Move operation foreign keys to the common identity, preserving tenant/workspace
referential integrity. Synchronize WordPress lifecycle into it. Reuse
gateway_operations, gateway_approval_requests, events and the same final decision
helper. Existing WordPress entry points retain provider restrictions and lease
wrappers. Bot operations cannot claim WordPress paths, identities or signing keys.

The provider registry is closed code, not an arbitrary upstream proxy. Register
bot tools under `bot.` to avoid existing gateway workflow-tool collisions.
Discovery and resources are authorization scoped.

## Enrollment and independent native authorization

WPMCP's existing OIDC/resource-server owns MCP authentication. Do not copy access
or refresh tokens to the bot application or audit.

Enrollment requires an authenticated gateway workspace manager and a real bot
dashboard manager. A short-lived single-use pairing intent binds issuer,
subject/client, tenant/workspace, connection, installation and requested Stores
and scopes. The native manager confirms the exact grant through the existing
dashboard session and signed BFF. No model tool can grant its own staff identity
or expand a native grant.

Native grants persist explicit staff, Store, scopes, gateway identity, version
and revocation. Every request/effect reconstructs StoreContext from current
active staff/memberships and the grant intersection. Never forge an AdminSession
or accept tool-selected Store/Bot IDs as authority.

| Native scope | Capability and native Store requirement |
| --- | --- |
| workflow:read, workflow:validate, workflow:simulate | workflows.read; current member |
| workflow:write | workflows.write; editor |
| workflow:publish, workflow:rollback | workflows.publish; manager; exact approval |
| runtime:read | workflows.read; private Runtime projection |
| runtime:control | workflows.runtime.manage; manager; exact approval |
| actions:read, bots:read | workflows.read; safe Studio metadata |
| audit:read | audit.read; scoped Store management |

Fixed read-only catalog preview additionally needs catalog.read. It cannot run
cart/payment/notification mutations. Gateway workspace roles do not confer native
capabilities. Both authorities must allow the operation. Revocation stops new
requests and unstarted effects.

## Private delegation and approval proof

The fixed private /internal/mcp/v1 route accepts only strict registered
operations. Dedicated versioned Ed25519 delegation binds issuer, audience,
subject/client, tenant/workspace/connection/native grant, scopes, exact method,
target/body hash, correlation, issued/expiry times and nonce. Keys/origins are
administrator configuration. Reject unknown keys/algorithms/audiences/issuers,
stale/future proofs and body mismatches; no caller-selected key discovery URL.

Sensitive execution also requires a distinct signed approval proof bound to
gateway operation/approval IDs, requester, connection/grant version, Store,
workflow/source/proposed revisions, Change Set, exact canonical proposal digest,
binding fingerprint, operation kind and expiry. Introduce a generic proof
version; preserve the frozen WordPress proof format. The gateway signs only from
the persisted approved decision after rechecking requester/workspace/connection.

The bot records an external approval reference and native application receipt,
never its own editable approve/deny decision. Tool arguments, elicitation
responses, successful HTTP responses or approval booleans provide no authority.
Human decisions occur only on WPMCP's supported surfaces.

For the first bot provider, only the paired requesting subject may view or decide
its sensitive review. WPMCP role checks still apply, and the review surface checks
current native grant access before disclosing the diff or recording a decision.
An unrelated workspace administrator does not inherit Store visibility. Delegated
reviewers require a later explicit independent native grant design.

An authorized durable gateway dispatch claim is the start of an operation.
Gateway revocation prevents later claims and reports any already claimed operation
as in flight; it cannot promise to retract a signed request already in transit.
Native grant revocation independently serializes against native admission. A
revocation response distinguishes stopped future work from work already started.
Tests pause dispatch before native admission and exercise this exact ordering.

## Typed services and Change Sets

Implement the brief's context/platform/Bot/Action/workflow/revision tools,
validation/simulation, publication/rollback and Runtime inspection/control.
Include explicit Change Set and durable-operation status/list/cancel for recovery.
Use strict schemas, stable safe errors and bounded structured outputs/pagination.

Typed patches cover nodes, edges, variables, entries, Bot assignments and
platform overrides. Every mutation has expected revision, stable operation UUID
and canonical digest. Editable graph errors remain editable while strict schema,
ownership and budgets always apply. Create/template/replace/restore share risk
assessment; no mutation path bypasses staging.

Change Sets persist base/proposed definition and layout, normalized operations,
diff, validation/capability/Action findings, risk, owner/connection, expiry,
version and status. Pending/approved proposals are immutable. Ordinary draft
changes are low risk. Destructive changes or introduction/alteration of a
mutating Action are staged for WPMCP review. Publish, rollback and Runtime
control always need exact review.

Simulation uses only the existing pure simulator and bounded typed fixtures.
Authenticated resources expose schemas/catalogs/examples/scoped summaries.
Six prompts cover design, completeness, manual-flow conversion, platform
comparison, prepublication review and failure diagnosis. External/customer/
administrator text stays untrusted data, never prompt instructions.

## One approval and durable automatic continuation

Preparation returns immutable native intent, bounded exact diff, digest,
dependencies, customer impact, expiry and binding fingerprint. WPMCP persists
one operation and one approval per exact idempotent request. Its canonical review
shows the exact intent/hash. Compatible clients use that same review through
MCP elicitation/App UI; others receive its authenticated review URL.

An authenticated decision moves the existing gateway operation to READY or
DENIED. A durable gateway worker independent of the chat reloads original
normalized arguments, revalidates current gateway authority and obtains a fresh
request-bound proof before invoking the native commit endpoint. The bot checks
current grant/staff/membership, revision, Change Set, Bot state, platform/Action
availability, routing fingerprint and digest. Stale intent requires new review.

Both sides use stable operation IDs and native receipts. Record dispatch and
reconciliation phases and short claim leases. After a crash, read the native
receipt first. Timeout is not failure; never resend an unknown effect.
Native services may commit internally, so receipt reconciliation is mandatory.
Disconnection does not cancel approved work. Cancellation/revocation must report
an already committed effect accurately. Approval never enables forbidden unknown
delivery/Action retries or synthesizes customer consent.

## Administration, bounds and audit

Native Studio shows grants/connections, exact scopes/Store access, revocation,
external pending-operation references, safe audit and usage. Review links lead to
WPMCP and reflect verified status; no local approve/deny endpoint or button.
Use existing Persian RTL/themes/responsive components. Never expose saved tokens
or inaccessible Store names.

Gateway owns central user/workspace/connection quotas and approval limits.
Native Backend owns Store budgets and validation/simulation concurrency leases.
Use durable counters and bounded input/output: pages 50, patches 128, input
256 KiB, bounded outputs and fail-closed quotas. Audit safe controlled IDs, method,
outcome/code, timestamp and correlation; no raw proofs/secrets/customer answers.

## Acceptance sequence

1. Add generic connection identity and extend the existing approval authority.
   Prove WordPress leases/approvals and cross-provider isolation stay enforced.
2. Add native grants, signed private contracts and scoped services. Forged,
   cross-tenant, revoked and stale requests must fail closed.
3. Add patches/Change Sets, simulation/exact preparation, durable approved
   continuation and receipt reconciliation.
4. Register actual gateway tools/resources/prompts and native administration.
   Enforce quotas and audit.
5. Run the brief's product inquiry via real MCP/PostgreSQL/Fake Providers:
   compatibility failure/fix, both simulations, exact approval through a controlled
   test human-decision harness, auto resume, actual Runtime/Action receipt,
   duplicates, worker races, revision conflict and cross-tenant denial.
   Never approve our own operation in a real user's authenticated approval UI.
6. Run Python, gateway, Next unit/type/lint/build, PostgreSQL, browser and Relay
   gates, then fresh security/diff review. Report unavailable external clients
   BLOCKED. Documents or a Fake Approval Provider alone cannot certify integration.

Product display may need an additive scalar catalog-search projection produced
from actual visible results. Preserve existing pinned Action contracts. Never
substitute fixture results or expose arbitrary commerce execution.
