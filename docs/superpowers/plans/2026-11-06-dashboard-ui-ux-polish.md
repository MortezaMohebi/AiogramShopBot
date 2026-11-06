# Dashboard UI and copy implementation plan

**Goal:** Simplify the existing Persian dashboard and verify its behavior in the running application.
**Architecture:** Keep Next.js server pages, existing semantic tokens and signed backend bridge. Correct shared primitives first, then scoped page copy without altering domain operations.
**Spec:** User attachment Pasted text(10).txt, 2026-11-06.

## Constraints
- Preserve authentication, MFA, CAPTCHA, permissions, receipts and uncertain outcomes.
- No new UI dependencies, live provider operations, deployment or merge. GitHub Actions remain off.
- Existing teal tokens, Vazirmatn, Persian RTL and both themes remain.

## Review focus
- 320px RTL reflow and mixed-direction identifiers.
- Keyboard focus containment/restoration and Escape for overlays.
- Invalid credentials, expired session, MFA and CAPTCHA failures.
- Unknown mutation results remain unknown until authoritative readback.
- Domain warnings remain accurate after copy simplification.

## Tasks
- [x] Inventory routes/components and inspect the eight named official login pages (JS-only results require browser follow-up).
- [ ] Simplify login and shared controls, shell and navigation; verify login/error/keyboard behavior.
- [ ] Audit and fix commerce routes and domain controls.
- [ ] Audit and fix settings, bots, stores, account and staff routes.
- [ ] Audit and fix Studio, workflows, runtime and MCP controls.
- [ ] Run unit/type/lint/build checks; exercise changed routes in isolated PostgreSQL QA and browser.
- [ ] Review screenshots at desktop/laptop/tablet/mobile sizes in both themes; debug and retest.
- [ ] Independent final review, evidence report and reviewable branch.
