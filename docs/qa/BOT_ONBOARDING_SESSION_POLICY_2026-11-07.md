# Bot onboarding session policy

Requested behavior: a signed-in administrator can add a bot and complete its token verification and receiver activation without repeating their password or MFA. Destructive bot operations retain recent MFA verification. Login authentication, session revocation, role permissions, Store ownership, credential encryption, provider identity checks, receiver revision checks, and worker lease checks remain enforced.

## Implementation

Only these exact POST routes bypass the repeated five-minute proof: creating a Registry bot, staging its token, verifying its identity, staging its receiver, and activating its verified draft. Every DELETE and all credential-revocation, bot-state, settings, commerce, Relay, and unknown paths retain their prior step-up checks. Receiver activation accepts only its expected revision, and the UI no longer requests password/MFA for activation.

There is currently no permanent bot-deletion API. It remains unavailable. Regression tests send DELETE/revoke/disable requests against a bot with persisted credentials using expired proof: each is rejected and all records remain.

The onboarding regression exercises the actual signed HTTP boundary, encrypted credential storage, getMe verification, receiver staging, and activation with an expired step-up timestamp. Only provider I/O and polling startup are fake. Unauthorized roles and revoked sessions remain rejected. A rendered production Receiver panel regression confirms that activation has no password/MFA fields.

## Verification

- Python: 1315 PASS; three pre-existing pytest collection warnings.
- Next.js: 316 PASS.
- Typecheck, Lint, and production Build: PASS.
- Focused Python onboarding/security scenarios: 9 PASS.
- Scoped deployment: generated dashboard node_modules, Next.js caches/backups, and nested environment files are excluded from the API image; dashboard build caches/backups are excluded from its own image.

Runtime deployment and live bot activation results will be appended after verification. No provider token or administrator credential is recorded here.
