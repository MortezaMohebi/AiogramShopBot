# Proxy-safe login regression

The reported redirect was reproduced exactly: `https://localhost:3005/login?error=security_check_failed`.

The port 3005 development process used an older checkout and an empty `NEXT_ADMIN_PUBLIC_ORIGIN`. Its internal request URL became the absolute auth redirect destination. The form also allowed a native submission before React hydration, which bypassed the browser's JSON/CSRF challenge handler and correctly failed the security check, then followed that bad redirect.

Auth navigation now uses a fixed relative `Location` header. Neither internal request URLs nor forwarded Host headers choose the destination. The server-rendered submit button stays disabled until the secure client handler hydrates. Missing/cross-site CSRF challenges remain rejected, and password/MFA/session policy is unchanged.

Port 3005 now runs the Registry-only checkout with the explicit Codespaces HTTPS origin and the active administrative Backend on 8096. Port 3006 remains the production Dashboard.

Validation: 309 frontend tests, Typecheck, Lint and production Build passed. Three newly added assertions failed against the original behavior and passed after the fix. Runtime acceptance and Next.js evidence are stored in `login-proxy/`. Only an owned, disposable synthetic account is used for login/MFA acceptance; owner credentials are never read or reset.

Final runtime acceptance: 10 PASS on development port 3005 and 10 PASS on production port 3006; both exercised real Backend rejection, separate MFA, successful synthetic login, Remember me and CSRF denials. No uncaught browser errors. All owned synthetic accounts, grants and sessions were removed. Independent security review found no Important issues. The production image build and restart passed after releasing development build memory.
