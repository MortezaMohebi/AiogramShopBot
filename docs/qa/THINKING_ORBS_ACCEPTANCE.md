# Thinking Orbs integration

User-requested addition to `feat/dashboard-ui-ux-polish` / Draft PR #19.

## Implementation

`thinking-orbs` is installed through npm and pinned to **0.3.2** in the dashboard manifest and lockfile. The installed MIT notice is retained at `docs/licenses/thinking-orbs-MIT.txt`. The package has no additional runtime dependencies; it uses the dashboard's existing React 19.2.

The shared client `ActivityIndicator` renders a tuned 20px orb next to visible Persian progress text. It is used by the dashboard and Studio Workflow/Runtime/MCP loading boundaries, the lazy workflow-canvas fallback, and the login button while an existing request is pending. Skeleton geometry remains; simultaneous pulsing was removed from these loading screens. No progress animation is added to completed, unknown-outcome or approval-required business states.

- One polite status per loading boundary. Login retains its existing live region and suppresses an additional announcement inside the button.
- Decorative canvas is `aria-hidden`, unfocusable and has a fixed size. Visible labels remain readable without animation or canvas support.
- Normal surfaces follow the host theme automatically. Primary-button ink uses the contrasting palette through the existing theme provider.
- The installed library handles reduced motion, offscreen/tab visibility and effect cleanup. Pointer gravity is explicitly disabled.
- No authentication, permission, approval, request/receipt, persistence or business-runtime contract changed.

## Verification

| Check | Result |
|---|---|
| Four loading-boundary regressions | 4 FAIL before integration, 4 PASS after; real React/theme/orb modules used |
| Full dashboard unit suite | 251 PASS, 0 FAIL, 0 skipped |
| TypeScript / ESLint / production build | PASS |
| Focused source review | No Critical or Important findings; the test-fixture cleanup finding was corrected |
| Isolated Codespace UI matrix | 14 PASS, 62 screenshots, no browser exceptions |
| Responsive / RTL | 320, 390, 768, 1024, 1440px in light and dark |
| Theme contrast | Painted canvas verified; normal and primary-button ink change in opposite directions as required |
| Reduced motion | Stable painted frame; animation resumes after the preference changes |
| Actual login pending / error recovery | PASS in both themes at 320px with offline challenge/login responses; button disabled while pending and enabled after failure |
| Test fixture cleanup | PASS; temporary route removed |
| Final Next.js MCP | PASS — metadata, routes, compilation issues, errors and page metadata |
| Final agent-browser React check | PASS — mounted component tree after a same-session reopen |
| Visual inspection | Mobile light/dark contact sheets and both-theme pending login inspected |

The UI fixture renders actual production loading components using the existing Providers, font, tokens and shared controls. It is clearly labeled, contains no business data, runs only after the isolated-lab guard, and is removed afterward. Login checks use synthetic text and intercept both auth endpoints; they do not establish a real login or execute backend authentication. The earlier real MFA result remains separately recorded in `UI_UX_ACCEPTANCE.md`.

The first UI attempt timed out during development-route compilation. After stopping only the dedicated QA Next server, backing up its stale development output and restarting, the full scoped matrix passed. The initial Next MCP probe was attempted without an attached browser session and rejected its absent error-list fields; it was not reported as a pass. After a same-session agent-browser reopen, the final probe passed all five checks and returned empty compilation/configuration/session-error lists; the mounted React tree was observed.

This accepts the **orb integration's UI scope**. The broader authenticated dashboard route sweep and cleanup items from the earlier UI task remain separately tracked; these 14 checks do not replace that acceptance.

Screenshots/contact sheets and machine-readable results are in `docs/qa/thinking-orbs/`.
