# Approved scope: My Account, security/sessions, permissions, tracked connections

Base: 31ccd2ae5dab28e9749d0011fa18060e3f21180a

1. Preserve the posted ESLint fix; remove the remaining diagnosed warnings.
2. Add persistent session, profile/MFA, security audit and connection-operation
   tables, without altering legacy tables or dropping existing Codespace data.
3. Add an explicit outer FastAPI application: existing business routes remain
   mounted; new account/session endpoints take precedence over old auth routes.
   Every authenticated internal request must carry a server-issued session and
   an HMAC proof. Legacy SQLAdmin is not an alternative MFA/session bypass.
4. Ship My Account (display name/time zone, current-password rotation, optional
   TOTP + one-use recovery codes, per-session/all-other-session revocation and
   audit history), and an explicit fixed-role permission catalogue.
5. Replace ephemeral connection staging with durable, idempotent changes.
   Separate requested/applying/verified/failed/needs-review state. Apply through
   a supervised in-process controller, no Docker socket or arbitrary command.
6. Run behavioral SQLAlchemy/HTTP/unit tests, Python compilation, TypeScript
   checks available offline, and prepare live Codespace commands. Push atomic
   commits via the connected GitHub API, retaining PR #3 as Draft.

Constraints: no live bot calls here, no payments, no automatic message dropping,
no forced pushes, no user-data reset. Existing secrets never enter code/logs.

Execution note: container has Python/SQLAlchemy/cryptography and TypeScript, but
no Docker, Next.js, agent-browser or outbound DNS. Full next-dev-loop/build needs
Codespace verification; do not misrepresent local service tests as that result.
