# Dashboard UI/UX acceptance

Branch: `feat/dashboard-ui-ux-polish`.
Base source tree: Layer 4 verified snapshot `6569dcbd16e9237130a8ebd07b355946ed1bd2b1` (remote commit `3ba77eae19c74472f1ab877f718290d8b80049c1`).

## Scope

Every dashboard page and major component was inventoried and reviewed. Detailed inventories/findings are in `UI_UX_ROUTE_INVENTORY.md`, `UI_UX_COMMERCE_AUDIT.md`, `UI_UX_SETTINGS_AUDIT.md` and `UI_UX_STUDIO_AUDIT.md`. The eight official reference login pages and observations are recorded in `UI_UX_LOGIN_REFERENCES.md`.

Copy classifications: essential labels retained, helpful operational consequences retained, redundant headings/helper text removed, architecture/security filler removed from ordinary screens, technical identifiers retained in actual setup/diagnostic interfaces. No new marketing text or unsupported authentication flow was added.

## Changes

- Focused login with existing username/password, MFA, configured CAPTCHA and challenge enforcement; password visibility, pending/error feedback and support-detail reference remain.
- Existing semantic tokens and shared Input/Textarea/Button/PageHeading improved; one subsequently requested loading dependency is documented in `THINKING_ORBS_ACCEPTANCE.md`. Input boundaries and focus indicators have stronger contrast. Mobile text inputs use 16px to avoid focus zoom.
- Native modal dialog reused by mobile navigation, store selection and category editing: focus containment, background inertness, Escape and focus restoration. Navigation grouped by user tasks with an in-page skip link.
- Shorter Persian labels, specific CTAs, useful empty/filter states, visible form labels, mixed-direction identifiers, wrapping and table pagination boundaries.
- Corrected misleading report period, product-access KPI and workflow-publication instructions.
- Retention dry-run and explicit purge show only the count in a matching validated backend receipt. Existing deletion consent and confirmation protocol remain.
- Save conflicts, uncertain writes/delivery, approval scope and actual execution remain distinct. No automatic business-operation replay added.

## Verification ledger

| Check | Result |
|---|---|
| Dashboard unit suite | PASS — 254 tests, including receipt, account-feedback, Store-scope, CAPTCHA loading-boundary and media-thumbnail regressions |
| TypeScript | PASS |
| ESLint | PASS |
| Production build | PASS — final source snapshot, independent worktree dependencies |
| Independent source review | PASS after all three Minor findings and one follow-up were corrected; no open Critical/Important finding |
| Backend auth/session/MFA/lifecycle regressions | PASS — 31 tests in Codespace |
| Authenticated browser / PostgreSQL | PARTIAL / FAIL — password + MFA passed; 36 route/viewport cases passed, then Chromium crashed on /orders at 1280px |
| Next.js runtime MCP / agent-browser | PASS — tools, empty compile/runtime issue lists, mounted React tree |
| Login automated accessibility | PASS — axe, 0 violations and 0 incomplete checks |
| Login visual / responsive / RTL | PASS — 1440, 1024, 768, 390 and 320px in both themes |
| Other changed pages, dialogs and responsive layouts | PARTIAL — Store, mobile-menu and category dialogs passed; full route/viewport and final-source acceptance pending |

Initial local build with an external node_modules symlink was rejected by Turbopack's filesystem root boundary. Copying the installed dependencies into this worktree resolved the environment issue without changing application configuration or dependencies.

The dedicated Codespace dev server needed a restart after archive source replacement: the watched `/login` route temporarily returned the not-found surface. Restart restored the actual route. This is recorded separately from product defects and all final acceptance checks must run on the settled source snapshot.

Additional browser-driven fixes:
- Explicit forward/reverse Tab containment in the shared native dialog, preserving Escape and focus restoration. The mobile drawer remains on the right in RTL.
- Current-store Settings branding remains available when unrelated global controls return the backend's exact `409 store_scope_not_supported`. Restricted connection, relay and retention sections show Store-selection guidance. Other conflicts, permission denials and service failures remain errors; no backend access rule changed.
- Visible Turnstile and reCAPTCHA v2 widgets request their documented compact layout for the 280px login content width at a 320px viewport. Token handling and server verification remain unchanged. Four lifecycle regressions pass; offline SDK browser layout testing is pending.
- The Next.js development badge is disabled because its mobile position covered the navigation trigger. Framework compile/runtime diagnostics remain available; production UI is unchanged.
- Product feedback preserves unknown save outcomes instead of claiming a confirmed failure.

## Operational boundaries

No merge/deployment, production setting change, live message, live payment or customer-bot activation is part of this UI task. GitHub Actions remain disabled. Dedicated synthetic QA data and Fake Providers are used. Automated accessibility checks and visual inspection do not imply exhaustive assistive-technology certification.

## Browser status and handoff

**Acceptance is incomplete.** [Draft PR #19](https://github.com/MortezaMohebi/AiogramShopBot/pull/19) remains a review checkpoint.

After the user authorized reopening the private Codespace, real password and MFA login succeeded. The earlier retry timeout came from synchronous Docker preparation of the synthetic MFA proof blocking Playwright's request-interception event loop. The harness now prepares the proof asynchronously; production authentication did not need a change.

The latest observed browser run passed seven checks before the route inventory: focused login copy, five-width/both-theme login reflow, password/error behavior, real MFA login, Store dialog keyboard behavior, mobile-menu keyboard/RTL behavior, and category-dialog keyboard behavior. It then passed 36 route/viewport cases (18 routes in desktop light and mobile dark). The next case, `/orders` at 1280px, failed with a Chromium renderer target crash. This is a failed acceptance run; it does not establish an application defect in Orders or a complete route pass.

Runtime investigation observed no cgroup OOM kill and no process-limit exhaustion. Chromium diagnostics did not identify a conclusive crash cause. A separate Next.js hydration warning included screenshot-injected inline `caret-color: transparent` attributes. Playwright documents that screenshots hide the caret by default. The harness now uses `caret: "initial"` and waits for mounted client controls before inspection; login readiness is demonstrated through password reveal/hide behavior. These harness corrections are syntax-checked but have not been rerun in the browser. They are not proof that the renderer crash is resolved.

The mobile-menu evidence theme label was also corrected: the harness explicitly applies light and dark before the corresponding captures. Unexpected console errors are collected separately from expected failed-login/permission responses.

### Later scoped recheck: Thinking Orbs

User requested adding `thinking-orbs`. It is pinned at 0.3.2 with the MIT notice retained. A fresh browser tab restored Codespace access. The orb integration passed a separate 14-check/62-capture matrix at five widths in both themes, including real-component loading fixtures and offline login pending/error UI. See `THINKING_ORBS_ACCEPTANCE.md`. This restores browser access and accepts that scope; the earlier full authenticated route sweep remains incomplete.

### Later scoped recheck: lazy media

User requested `lazysizes` for skeleton-backed lazy loading. It is pinned at 5.3.2 with its MIT notice retained. The media library and product editor use the existing private preview endpoint for raster-image thumbnails. The scoped browser matrix passed 13 checks and saved 12 views across five widths and both themes, including offscreen deferral, success/error/source replacement and a decoded no-JavaScript fallback. See `LAZYSIZES_ACCEPTANCE.md`. The full dashboard route sweep remains pending.

### Prior environment incident

During upload of the updated harness, browser control became unresponsive. A Codespace state read, packaged troubleshooting-documentation read, and runtime reset each timed out. The upload result could not be reconciled. This is a control-connection failure after restored authorization, not a new approval denial.

Independent local-browser verification could not proceed: Chrome's launch aborted because creation of a required process-singleton socket was denied (`Operation not permitted`). No sandbox or access restriction was bypassed. Unit, TypeScript, ESLint and production-build checks all completed successfully on the final local application source.

### Remaining broader dashboard acceptance

1. Codespace access is restored for the orb recheck. Reconcile the full-dashboard harness upload before rerunning it. Verify source hashes against the published follow-up commit. Do not change production auth to compensate for a test-tool failure.
2. Complete all 38 static routes and available detail routes, including workflow editor/settings/preview/versions and available product/staff details. The current first-level detail-link discovery may need recursive traversal. If a renderer crashes again, preserve its diagnostics; no failed case may be silently counted as passed.
3. Complete settings save/reload/restore, reauthentication, original-Store retention dry-run, disabled/viewer restrictions, logout, expiration and activation errors. The harness is prepared; these checks are pending in the final run.
4. Run offline SDK CAPTCHA layout/error tests for Turnstile, reCAPTCHA v2 and unavailable configuration at 320/390/1280px in both themes. The script blocks login POSTs; no real challenge or live verification is part of that layout test.
5. Review the final screenshots at planned widths/themes and rerun Next.js MCP/agent-browser checks against the settled final source. Prior login axe results were 33 passes, 0 violations and 0 incomplete; prior framework results had empty compile/configuration/session-error lists. They do not certify the later source snapshot.
6. Log out/revoke only synthetic QA sessions and stop only this task's dedicated services, retaining data volumes and leaving the original project services untouched.

The latest run's evidence is in the dedicated Codespace at `/tmp/dashboard-ui-scope/evidence.json`; its terminal log is `/tmp/ui-browser-scope.log` and framework log `/tmp/ui-next-scope.log`. These diagnostics are remote and were not republished as final screenshot evidence. Dedicated PostgreSQL, Redis, API and Next dev were last observed running. Final remote cleanup remains unverified because the control connection timed out. The temporary host-side browser did not start and no host-side login occurred.

### Component skeletons and deferred Studio forms

The authorized component-loading changes are implemented locally. Products streams results below its search controls; Orders streams the list and permitted review queue independently; Dashboard waits once for `/overview`; Studio imports inspector/settings forms when rendered. All 265 dashboard tests, Typecheck, Lint and the production Build pass. An independent source review found no Critical or Important issues. See `COMPONENT_SKELETONS_ACCEPTANCE.md`.

Browser acceptance for this change is **blocked**. Automatic approval review denied uploading the source delta to the private Codespace, citing absent explicit destination authorization. A local alternative also failed: Chromium aborted because required socket creation was denied (`EPERM`), and agent-browser could not start. No controls were bypassed. Zero browser cases or screenshots are counted for this scope. The owned fixture was removed and the dedicated local Next server stopped; no remote source, service, session or data was changed in this attempt.
