# Layer 4 — verified implementation and handoff

Date: 2026-11-06. Implementation scope: complete. All locally executable
mandatory gates passed. Hosted ChatGPT/Codex attachment to this private lab is
BLOCKED pending an explicitly authorized public deployment and client setup.
No merge, production deployment, customer Bot activation, live message or live
payment was performed. The integration defaults OFF in both applications.

## Required 24-field handoff

| # | Field | Verified result |
| --- | --- | --- |
| 1 | Base branches | Native `feat/bot-experience-layer3-workflow-runtime`, `8c220af7b7cedc6c2c5ff717780e50625b433796`; WPMCP `staging/ci-platform-coverage-20261102`, `a12d65fa8a7304ddc0b7ad1e37fc5d68b0358ba4`. Both remote bases were rechecked and preserved. |
| 2 | Feature branches | Native `feat/bot-experience-layer4-mcp-workflow-designer`; WPMCP `feat/universal-gateway-bot-workflows`. |
| 3 | Final verified snapshots | Native implementation `e3b8bc7097617786799b4a84e19740c21d9a2f9c`, final executable QA/evidence `137f20b8c494c4c2324cd49071b93f1f583794f2`; WPMCP implementation `06697b7875c7b07f418db59291afce9ff5e461d5`, documentation `fd072392a0afd37b4a136d080a721f1366c26c8b`. Subsequent Native handoff commits contain documentation only; the Draft PR head records their exact final SHA. |
| 4 | Progress | 100% of the implemented Layer 4 scope after the final handoff commit. External hosted-client verification remains explicitly BLOCKED. |
| 5 | MCP specification | `2026-07-28`; the existing gateway protocol policy is preserved. |
| 6 | SDK | Official TypeScript MCP server `2.3.1`, Node adapter `2.1.1`, Fastify adapter `2.0.1`. |
| 7 | Transport | WPMCP public Streamable HTTP `/mcp`; fixed, signed private Native POST routes under `/internal/mcp/v1`. |
| 8 | Authentication | Existing WPMCP local/OIDC authentication; verified subject/client/workspace authority. Native independently checks purpose-separated Ed25519 delegation and approval proofs, exact HTTP bytes/target, expiry, nonce, current staff/membership/grant version and Store/Bot authority. Native human administration uses existing sessions, MFA, Signed Bridge and CSRF protection. |
| 9 | Scopes | Public `aiwb:read`/`aiwb:write`; Native `workflow:read`, `workflow:write`, `workflow:validate`, `workflow:simulate`, `workflow:publish`, `workflow:rollback`, `runtime:read`, `runtime:control`, `actions:read`, `bots:read`, `audit:read`, `catalog:read`. Effective access intersects current Native and gateway permissions. |
| 10 | Tools | 43 closed Native-backed `bot.*` tools plus `bot.connections.list` and `bot.operations.status`; existing WordPress tools remain available. Exact schemas are in `contracts/wpmcp/bot-workflow-tools-v1.json`. No arbitrary SQL, URL, ORM or Backend method executor is exposed. |
| 11 | Resources | Nine scoped resource families: workflow schema, node catalog, Action catalog, platform capabilities, validation codes, examples, draft summaries, publication summaries and Runtime summary. Four also have paginated templates, yielding 13 bot resource templates. |
| 12 | Prompt templates | Six inert templates: design, completeness review, manual-flow conversion, platform comparison, publication review and Runtime diagnosis. User-authored fields remain untrusted data. |
| 13 | Change Sets | Durable base/proposal/version/hash; typed patches; revision conflicts; separate validate/simulate/apply/cancel. Immutable proposal evidence recovers exact retries across process interruption, including an older proposal version after a newer edit. Sensitive proposals are frozen for gateway review. |
| 14 | Approval flow | WPMCP owns the sole MCP business approval decision authority and its existing shared operation/approval tables. Complete escaped Native evidence is bound to an exact hash, actor, connection, grant, Store, revision and expiry. Current Native authority is checked before disclosure, decision and dispatch. Native pairing is independent connection consent. |
| 15 | Auto-resume | Shared fenced workers continue after the human decision without a further model call. Receipt-first recovery settles a crash after Native commit without another effect. A fresh definitive pre-commit rejection finishes FAILED; previously dispatched or ambiguous work stays UNCERTAIN. |
| 16 | Runtime tools | Redacted Run inspection/diagnosis; prepared gate changes, retry/cancel and known-rejected delivery retry. Sensitive operations require exact WPMCP approval; unknown sends cannot be automatically resent. Existing Layer 3 execution and receipts are reused. |
| 17 | Dashboard pages | Native `/studio/mcp` and Store-independent `/account/mcp`; closed Next BFF for owned connection administration. WPMCP connection list/detail/enrollment/revocation and existing approval pages/App surface. Normal MFA, exact consent, unknown withdrawal recovery, RTL and responsive layouts were exercised. |
| 18 | Limits/quotas | Existing shared monthly quota, activity leases and circuits; default user concurrency 4/RPS 20, Store concurrency 4/RPS 40, simulation 2, validation 2, publication 1, pending approvals 20. Private input 256 KiB, response 2 MiB; immutable intent evidence 768 KiB. Server policy remains authoritative. |
| 19 | Audit | Native request/proposal/intent/domain receipts and administration/Runtime audit; WPMCP usage, approval and operation events. Real PostgreSQL readback confirmed exactly one approval decision, one completion event and one Native activation audit for the accepted publication. Private answers/uploads/tokens are excluded from public Runtime inspection. |
| 20 | Client compatibility | Developer HTTP client PASS; Inspector `2.14.0` authenticated Native profile PASS using `--protocol-era modern`. Its default legacy negotiation was rejected correctly. Existing WordPress/client compatibility regressions PASS. Hosted ChatGPT/Codex private-QA connection: BLOCKED; no public endpoint or client registration was created. |
| 21 | Test commands/results | Python 1,263 PASS; Next 220 PASS plus Typecheck/Lint/Build; gateway source 588 PASS and provider subset 60 PASS; Relay 14 PASS; cross-service PostgreSQL/Inspector/browser acceptance 18 PASS; Native browser 7 PASS; Runtime PostgreSQL regression 23 PASS; exact audit readback PASS. Commands and logs follow. |
| 22 | Remaining limitations | Three inherited Python collection warnings remain. Historical lint findings in legacy fixtures/adapters were not expanded into unrelated refactoring; targeted new/changed recovery and QA modules passed Ruff. Public hosted-client/card acceptance and production load capacity were not measured in this private lab. |
| 23 | Deferred capabilities | Additional universal-gateway providers, Odoo adapters, cross-workspace delegated reviewers, production rollout, live provider tests and public client onboarding. Current providers are WordPress and Bot Workflows. |
| 24 | Security/architecture risks | Deployment must pin trusted HTTPS origins, separate signing purposes and protect operator keys. Revocation stops new admission and cannot retract a previously committed effect. Unknown outcomes retain uncertainty; expired worker capacity leases can temporarily delay new work. No open Critical/Important finding remains from the independent review and focused re-review. |

## Executed verification

| Command | Result | Evidence |
| --- | --- | --- |
| `python -m pytest -q` | 1,263 PASS; 3 inherited collection warnings | [Python log](workflow-mcp/python-final.log) |
| `cd dashboard-next && npm test` | 220 PASS | [Unit log](workflow-mcp/next-unit-final.log) |
| `cd dashboard-next && npm run typecheck` | PASS | [Typecheck](workflow-mcp/next-typecheck-final.log) |
| `cd dashboard-next && npm run lint` | PASS | [Lint](workflow-mcp/next-lint-final.log) |
| `cd dashboard-next && npm run build` | PASS | [Build](workflow-mcp/next-build-final.log) |
| Gateway `cd apps/saas-gateway && npm run test:source` | 588 PASS; zero failures/skips | [Source log](workflow-mcp/gateway-source-final.log) |
| Gateway `cd apps/saas-gateway && npm run test:providers` | 60 PASS | [Provider log](workflow-mcp/gateway-provider-final.log) |
| `node --test cloudflare/telegram-relay/test/*.test.mjs` | 14 PASS | [Relay](workflow-mcp/relay-final.log) |
| `node scripts/workflow_mcp_gateway_e2e.mjs` | 18 PASS | [JSON](workflow-mcp/gateway-postgresql.json), [log](workflow-mcp/gateway-postgresql.log) |
| `node scripts/workflow_mcp_browser.mjs` | 7 PASS | [JSON](workflow-mcp/native-browser.json), [log](workflow-mcp/native-browser-final.log) |
| `docker compose -f compose.workflow-mcp-qa.yml exec -T api python -m scripts.workflow_runtime_e2e` | 23 PASS | [JSON](workflow-mcp/runtime-regression.json), [log](workflow-mcp/runtime-regression.log) |
| `node scripts/workflow_mcp_audit_readback.mjs` | One decision, completion and activation audit | [JSON](workflow-mcp/audit-readback.json) |

Browser commands used Node 24.22.1, the isolated Compose lab and its private QA
environment, Playwright with Chromium, and the fixed tool paths recorded in the
runner. Inspector 2.14.0 used `--protocol-era modern`; the actual Next Turbopack
MCP compilation probe also returned `issues: []`. Native pages were checked at
390/1280 in light/dark; gateway pages at 390/1280 in their existing dark theme.
Fourteen viewport screenshots are retained in [screenshots](workflow-mcp/screenshots).

## Acceptance and recovery evidence

The real MCP flow discovered current Store/Bot/platform/Action/catalog data,
created and edited an inquiry through a Change Set, rejected an incompatible
Runtime choice source, repaired it, and simulated Telegram and Bale. One
controlled human decision published the exact proposal. Two independent worker
processes were used; one was killed after Native commit. The other recovered
the immutable receipt. Fake Telegram/Bale input completed two Runs with two
actual search Action receipts, no repeated sends and unchanged commerce state.
Search v2 adds bounded display text from the same ACL-filtered real product
page; v1 remains unchanged.

The expanded checks cover conflicting edits, signature replay, foreign Store
requests, unrelated reviewers including another tenant, PostgreSQL immutable
proposal enforcement, customer-value redaction, both revocation orders and
normal UI logout. The QA crash test advances only its own expired dispatch and
publication capacity leases to avoid waiting for their production TTLs.

The independent whole-branch review reproduced three recovery defects. All were
fixed with failing-then-passing regressions and re-reviewed: fresh stale-review
queue blocking; proposal journal finalization crash recovery; and enrollment
preparation that never reached Native. See the [review and follow-up](workflow-mcp/whole-branch-review.md).

## Operational handoff

GitHub Actions were verified disabled in both repository settings. Both remote
base branches and other dirty checkouts were preserved. Only the feature
branches are proposed as Draft PRs. The QA keys, session tokens and private
worker configuration are excluded from commits. The dedicated QA services are
stopped after evidence collection; the original Codespace stack is preserved.

WPMCP deployment requires its SaaS profile and migrations through 0034. Native
and gateway integration flags stay OFF until separately configured and enabled.
The gateway provider setup is documented in the companion repository at
`docs/universal-gateway-bot-provider.md`. Public Studio origins can be configured
separately from private API origins. Human consent/withdrawal and sensitive
business approval remain separate operations.
