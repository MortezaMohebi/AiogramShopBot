# Studio UI/UX audit

## Reviewed scope

- `/studio/workflows`: list/search/status/pagination/empty states.
- `/studio/workflows/new`: creation and duplication forms.
- `/studio/workflows/[id]`: editor, diagram, node inspector, validation, save/conflict/unknown states.
- `/studio/workflows/[id]/settings`: bot assignment, entry points, variables, error/timeout policies, archive/delete.
- `/studio/workflows/[id]/preview`: simulated conversation, scenario/input/file/time controls.
- `/studio/workflows/[id]/versions`: comparison, immutable snapshots, restoration and history.
- `/studio/actions`: catalog filters/details/context/access and read-only dry run; Action input/output bindings.
- `/studio/runtime`: all six tabs, gates, operational metrics, publications, delivery/recovery/approval/history controls.
- `/studio/runtime/runs/[id]`: run metadata, private variable projections, Action receipts, events and delivery.
- `/studio/mcp` and `/account/mcp`: identity/scope review, connection access, revocation, unknown-result reconciliation and receipts.
- All components in `components/{workflows,runtime,actions,mcp}`, including unchanged operation/save hooks.

Route error/loading files were reviewed but left to the parent integration owner because the assigned route edit scope was `page.tsx` only.

## Findings and fixes

| Priority | Finding | Implemented change |
| --- | --- | --- |
| High | Settings incorrectly claimed publication was unavailable even though the runtime publication flow exists. | Explain that saving a draft does not update the active bot version; direct the user to publication. |
| Medium | Architecture and promotional descriptions dominated workflow/catalog headings. | Remove redundant subtitles; use task names: فرایندها، عملیات آماده، وضعیت اجرای فرایندها، اتصال‌های MCP. |
| Medium | Revision, snapshot, restore, entry-point, override, context and legacy labels appeared in routine controls. | Use plain Persian for actions/navigation; preserve literal identifiers, schema fields, protocol names and advanced technical configuration. |
| Medium | Entry-point, variable and button editor controls relied on accessible names with missing visible field labels. | Reuse the local existing Field component for persistent labels; retain specific accessible names and handlers. |
| Medium | Publication review could retain two visually primary actions after preview creation. | Make preview creation secondary once a preview exists; preserve the explicit final activation action and its confirmation. |
| Medium | Workflow list empty copy suggested creating even for searches or archived/deleted views. | Distinguish no search matches; provide clear-search or creation link only in applicable states. |
| Low | Missing description filler and always-visible integrity hashes added noise. | Omit absent description; retain hash in an expandable detail. |
| Low | Persian labels shared a forced LTR paragraph with a store ID; version arrows had no explicit LTR direction. | Isolate the ID and comparison direction; retain all identifier bytes. |
| Low | Version comparison headers lacked explicit column/row scope. | Add semantic scopes and Persian row labels. |
| Low | Narrow filter controls competed for flex space. | Give long-ID/search filters a flexible wrapping basis and preserve min-width constraints. |
| Low | Account MCP withdrawal used a divergent raw text input. | Reuse the existing shared Input component without changing behavior. |

## State and consequence safeguards

No endpoint, payload, identifier, hook, authorization, idempotency, business handler or state machine was changed. Unknown save/mutation results, matching receipt reconciliation, conflict/version checks, duplicate prevention, approval versus execution, simulated versus real effects, publication preview expiry, activation versus gates, immutable run versions, retained bindings, safe recovery, delivery uncertainty and revocation consequences remain explicit.

MCP request receipts remain distinct from decisions/execution in WPMCP. Consent identities, requested stores/scopes, versions, expiry and revocation confirmation remain visible. Advanced schema/JSON fields and diagnostic identifiers remain where they support configuration or investigation.

## Validation

- Scoped ESLint passed over workflows/runtime/actions/MCP components and studio/account-MCP routes.
- Full TypeScript `tsc --noEmit` and `git diff --check` passed after the final edits.
- Existing runtime UI, runtime overview and MCP connection regression tests: **13 passed, 0 failed**. These cover private-data exclusion, queued/sent/unknown delivery distinctions, retained publication bindings, read-only controls, missing metrics versus zero, exact scope/receipt matching and unresolved writes.
- The root integration owner runs the full type/build/test and authenticated browser checks. Desktop/mobile/tablet, dark mode, keyboard and final browser console results are not independently claimed by this scoped source audit.
- No live mutation or approval was used for this review.

## Integration notes and remaining risks

The browser runner uses exact visible/accessible names and must follow intentional copy changes: gate permission checkbox `مجوز اجرای فرایند`; emergency checkbox `توقف اضطراری و بازگشت به مسیر قبلی ربات`; gate save `ذخیرهٔ تنظیم اجرا`; runtime nav `بخش‌های وضعیت اجرا`. Publication preview/activation labels and business semantics are unchanged.

Backend-supplied catalog/node labels and error messages cannot be exhaustively localized by a frontend copy pass without editing their contracts. Existing advanced identifiers are intentionally retained rather than disguised or transformed. No new dependency or shared primitive was introduced or changed by this scoped work.
