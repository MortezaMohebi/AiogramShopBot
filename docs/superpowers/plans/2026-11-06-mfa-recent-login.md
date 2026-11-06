# Recent-login MFA enrollment implementation plan

**Goal:** Remove the repeated password prompt immediately after successful login.

**Architecture:** Reuse the existing backend-issued five-minute recent-proof window on the current revocable session. The browser sends an empty setup object; it cannot declare authority or extend the window. Older clients can still supply explicit password proof. Keep all other sensitive action contracts unchanged.

**Scope:** Existing isolated dashboard worktree and Draft PR #19; update only the dedicated private QA Codespace. No credential reset, real MFA enrollment, provider calls, production rollout, migration, or merge.

## Task 1: Backend proof and account UI

- [x] Reproduce the repeated-password screen with real component rendering and signed HTTP tests.
- [x] Permit first setup with a live, owned, recently authenticated session; preserve explicit-proof compatibility.
- [x] Reject stale/remembered proofs, browser authority fields and concurrent revocation/version/expiry/active changes.
- [x] Remove the setup password form and show sign-in recovery when recent proof expires.
- [x] Preserve password requirements for disabling MFA, changing password and renaming accounts.
- [x] Complete fresh review corrections and whole-suite verification; commit follows with the verified source.

## Task 2: PostgreSQL and browser acceptance

- [x] Reproduce the reviewed Session/Profile lock inversion in an isolated PostgreSQL schema (SQLState 40P01); remove the owned schema afterward.
- [x] Verify the corrected lock ordering against the same concurrent enrollment/session workload.
- [x] Exercise fresh, expired and renewed proof UI in both themes, keyboard and 320/390/768/1440px layouts.
- [x] Remove temporary fixtures and restart only QA services; verify PostgreSQL/Redis health and available Next MCP server checks.
- [ ] Browser-connected final Next/React introspection: blocked by daemon IPC and native preview URL policy; do not use another browser to bypass the block.
- [x] Publish verified source to the Draft and Codespace; retain acceptance evidence alongside it.

## Review decisions and ledger

- Use backend session proof instead of retaining/replaying the login password in the browser; existing short proof lifetime and CSRF remain authoritative.
- Preserve explicit-proof callers during rollout; their Session lock must precede Profile, matching middleware. The original inversion was reproduced before changing its ordering.
- Successful in-account reauthentication should restore optional-MFA setup after an expired proof; cover this recovery in the browser.
