# Recent-login MFA setup acceptance

User request: do not ask for the password again on first MFA setup immediately after successful login.

## Result

The setup card sends an empty JSON object and contains no password field. The backend reuses the existing five-minute recent-auth timestamp of this live, owned, revocable session. The browser does not retain/replay the login password or supply authority timestamps. Expired proof offers sign-in again. Successful in-account reauthentication also restores optional-role setup.

Explicit password proof remains supported for older dashboards during rollout. Password changes, username changes and MFA disable keep their existing explicit-proof requirements. No schema change or new lifetime setting was introduced.

## Verification

| Check | Result |
| --- | --- |
| Signed HTTP enrollment, expiry, remembered sessions, strict payloads, mid-request authority invalidation, existing MFA, legacy proof and other sensitive operations | PASS: 18 isolated SQLite/ASGI cases |
| Complete Python suite after lock correction | PASS: 1291 tests; 3 existing collection warnings for model classes named Testimonial/TestimonialPatch |
| Complete Next suite | PASS: 289 tests |
| ESLint and production Build including Typecheck | PASS |
| PostgreSQL lock inversion before correction | REPRODUCED: SQLState 40P01, probe commit 556e684 |
| Same PostgreSQL concurrency after correction | PASS: enrollment and competing session validation, probe commit 2ab16c4 |
| Owned PostgreSQL schema cleanup, both probes | PASS |
| Real AccountPanel/Providers browser acceptance | PASS: 12 checks, 10 captures, both themes; 320/390/768/1440px, keyboard activation, setup/confirmation/recovery, stale proof and renewed proof |
| Real owner MFA enrollment/reset | NOT RUN; remains an owner action |
| Final ordinary QA service restart and Next MCP/React | PENDING |

The browser uses a guarded synthetic account fixture and intercepted account endpoints. It made zero real authentication writes. Expected HTTP 403 responses for expired proof are recorded separately from unexpected console/runtime errors. Backend proof authorization is covered by real signed HTTP/database tests and is not inferred from browser stubs.

## Review corrections

1. The explicit-proof compatibility path initially held Profile before Session, reversing middleware order. A deterministic real-PostgreSQL race reproduced the deadlock before correction. The route now acquires Staff, Session, then Profile; the exact same workload completed after the fix.
2. An expired optional-MFA setup could retain its sign-in-only state after a successful existing reauthentication action. The browser reproduced the missing setup button before the state reset was added, then passed the renewed-proof path.

Acceptance snapshot: probe 2ab16c4 plus the single verified recovery-state line. The tested AccountPanel blob is `7272f4f7b1fd06c076270a060e8622371c8a77bf`. The final source commit contains those same tested bytes.

Evidence will be retained in `docs/qa/mfa-recent-login/`. Existing broader dashboard acceptance remains Draft; this report is scoped to the requested enrollment UX. The assistant did not change any owner's password, MFA key or provider settings.
