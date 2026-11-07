# Two-screen login implementation plan

> **For agentic workers:** Execute inline. User explicitly requested password-first login followed by a separate MFA screen, and diagnosis of rejected current MFA. Continue in the existing isolated UI worktree/PR.

**Goal:** Show credentials first and MFA only after the backend has verified the password; restore usable Persian/Arabic OTP input without weakening verification.
**Architecture:** Preserve the existing complete server verification contract. Its 428 `mfa_required` response follows successful password verification and creates no session. The client switches to a distinct MFA screen; credentials are retained only in a component ref for at most five minutes and are resubmitted for full backend verification. Back, expiration, reload, unmount and success clear them. No URL/history/storage credential persistence, MFA bypass or schema/API protocol expansion.
**Tech Stack:** Existing Next.js16.4/React19, Python/FastAPI and server-side MFA.
**Spec:** User's explicit latest request in this conversation. A separate screen within the login route is the implementation choice; it avoids placing credentials into a URL or persistent browser/server storage.

## Review focus
- Initial HTML contains no MFA input; invalid password never advances.
- Only a verified 428 advances; malformed replies cannot claim success.
- Wrong/replayed OTP stays on MFA; expired/replaced credentials return to password entry.
- Authenticator and recovery modes preserve both proofs and CAPTCHA/CSRF checks; no session before complete server proof.
- Pending secrets expire and clear on exit; async results cannot restore an abandoned attempt.
- Unicode digit/space normalization remains narrow and retains replay protection.

## Tasks
- [x] Reproduce Unicode OTP failures and initial-login MFA field regression before implementation.
- [x] Update LoginForm/Page heading with distinct credential/MFA screens, focus, Back, expiry and recovery mode; keep signed bridge enforcement.
- [x] Normalize supported OTP digits/spacing in server verification; expose allowlisted MFA service feedback.
- [x] Check only non-secret account/configuration metadata in QA. Never disable/reset/read the user's MFA proof automatically.
- [x] Run Python regression/security suite and full Next tests/type/lint/build, then review.
- [x] Update existing QA Codespace and use isolated fake auth responses to verify both screens, bad password/code, recovery, Back, expiry, RTL/themes. Real account login is user-owned; no secret extraction or MFA reset.

Prior component-loading browser harness acceptance remains pending and is kept separate from this login fix.

Evidence: scoped browser14PASS/22captures, Python25PASS, Next267PASS, Typecheck/Lint/BuildPASS. Full Python rerun had no final terminal result; report preserves that limit. Owner recovery is prepared for the user and was not executed by the assistant.
