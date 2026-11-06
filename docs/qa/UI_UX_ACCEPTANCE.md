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
| Dashboard unit suite | PASS — 236 tests, including 11 retention receipt and 5 account feedback regressions |
| TypeScript | PASS |
| ESLint | PASS |
| Production build | PASS — final source snapshot, independent worktree dependencies |
| Independent source review | PASS after all three Minor findings and one follow-up were corrected; no open Critical/Important finding |
| Backend auth/session/MFA/lifecycle regressions | PASS — 31 tests in Codespace |
| Authenticated browser / PostgreSQL | BLOCKED — successful MFA retry and authenticated route checks not accepted |
| Next.js runtime MCP / agent-browser | PASS — tools, empty compile/runtime issue lists, mounted React tree |
| Login automated accessibility | PASS — axe, 0 violations and 0 incomplete checks |
| Login visual / responsive / RTL | PASS — 1440, 1024, 768, 390 and 320px in both themes |
| Other changed pages, dialogs and responsive layouts | BLOCKED — source review complete; browser acceptance pending |

Initial local build with an external node_modules symlink was rejected by Turbopack's filesystem root boundary. Copying the installed dependencies into this worktree resolved the environment issue without changing application configuration or dependencies.

The dedicated Codespace dev server needed a restart after archive source replacement: the watched `/login` route temporarily returned the not-found surface. Restart restored the actual route. This is recorded separately from product defects and all final acceptance checks must run on the settled source snapshot.

## Operational boundaries

No merge/deployment, production setting change, live message, live payment or customer-bot activation is part of this UI task. GitHub Actions remain disabled. Dedicated synthetic QA data and Fake Providers are used. Automated accessibility checks and visual inspection do not imply exhaustive assistive-technology certification.

## Browser status and handoff

**Acceptance is incomplete.** Draft PR #19 remains a review checkpoint, not a production-readiness claim.

Observed in the Codespace before access was blocked:
- Three initial browser checks passed: no login filler, five-width/both-theme login reflow, and password visibility/invalid-password/error-focus behavior.
- The missing-MFA response was displayed correctly. A subsequent valid-MFA retry stayed on login and showed a network error; no successful dashboard navigation was observed. No production auth fix is justified until the request timings and server result are read.
- The first test-script failure was an overly broad alert selector that also matched Next.js's route announcer. It is now scoped to the main content.
- The real login page mounted in agent-browser with React introspection. Its axe scan reported 33 passes, 0 violations and 0 incomplete checks.
- Next MCP returned empty compilation issue, configuration-error and session-error lists.
- Backend auth/session/lifecycle tests passed 31/31 in the dedicated container.

The last instrumented browser run was started against the then-current QA source. Its terminal output `/tmp/ui-browser-diagnostic.log` and evidence `/tmp/dashboard-ui-browser/evidence.json` were not read after the browser-origin block. The most recent three heading-level changes and preserved account feedback unit tests are host-verified; they have not been applied or browser-tested in QA.

Automatic approval review rejected further observation of `https://obscure-space-couscous-p7w6p4jrrxv3j59.github.dev`, stating that the origin approval gate did not grant access and a retry after the prior browser security denial posed unacceptable risk. Browser access was not bypassed. Local source work and GitHub publication continued independently.

Resume only after approved Codespace access:
1. Read the last instrumented run and safe request timings/statuses before changing auth behavior. Preserve network-error versus confirmed-login distinctions.
2. Verify the final feature-branch source matches the QA checkout, then complete the 38 static routes, available detail routes, dialog focus checks and key layouts at all planned sizes.
3. Check activation/error fallback headings, category dialog, report period, retention preview count, CAPTCHA widget/failed-provider paths, role restrictions, logout and expired-session handling.
4. Inspect the saved viewport screenshots, resolve any browser defects, and rerun relevant checks. Publish bounded evidence and update this ledger.
5. Log out synthetic QA sessions and stop only this task's isolated services. Existing five project services must remain untouched.

Last known QA services: dedicated PostgreSQL, Redis, API and Next dev were running. Their final state and active synthetic sessions could not be verified or cleaned up after the origin denial. No live messenger or payment provider was configured.
