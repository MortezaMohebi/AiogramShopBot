# Post-reset MFA enrollment and React theme recovery

Scope: Draft PR #19, QA only. No owner credential or MFA state is changed by these fixes or acceptance scripts.

## Reproduced failure

Authenticated `/account?enroll=1` rendered within `(console)` and requested StoreContext before enrollment. The backend correctly returned HTTP 428 `mfa_enrollment_required`; the account page consequently returned 500. Correlation: `ef897462-c91f-49fe-9165-2a2e7b53efbd`.

React 19 also warned when next-themes 0.4.6 created its inline ThemeScript during a fresh client mount. The negative Performance timestamp appeared during the failed render's recovery. No console filtering or Performance monkeypatch is used.

## Changes

- Personal `/account` sits outside the Store layout, with live session validation through the existing account backend. Only MFA controls appear while mandatory enrollment is incomplete.
- Shared protected GET reads redirect the exact enrollment-required response, including concurrent page/layout reads. Other permissions, account errors, and mutation failures retain their original enforcement.
- A pinned, checksum-verified postinstall patch skips ThemeScript only on the client, preserving the server anti-flash script. Both distribution formats and Docker install paths are covered. Unknown dependency versions/bytes fail installation until reviewed.
- Account session copy includes the implemented opt-in 30-day persistence and each server-issued expiration.

## Source verification

PASS: 287 Next tests, Typecheck through production build, Lint, Build. Independent review: no Critical/Important findings; 23 focused tests independently passed.

PASS: failing baselines reproduced enrollment dependency and client ThemeScript creation before fixes. Vendor-patch tests cover both entry points, idempotency, version mismatch, and rejection before writes.

BLOCKED locally: a separate offline clean npm ci lacked cached zustand archive. The existing installation's postinstall command passes. Clean installation in Codespace is pending.

PENDING: Codespace browser acceptance. `scripts/dashboard_enrollment_browser.mjs` prepares a guarded temporary synthetic fixture, checks real AccountPanel/Providers with intercepted writes, then removes only owned fixture files. It must be removed and the QA dev server restarted before the final Next MCP probe. This is component/runtime acceptance, not proof of a real owner's MFA enrollment.

Earlier Remember-me browser run on source a900957: PASS 14 checks, 22 captures, zero real authentication writes. Browser-native password saving remains controlled by the browser; the app offers credentials only after verified complete login.

The full dashboard sweep and unrelated component-loading Studio acceptance remain outside this focused fix and are not declared complete.
