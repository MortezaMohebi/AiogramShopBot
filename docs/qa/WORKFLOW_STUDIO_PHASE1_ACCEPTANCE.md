# Workflow Studio Phase 1 acceptance

**PASS — Phase 1 implementation and acceptance are complete.** Customer Bot
Runtime and live publishing remain disabled. No live provider call or payment
was performed.

- Branch: `feat/bot-experience-workflow-builder`.
- Draft PR: [#15](https://github.com/MortezaMohebi/AiogramShopBot/pull/15), stacked
  on Draft PR #14; no merge or deployment.
- Base: `f423a7489c8cc0659ece37d1320026770668696a`, the unchanged head of Draft PR #14.
- Final application fix: `92057a65d63af16406e4f658f1a907ad2dff9745`.
- Complete browser run: `cffa94215ef636cabadcdb4c77f5647f71a678ee`.
- Isolated checkout: `/workspaces/AiogramShopBot-workflow-builder`.
- QA: Compose project `aiogram-workflow-qa`, PostgreSQL 18, private Redis/assets,
  loopback API `8092`, Next dev `3002`. The original checkout and stack were preserved.

## Executed gates

| Gate | Result | Observed evidence |
| --- | --- | --- |
| All Python regressions | PASS | **850 passed**, zero failures/skips, 3 existing collection warnings; **110.16s in Codespace**, also 850 locally |
| Dedicated Workflow Python cases | PASS | **66 passed**: 33 schema, 17 signed API and 16 interpreter regressions |
| Cloudflare Relay | PASS | **14 passed**, zero failures/skips, in Codespace and locally |
| All Next unit tests | PASS | **78 passed**, zero failures/skips; rerun after the final Editor fix and in the final Codespace gate |
| Python compile / Typecheck / lint | PASS | Each completed with exit 0; no application lint warnings |
| Production build | PASS | **Codespace exit 0**, all six Studio routes included; own dev server stopped first after verifying its exact command, cwd and process group |
| Real PostgreSQL + Signed HTTP | PASS | CRUD/history/compare/restore, Store/Bot denial, both-platform simulation, publish denial and unchanged business row counts |
| Concurrent PostgreSQL writers | PASS | Exact concurrent create/save retries produce one snapshot; distinct stale writers produce one winner and one 409 |
| Complete running browser matrix | PASS | **22 observed check groups**, normal password/MFA login, real API saves, both platforms, history/export/recovery/scope and **48 route/viewport/theme combinations** |
| Next MCP / browser runtime | PASS | Correct worktree confirmed; configuration/session errors empty and no uncaught browser page errors |
| Independent scoped review | PASS | No remaining Critical/Important findings after review fixes; reviewer independently ran 11 navigation/auth tests |
| Customer Runtime / real providers | NOT ENABLED | Outside Phase 1; publish returns 409; no dispatcher registration, live payment/refund/broadcast or Bot-management MCP server |

Machine-readable evidence:

- [Final browser checks](workflow-studio/browser.json)
- [Real PostgreSQL checks](workflow-studio/postgresql.json)
- [Final Codespace gate exit codes](workflow-studio/offline-gates.json)
- [Executed test/build summaries](workflow-studio/executed-gates.txt)
- [Next runtime errors](workflow-studio/next-errors.json)
- [Next project identity](workflow-studio/next-project.json)

An earlier combined shell run ended without a final summary and is **not** counted
as passing. The final recorded commands completed separately, with their actual
counts and exit codes above. The final application changes were followed by a
complete successful browser run and Codespace compile/typecheck/lint/test/build.

## Required end-to-end sequence

| Brief step | Executed evidence |
| --- | --- |
| 1–4. Create, add Start/End, message/buttons and a condition | Real UI creates five typed nodes and five outgoing transitions; inspector destinations and condition fields use the actual catalog |
| 5–6. Save/reload and validate | Confirmed autosave, reload, exact text/topology, valid definition report and measured desktop Canvas |
| 7–8. Telegram and Bale previews | Created graph traverses each platform branch; complete synthetic Return Request also finishes on both platforms |
| 9. Save another revision | Message edit is confirmed before navigation; immutable history records the change |
| 10. Restore a previous revision | Compare, inspect Snapshot, append the expected new restore revision, download actual JSON and compare definition/positions/name to the Snapshot |
| 11. Reject cross-Store access | Real Signed HTTP returns 404 for a foreign Store, rejects foreign Bots and wrong-current-Store writes; UI refreshes to read-only and restores editing when its owner becomes current |
| 12. Deny unsupported activation | Real publish endpoint returns 409 `workflow_runtime_unavailable`; publication UI remains disabled |

Additional real browser checks cover copy/delete/paste, button and keyboard
Undo/Redo, stale selection cleanup, preserved clipboard, Back/Cancel, no eligible
orders, typed input/photo metadata/explicit action stubs, and recovery from an
aborted save. Recovery reads a missing receipt, preserves local text and retries
only the identical operation; the confirmed revision increases exactly once.

Every Studio route was exercised at **320, 390, 768 and 1440 px**, in light and
dark themes. Each combination checked actual viewport width, RTL and document
scroll width. Customer/cart/order/payment/support table counts were unchanged
across the complete browser sequence.

## Visual evidence

| Screen | Desktop light | Mobile dark |
| --- | --- | --- |
| List | [PNG](workflow-studio/list-1440-light.png) | [PNG](workflow-studio/list-390-dark.png) |
| Create | [PNG](workflow-studio/create-1440-light.png) | [PNG](workflow-studio/create-390-dark.png) |
| Editor | [PNG](workflow-studio/editor-1440-light.png) | [PNG](workflow-studio/editor-390-dark.png) |
| Settings | [PNG](workflow-studio/settings-1440-light.png) | [PNG](workflow-studio/settings-390-dark.png) |
| Preview | [PNG](workflow-studio/preview-1440-light.png) | [PNG](workflow-studio/preview-390-dark.png) |
| Versions | [PNG](workflow-studio/versions-1440-light.png) | [PNG](workflow-studio/versions-390-dark.png) |

The [measured Canvas](workflow-studio/editor-desktop.png) has five visible nodes
and five connections. Full Return Request results are captured for
[Telegram](workflow-studio/return-preview-telegram.png) and
[Bale](workflow-studio/return-preview-bale.png). These images contain synthetic QA
data. Each screenshot has an adjacent JSON measurement file.

## Regression loop

The test/debug/fix/retest cycle addressed these application issues:

1. PostgreSQL exact-operation races expired the ORM actor during rollback and
   raised `MissingGreenlet`. Explicit refresh after rollback fixed exact create
   and save replay; both two-writer PostgreSQL regressions passed.
2. Separate dashboard tabs could replace each other's CSRF challenge. The shared
   route now derives a domain-separated HMAC from the verified revocable session;
   concurrent requests remain stable, different sessions differ, and production
   HttpOnly/Strict/Secure checks remain intact.
3. Declined history traversal could reach App Router before the draft guard.
   Capture-phase handling preserves the mounted editor, forward history and
   pending receipt; unknown history entries rebase their position scope.
4. Controlled React Flow updates lost geometry/edge selection. Ephemeral
   dimensions and selection remain outside the definition; dynamic handles
   refresh correctly and selected edges can be removed.
5. `go_to_step` config and edges could disagree. Validation now rejects ambiguous
   transitions rather than inferring a false cycle exit.
6. Invalid numeric/text bounds and oversized input media are rejected before
   replay. Shared service dictionary validation matches HTTP validation.
7. Clipboard state now captures a document snapshot, survives editing/deleting
   its source and remaps internal references.
8. A historic save receipt no longer adopts a newer server head as its local
   base; local edits remain and conflict is reported.
9. Archive/delete preserve history even if former Bot/media bindings retire.
   Save/restore/simulation continue enforcing current ownership and bindings.
10. Store/access/status changes remount the editor with the correct effective
    permissions, preventing stale writable controls.
11. Sticky-header scroll clearance and wrapping of valid long keys were added.
12. Keyboard Undo could leave a removed node selected in Toolbar state. The real
    browser test failed with `Undo left a removed node selected in the toolbar`.
    Selection now derives from live IDs; Copy with no selection retains the old
    clipboard. The same browser regression, typecheck, lint and 78 tests passed.

The independent review covered the main implementation and its requested fixes.
The later selection issue was reproduced and retested in the actual browser.

Earlier harness failures included accessibility-name normalization, stale physical
coordinates during scroll, choosing between two login headings, selecting hidden
preview JSON, and waiting on an existing restore label rather than a new revision.
They were corrected without bypassing authentication or injecting editor state.
Two earlier headless-shell runs lost a renderer. The final successful run used
regular Chromium headless mode and one fresh page per route, preserving its
session and viewport. The cgroup reported zero OOM events; kernel logs were
unavailable, so no specific crash cause is asserted. Failed runs were not counted
as acceptance.

## Reproduction

Use the separate guarded lab in [the Studio guide](../WORKFLOW_STUDIO_PHASE1.md).
Create its private environment once, keep provider credentials empty, and retain
its database between additive reruns.

```bash
# Complete source-level checks with this branch's installed dependencies.
bash scripts/beta_storefront_acceptance.sh

# Additive real PostgreSQL and Signed HTTP gate.
docker compose -f compose.workflow-qa.yml exec -T api \
  python -m scripts.workflow_studio_e2e

# Running own Next dev :3002, with bridge pointing to :8092.
PLAYWRIGHT_BROWSERS_PATH=/tmp/workflow-qa-browsers \
WORKFLOW_PLAYWRIGHT_MODULE=/tmp/workflow-qa-browser/node_modules/playwright-core/index.mjs \
WORKFLOW_BROWSER_STAGE=all node scripts/workflow_studio_browser.mjs
```

The QA-only Playwright version is **1.64.1**. The runner also accepts `editor`,
`preview`, `versions`, `recovery`, `access` and `layout`. It uses normal UI controls,
real application responses and Next MCP. Recovery aborts a request and never
fabricates a successful save. Browser credentials/OTP are kept out of diagnostics;
only successful synthetic screenshots and bounded evidence are committed.

## Limits and preserved scope

- No real Telegram/Bale customer client, public webhook, Stars/Bale settlement,
  refund, broadcast or customer menu activation was exercised in this phase.
- Return/approval/notify/wholesale executor gaps are explicit simulation stubs.
  Official capability and current adapter support are reported separately.
- Browser coverage is Chromium and the listed viewport/theme combinations;
  it is not a complete device/assistive-technology/WCAG certification.
- Three existing pytest collection warnings concern imported
  `Testimonial`/`TestimonialPatch` model classes with constructors. Non-failing
  Node/npm environment notices are separate from application lint findings.
- No Alembic revision, persistent database reset, production rollout, merge or
  GitHub Actions configuration change. Only the owned QA Next dev process was
  stopped for the production build; the original stack and all data were preserved.
