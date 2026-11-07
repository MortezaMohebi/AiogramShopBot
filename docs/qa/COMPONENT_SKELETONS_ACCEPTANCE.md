# Component loading skeletons

Status: source implemented and reviewed; browser acceptance blocked.

## Behavior

Products keeps authorized heading/actions/search outside a query-keyed Suspense boundary. The result table and matching pagination use one signed GET. Orders retains the role guard before any data read and streams the permitted manual-review queue separately from its order list. Finance never requests the queue. Dashboard retains a single `/overview` response for all metrics.

A known upstream 5xx becomes a local error with a read-only refresh button. It does not show an empty list or zero metrics. Redirects, authentication/permission failures, conflicts, throttling and programming errors propagate. Existing decision forms and server-action bindings are preserved; refresh never replays a mutation.

Studio dynamically imports Inspector and WorkflowSettings when rendered, with form-shaped fallbacks. The editor keeps ownership of draft, undo/redo, selection and save/unknown-outcome state. Existing canvas behavior is unchanged. Skeleton geometry uses current theme tokens, RTL layout and the global reduced-motion rules. No dependency was added.

## Evidence

| Check | Result |
|---|---|
| Initial production-page streaming regressions | 4 FAIL / 2 PASS before implementation |
| Focused regressions | 11 PASS, including non-5xx/redirect/error propagation |
| Full dashboard unit suite | 265 PASS, 0 FAIL, 0 skipped |
| TypeScript, ESLint, production build | PASS |
| Independent source review | No Critical or Important findings; focused tests independently passed |
| Planned browser matrix | BLOCKED; zero checks/captures credited |
| Local Chromium | Launch aborted: process-singleton socket creation denied (`EPERM`) |
| Local agent-browser | Daemon could not start; no React mount or Next session diagnostics claimed |
| Codespace upload | Denied by automatic approval review: explicit destination authorization absent |
| Cleanup | Owned fixture removed; dedicated local Next server stopped |

The reproducible browser harness is `scripts/dashboard_component_skeletons_browser.mjs`. It checks dedicated QA flags and empty live-provider credentials, creates owned temporary routes before Next startup, and refuses to overwrite an existing fixture. It renders production views/skeletons with synthetic data and controlled latency. It plans five widths × both themes, partial completion, errors/GET refresh, reduced motion and actual deferred Studio chunk delivery with selection changes. It blocks API mutations and external traffic, then removes the fixture. The harness is syntax-checked; none of those browser behaviors is claimed verified yet. Production-page unit tests separately exercise real fetch boundaries and permissions with controlled external reads.

No merge, deployment, messenger/payment operation, customer-bot activation, remote data change or authentication bypass was performed. Earlier orb/image acceptance and the unfinished full authenticated dashboard sweep remain separate scopes.
