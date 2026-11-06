# Dashboard UI/UX acceptance

Branch: `feat/dashboard-ui-ux-polish`.
Base source tree: Layer 4 verified snapshot `6569dcbd16e9237130a8ebd07b355946ed1bd2b1` (remote commit `3ba77eae19c74472f1ab877f718290d8b80049c1`).

## Scope

Every dashboard page and major component was inventoried and reviewed. Detailed inventories/findings are in `UI_UX_ROUTE_INVENTORY.md`, `UI_UX_COMMERCE_AUDIT.md`, `UI_UX_SETTINGS_AUDIT.md` and `UI_UX_STUDIO_AUDIT.md`. The eight official reference login pages and observations are recorded in `UI_UX_LOGIN_REFERENCES.md`.

Copy classifications: essential labels retained, helpful operational consequences retained, redundant headings/helper text removed, architecture/security filler removed from ordinary screens, technical identifiers retained in actual setup/diagnostic interfaces. No new marketing text or unsupported authentication flow was added.

## Changes

- Focused login with existing username/password, MFA, configured CAPTCHA and challenge enforcement; password visibility, pending/error feedback and support-detail reference remain.
- Existing semantic tokens and shared Input/Textarea/Button/PageHeading improved; no UI dependency added. Input boundaries and focus indicators have stronger contrast. Mobile text inputs use 16px to avoid focus zoom.
- Native modal dialog reused by mobile navigation and store selection: focus containment, background inertness, Escape and focus restoration. Navigation grouped by user tasks with an in-page skip link.
- Shorter Persian labels, specific CTAs, useful empty/filter states, visible form labels, mixed-direction identifiers, wrapping and table pagination boundaries.
- Corrected misleading report period, product-access KPI and workflow-publication instructions.
- Retention dry-run and explicit purge show only the count in a matching validated backend receipt. Existing deletion consent and confirmation protocol remain.
- Save conflicts, uncertain writes/delivery, approval scope and actual execution remain distinct. No automatic business-operation replay added.

## Verification ledger

| Check | Result |
|---|---|
| Dashboard unit suite | PASS — 231 tests, including 11 retention receipt regressions |
| TypeScript | PASS |
| ESLint | PASS |
| Production build | PASS — final source snapshot, independent worktree dependencies |
| Independent source review | PASS after all three Minor findings and one follow-up were corrected; no open Critical/Important finding |
| Authenticated browser / PostgreSQL | RUNNING |
| Next.js runtime MCP / agent-browser | RUNNING |
| Visual review / responsive / RTL | RUNNING |

Initial local build with an external node_modules symlink was rejected by Turbopack's filesystem root boundary. Copying the installed dependencies into this worktree resolved the environment issue without changing application configuration or dependencies.

The dedicated Codespace dev server needed a restart after archive source replacement: the watched `/login` route temporarily returned the not-found surface. Restart restored the actual route. This is recorded separately from product defects and all final acceptance checks must run on the settled source snapshot.

## Operational boundaries

No merge/deployment, production setting change, live message, live payment or customer-bot activation is part of this UI task. GitHub Actions remain disabled. Dedicated synthetic QA data and Fake Providers are used. Automated accessibility checks and visual inspection do not imply exhaustive assistive-technology certification.
