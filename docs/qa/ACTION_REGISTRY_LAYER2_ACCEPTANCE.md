# Layer 2 acceptance — 2026-11-05

**LAYER 2 PROGRESS: 100%**
**STATUS: COMPLETE — READY FOR LAYER 3.**
All implementation and finalization gates passed. GitHub Actions is disabled,
and [Draft PR #16](https://github.com/MortezaMohebi/AiogramShopBot/pull/16) targets
the completed Layer 1 branch. No Layer 3 or Layer 4 implementation, live provider
call, merge or deployment is included.

## Branch, scope and evidence

- Base: `feat/bot-experience-workflow-builder`, `c3c6e79796f864f09df4deb0462cd36f221dbf9e`.
- Feature: `feat/bot-experience-layer2-action-registry`.
- Draft PR: `https://github.com/MortezaMohebi/AiogramShopBot/pull/16`.
- Reviewed application source: `037ab2c5a26a969bb435dcac890cf215fc05cfb0`.
- Current acceptance runner: `e17aac89e2628bbd4c779b708b381938914c7677`.
- Final documentation/evidence commit is the feature branch HEAD.
- Codespace: `obscure-space-couscous-p7w6p4jrrxv3j59`.
- Isolated checkout: `/workspaces/AiogramShopBot-action-registry`.
- Separate project: `aiogram-action-qa`; API `127.0.0.1:8093`, Next dev `3003`.
- Original checkout, its dirty generated files and its main stack were preserved.

See [the implementation guide](../ACTION_REGISTRY_LAYER2.md) for the 19 exact
Action contracts, four unavailable services, two additive ORM models, application
services, APIs, dashboard paths, side-effect/approval/idempotency policies,
limits, future Layer 3 contracts and architectural boundaries.

## Acceptance results

| Gate | Result | Evidence |
| --- | --- | --- |
| Full final Python suite, host | PASS — 968; 3 existing collection warnings | `python -m pytest -q tests`; 96.59 s |
| Focused final Action/Workflow/cart regressions | PASS — 142 | Actual services, SQL rows, authorization and binding assertions |
| Next unit suite | PASS — 99; no failures/skips | `npm test` |
| TypeScript and ESLint | PASS; zero lint warnings | `npm run typecheck`; `npm run lint -- --max-warnings=0` |
| Python formatting | PASS — 27 new Action/contract/test files | Black check |
| New Action UI/BFF formatting | PASS | Prettier check |
| PostgreSQL Action/signed HTTP suite | PASS — 11, final source rerun | `action-registry/postgresql-actions.json` |
| Existing PostgreSQL Workflow suite | PASS — 4, final source rerun | CRUD/scopes/simulation and exact-create/save/CAS races |
| Existing Telegram/Bale journeys | PASS — both platforms, final source rerun | Real dispatcher, PostgreSQL and Fake Providers |
| Full final Codespace offline suite and build | PASS — Python 968 (122.86 s), Relay 14, Next 99, compile/typecheck/lint/build | `action-registry/codespace-final-gate.log`; `summary.json` |
| Full final browser suite | PASS — 35; 64 viewport/theme route combinations | `browser-all.json`; source `e17aac89`; no uncaught or Next MCP errors |
| Final independent implementation review | PASS; no remaining Critical/Important/Minor findings | Scope and verification below |
| GitHub Actions disabled | PASS | Explicitly authorized Save succeeded; Disabled persisted after reload; `github-actions-status.json` and screenshot |
| Draft PR finalization | PASS — Draft PR #16 | Correct Layer 1 base, Layer 2 head; no merge or deployment |

## Defects reproduced and corrected

| Trigger | Observed failure | Correction and verification |
| --- | --- | --- |
| Two independent cart Actions after receipt insertion | PostgreSQL `40P01` deadlock; loser returned `action_busy` | Bot policy lock uses NO KEY UPDATE; repeated real PG race returns one success and exact stale-revision rejection |
| Retry delivery of a committed operation after retry budget | Successful receipt was hidden by `action_retry_exhausted` | Budget restricts adapter execution; exact committed receipt remains recoverable |
| Preview of unavailable business service | Success branch followed with synthetic unavailable output | Explicit unavailable stub/transition; successful output assignment omitted |
| Legacy Bot disabled/paused/maintenance via operational settings | Support/order Actions still succeeded | Central operational gate applies to every category; 6 RED→GREEN cases |
| Remove one cart item while remaining lines have stale stock/ACL | Valid removal rolled back on re-quote | Honest unquoted cart snapshot; monetary totals null; denied names/prices omitted; 2 RED→GREEN cleanup cases |
| Product-name string mapped to date/datetime/enum | Validator said valid; Simulator failed at assignment | Direction-aware Python/TS compatibility and enum containment; 5 Python +1 TS regression cases |

Additional source regressions cover staff session expiry/version, proof purposes,
both independent proofs, required context, forbidden generic executor names,
editable incomplete mappings and selected Bale simulation context. Invalid
outputs, authorization failures and no-effect modes are tested against actual
SQL tables rather than accepted mocked success values.

The acceptance harness also needed corrections: diagnostic-session revocation
arguments, waiting for server Store props after `router.refresh`, selecting the
visible desktop Canvas, and laying out new overlapping nodes before pointer
selection. The initial QA dev origin was accidentally configured with HTTP in
the production-only HTTPS origin setting; the dev override was cleared. No
authentication or origin protection was weakened to make these tests pass.

## Independent review

A fresh read-only reviewer inspected the complete Layer 2 application diff
against `c3c6e797`, then the nine-file fix diff. It independently reproduced the
operational gate, cart cleanup and output mapping defects and verified their
fixes. Final verdict: approve the scoped implementation, subject to acceptance
gates; no remaining Critical/Important/Minor implementation finding.

Independent checks: 8 operational/cart tests, 26 Workflow binding tests,
11 TypeScript state tests, clean `git diff --check`. No unauthorized live HTTP
execution, customer impersonation or proof issuance surface was found.
Final PostgreSQL/browser/build gates, remote Actions settings and future
Runtime/MCP/provider behavior were explicitly outside that reviewer's verdict.

## Exact reproduction commands

Run only with the private provider-free QA environment, a separate project and
synthetic fixtures. Do not reset an existing database.

```bash
# Start isolated dependencies and seed additive Fake Provider data.
docker compose -f compose.action-qa.yml up -d --no-build
docker compose -f compose.action-qa.yml exec -T api python -m scripts.beta_storefront_e2e
docker compose -f compose.action-qa.yml exec -T api python -m scripts.workflow_studio_e2e
docker compose -f compose.action-qa.yml exec -T api python -m scripts.action_registry_e2e

# Run normal password/MFA, real signed responses, typed bindings and UI recovery.
# Next dev :3003 uses SHOP_FASTAPI_INTERNAL_URL=http://127.0.0.1:8093.
# Leave NEXT_ADMIN_PUBLIC_ORIGIN empty for this loopback development instance.
PLAYWRIGHT_BROWSERS_PATH=/workspaces/beta-qa-tools/playwright-browsers \
WORKFLOW_PLAYWRIGHT_MODULE=/workspaces/beta-qa-tools/playwright/node_modules/playwright-core/index.mjs \
WORKFLOW_QA_COMPOSE=compose.action-qa.yml WORKFLOW_BROWSER_STAGE=all \
node scripts/workflow_studio_browser.mjs

# After verifying and stopping only this checkout's Next dev process:
PATH=/workspaces/beta-qa-tools/python/bin:/workspaces/beta-qa-tools/bin:$PATH \
bash scripts/beta_storefront_acceptance.sh
```

The browser runner accepts `actions` independently or `all` for combined
Layer 1/2 regression coverage. Playwright 1.64.1 is a QA tool outside application
dependencies. It uses regular headless Chromium, actual controls/responses and
Next MCP; no successful application response is fabricated. Its request-abort
tests simulate recovery failures only.

The final browser run covers Catalog filters, schema/policy detail, safe real
Catalog dry-run for Telegram and Bale, foreign-product denial after Store switch,
normal MFA login, typed Action creation with five outcomes, exact version and
constant/output-variable roundtrip, both pure platform previews, keyboard tab
order and the existing editor/history/restore/Save recovery journeys. It checks
320/390/768/1440 px in light/dark: 16 new Action route combinations plus 48
existing Studio combinations. All customer/commerce/Action table counts remain
unchanged across browser activity.

The final offline gate ran with the QA dev process stopped only after its
PID/process-group, command line and exact checkout directory were verified.
The main Codespace stack was not stopped. Generated `next-env.d.ts` was restored
only in this owned Layer 2 checkout after the build. Successful synthetic
screenshots, Next MCP output, PostgreSQL checks and a bounded summary are in
`docs/qa/action-registry/`; private login diagnostics and credentials are excluded.
One leftover session from the earlier QA diagnostic cleanup failure was revoked
using its exact diagnostic label in this isolated database. The owned Codespace
checkout was clean after the evidence commit. All five original main-stack
containers were checked and remained healthy.

## GitHub Actions and finalization

The repository setting at
`https://github.com/MortezaMohebi/AiogramShopBot/settings/actions` was saved as
**Disable actions** after the user explicitly requested this exact change.
The page confirmed **Actions policy updated**; a subsequent reload still showed
Disabled selected and Allow all unselected. The repository Actions tab was hidden.
`github-actions-status.json` records the result and the successful saved-state
screenshot. Draft PR #16 was created only after this persisted-state verification.

Earlier attempts were blocked by automatic approval review until the user gave
explicit authorization. Their unsaved screenshots are retained as historical
evidence; they do not describe the final setting. No alternative API/workaround
was used and no workflow was enabled or dispatched.

Closure changes after the verified `e17aac89` application/runner tree contain
documentation and QA evidence only. Executable source equality, committed result
counts, clean diff/tree, Draft PR metadata and the saved Actions policy were
checked again. These finalization changes did not require repeating the unchanged
application test/build suites. Layer 3 remains a separate future phase.

## Limits and risks

- No real customer messenger client, public webhook, Stars/Bale payment,
  refund, Broadcast or workflow customer routing was activated.
- Four unavailable contracts remain unavailable until their real services and
  policies exist. Telegram/Bale platform support does not imply payment/media
  parity beyond the actual implemented adapter.
- Invocation and proof issuance are trusted internal Backend interfaces; a
  future Runtime must authenticate transport, obtain real decisions and retain
  operation identity across retries. A dedicated session is mandatory.
- Initial adapters perform local atomic mutations/read-only work; there is no
  runnable external-mutation adapter. Future external work needs a durable
  outbox and outcome reconciliation.
- Metrics are process-local; production aggregation/retention is a deployment
  concern. No production schema/data migration was performed.
- Browser coverage is Chromium at explicit viewports/themes; it is not a full
  device or assistive-technology certification.
- Three existing pytest collection warnings concern imported classes named
  `Testimonial`/`TestimonialPatch`; they do not indicate failed test cases.

The supplied documentation ZIP contains guides/links, not full official API
pages. Relevant Telegram and Bale behavior was checked against primary official
documentation during design; no new unsupported provider operation was enabled.
