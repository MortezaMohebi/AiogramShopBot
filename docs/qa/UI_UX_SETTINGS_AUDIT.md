# Settings, bots and account UI audit

Scope: 12 route files, 13 block components, and two display/error helpers (`lib/bot-registry.ts`, `lib/account-control.ts`). Source review and fixes completed in the UI/UX worktree. No backend, dependency, authorization, payload or operation-state changes.

## Inventory and findings

| Routes | Finding and applied change |
| --- | --- |
| `/settings` | Removed database/implementation descriptions; shortened payment readiness and save messages; retained payment prerequisites and reauthentication guidance. |
| `/stores` | Replaced Store/Cart/Identity jargon with Persian domain labels; retained sharing/reconciliation consequences; added a create-store empty state. |
| `/bots`, `/bots/[id]` | Replaced migration/frozen-phase explanations with activation steps; named draft, Token, state and access actions clearly; removed raw relay error reflection; fixed empty audit text appearing beside existing state events. |
| `/bot-connections`, `/relay-workers` | Removed duplicate introductions and decorative security claims; retained allowlist, provisioning, MFA and unknown-result instructions required for technical setup. |
| `/staff`, `/staff/[id]/stores` | Used Persian role/store labels; removed the Odoo architecture analogy; clarified store access; added an unavailable-store state and disabled its unusable submit action. |
| `/permissions`, `/account` | Removed redundant subtitles; translated role labels; retained real password, MFA, recovery, session and notification policy information. |
| `/audit` | Removed the secrets-not-shown introduction; distinguished an empty history from no filter matches. |
| `/data-models/[model]` | Replaced Registry/SQL explanations with available user tasks. |

All blocks reviewed and edited: `bot-catalog-access-panel`, `bot-commerce-panel`, `bot-connections-panel`, `bot-profile-panel`, `bot-receiver-panel`, `bot-relay-routes-panel`, `shop-settings-form`, `customer-experience-policy-panel`, `telegram-transport-panel`, `connection-control-panel`, `staff-security-panel`, `account-panel`, `model-data-workbench` (under `dashboard-next/components/blocks/`).

Copy classifications applied: essential labels kept; helpful prerequisites/consequences retained; redundant subtitles removed; database/encryption internals removed from ordinary explanations; technical protocol/configuration identifiers retained where necessary to configure or diagnose a connection. No supported error recovery, account-security information or uncertain execution result was removed.

## UI and state fixes

- Customer menu rows and connection/bot action groups wrap; menu labels are no longer truncated. Repeated order selectors include the menu item's accessible name.
- MFA input codes use LTR direction. Filter values use bidi isolation; filter chips use field/operator display labels rather than backend keys.
- Account MFA QR images can shrink within a narrow card; security-event rows wrap.
- Request IDs and transport error codes remain available in expandable support details.
- Data search/grouping handles thrown connection failures with visible feedback. Import file/format controls are disabled while a request is pending.
- Search, grouping, store, staff and catalog screens have more specific empty states. Account success messages name the completed action.
- Known store, payment-account, receiver and relay states use Persian display labels; backend state keys remain unchanged.
- Account-control challenge/network/JSON failures now produce safe Persian messages instead of raw exceptions. Lost mutation responses still direct users to check status before retrying.
- Existing preview/apply, queued/running/unknown/completed, reauthentication and non-replay semantics remain intact. No live mutation was used for validation.

## Verification

| Check | Result |
| --- | --- |
| Bundled Next.js forms guide and repository AGENTS instructions | Read; existing Server Action and client request boundaries preserved. |
| ESLint on all 25 scoped TSX files and two helpers | Passed after final edits. |
| Five isolated account-control response/error checks | Passed: challenge failure, fetch failure, malformed JSON, allowlisted rejection and confirmed success; no live requests or mutation replay. |
| Scoped `git diff --check` | Passed after final edits. |
| TSX transpilation syntax diagnostics | Zero errors in the worktree's changed TSX files at the time checked. |
| Whole-app typecheck/build/tests and rendered browser review | Coordinated by the parent task; not claimed by this scoped audit. |

Remaining verification: desktop/mobile, light/dark, keyboard and protected account/bot workflows need the parent task's authenticated preview checks. The legacy bot-profile and bot-connections blocks were retained because safe deletion was outside this cleanup's purpose. Technical relay provisioning instructions intentionally remain in these administrative diagnostic interfaces.
