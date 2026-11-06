# Password-first login and MFA recovery

Application source: `01fb2bc5d95394cb3e22945c771b31e41e8874c2`, Draft PR19. The existing private QA Codespace runs this source on port3005, with its dedicated PostgreSQL database and no live providers.

## Behavior

The first screen contains username/password only. A verified backend428 `mfa_required` response moves to a separate MFA screen with its own title, focus, numeric keyboard and recovery-code option. No session is granted by428. Every MFA submission still passes username/password and the factor through the existing server verification. Invalid passwords never advance; rejected/replayed factors stay on the second screen. Credentials remain only in a component ref, expire after five minutes, and clear on Back, reload, unmount, success or a changed-password/locked response. No secret enters URL/history, persistent browser storage, cookies or hidden fields. CAPTCHA/CSRF and the allowlisted success destinations remain enforced.

Persian/Arabic OTP digits and copied whitespace normalize to the same six ASCII digits in the client and server. Other digit alphabets fail closed. The RFC6238 counter window and replay checks are unchanged. Known MFA configuration failures have safe Persian feedback.

## Owner-terminal recovery

`python -m scripts.manage_shop_staff reset-mfa shopadmin` is an explicit offline owner operation. It prompts for the current password and exact account-name confirmation. It permits only an active superadmin, clears the old enrollment, revokes all sessions, increments the session version and audits in one transaction. The existing server policy requires this role to enroll MFA again after login. The assistant did not execute this reset or enter any user credential.

For the QA preview:

```bash
cd /workspaces/AiogramShopBot-mcp-qa
docker compose --env-file .codespaces/mcp-qa.env \
  -f compose.workflow-mcp-qa.yml \
  exec api python -m scripts.manage_shop_staff reset-mfa shopadmin
```

## Evidence

| Check | Result |
|---|---|
| Localized OTP baseline | 3 FAIL; Persian/Arabic input raised TypeError, grouped input rejected |
| Initial-screen baseline | 1 FAIL; MFA input rendered before password proof |
| Focused Python security/recovery/lifecycle | 25 PASS, including real Argon2 proof and real SQLAlchemy/session effects |
| Dashboard unit suite | 267 PASS, 0 FAIL, 0 skipped |
| TypeScript / ESLint / optimized Build | PASS |
| Independent source/recovery review | No Critical or Important findings; timeout feedback corrected |
| Isolated browser run | 14 PASS, 22 captures; both themes and five widths |
| Browser scenarios | Initial/invalid password, verified transition, Persian OTP rejection, recovery success, Back, malformed success, five-minute expiry, non-MFA redirect |
| Actual private preview | First screen verified through the forwarded login URL; MFA input absent |
| Real-account diagnosis | QA account active, MFA enabled, encryption key valid, last counter not ahead of clock; observed invalid_verification401 |

The browser run intercepts synthetic CSRF/auth replies on the real login page. It does not create a real account session, consume a user's TOTP/recovery code, alter MFA, or contact a provider. The synthetic success destination declares UTF-8; the initial harness run lacked that declaration and was corrected before the passing rerun. Evidence/captures are retained under `docs/qa/login-steps/`.

A broad Python run before the test-fixture correction recorded1268PASS/1FAIL: the legacy global passlib placeholder cannot verify its own `hashed:` output. The focused recovery fixture now uses real Argon2 verification; all25 focused tests pass. The later full run did not return a terminal result before its host session disappeared, so no full-suite PASS is claimed for that rerun.

The component-skeleton Studio harness and the earlier full authenticated dashboard sweep remain separate pending scopes. The preview is intentionally left running for the user; the scoped test browser closes. No merge, production deployment, live messenger/payment operation or automatic MFA reset was performed.
