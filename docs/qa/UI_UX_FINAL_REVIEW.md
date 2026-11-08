# Dashboard UI/UX final source review

Reviewed the uncommitted dashboard changes against HEAD, the supplied requirements, implementation plan, and settings/Studio audits. Focus: shared modal/navigation behavior, login preservation, mutation uncertainty and receipts, destructive-action consequences, forms, accessible labels, Persian/RTL copy, and status display contracts. No source files, real systems, or QA data were mutated by this review. Broad suites and authenticated browser acceptance remain owned by the integration task.

No concrete Critical or Important regression was identified in the reviewed changes.

## Minor findings

1. **Mobile navigation opens from the opposite side of the RTL layout.** `dashboard-next/components/blocks/sidebar.tsx:64` uses `m-0 ms-auto` for the native dialog. In RTL, `margin-inline-start: auto` is the right margin, so the remaining width is placed to the dialog's right and the drawer sits on the left. The desktop sidebar and previous mobile implementation are at inline start/right. Use `me-auto` (or equivalent explicit logical positioning) and confirm the drawer remains at the right edge at 320/390px. This is a source/CSS finding; browser geometry was not independently executed by this review.

2. **Paused stores still expose the backend status key.** `dashboard-next/components/blocks/store-switcher.tsx:119` translates `suspended`, but `StoreOption.state` in `dashboard-next/lib/store-context.ts:9` permits `active | paused | archived`. `services/shop_store_context.py:126` returns nonarchived stores, including paused stores. Consequently a paused store displays `paused` rather than the intended Persian status. Translate `paused` instead of the unsupported `suspended` key; a typed map would make this mismatch visible to TypeScript.

3. **Credit confirmation input's accessible name no longer includes its visible label.** `dashboard-next/app/(console)/finance/page.tsx:91` adds `aria-label="عبارت تأیید عملیات"` inside a label visibly reading `تأیید دستی`. The ARIA name overrides the native label, so speech-input users cannot target the field by its displayed name (label-in-name). Remove this redundant ARIA label or align the visible label with the accessible phrase. The other confirmation inputs without visible labels still need accessible names.

## Review limits

The findings above are based on the final source/diff available during review. This review does not claim a separate browser pass, complete assistive-technology conformance, broad test execution, or production-provider validation. Existing isolated PostgreSQL acceptance and final build results must be recorded by the integration owner after any fixes.

## Focused resolution recheck

- Finding 1 resolved in source: the mobile drawer now uses `m-0 me-auto`, placing its automatic margin at inline end/left in RTL.
- Finding 2 resolved in source: the store state map now translates `paused` to `متوقف`.
- Finding 3 resolved for the credit input: its redundant ARIA override was removed and the native wrapping label remains.
- Minor follow-up resolved: both refund confirmation inputs now have persistent wrapping native labels reading `عبارت تأیید بازپرداخت`. Their accessible names therefore match the visible text without an ARIA override. The credit input retains its original native label.

All findings from this review are resolved in the inspected source. The focused recheck did not run broad suites or browser acceptance.

## Follow-up review against a7bdea0e

Reviewed the new changes to the shared Dialog, category edit modal, product new/edit feedback, development indicator placement, and dashboard browser harness. The Dialog explicitly wraps forward/reverse Tab navigation at the current modal controls; category editing retains the selected-ID response check and submit/cancel disabled states. Product feedback now preserves an unresolved mutation result. No concrete Critical or Important source regression was identified in this follow-up. No broad suites or QA mutations were performed by this reviewer.

- **Minor — screenshot theme evidence is mislabeled.** `scripts/dashboard_ui_browser.mjs:179` saves `mobile-menu-dark-320`, but the password/login check at line 147 set the theme to light and no subsequent theme change occurs before the mobile menu screenshot. The actual screenshot is therefore light despite its dark filename. Set the requested theme before capture (and restore light for the following category capture), or rename the mobile screenshot and report it as light. This is an evidence-label defect, not a demonstrated rendering defect.

The integration owner continues the authenticated browser inventory and records its results separately. This review does not independently claim the reported browser passes.

## Store scope and CAPTCHA follow-up review

Inspected the current bridge helper, Settings and restricted-route rendering, shared StoreScopeNotice, CAPTCHA SDK options, development indicator setting, regression-test sources, and updated browser harness. No new concrete Critical, Important, or Minor finding was identified.

- `optionalStoreRead` catches only an `ApiError` carrying status 409 and the allowlisted `store_scope_not_supported` code. Authentication redirects, permission failures, other conflicts, and service errors continue through the established failure path. The helper performs GET reads only.
- Settings still requests current-store branding through `adminFetch`; only the unsupported global configuration reads become unavailable. Existing supported forms retain their handlers and values. The connection, relay, and retention pages retain their superadmin checks and show scope guidance only for the exact restriction. The backend middleware restriction remains unchanged.
- Compact Turnstile/reCAPTCHA v2 options do not alter token acquisition, expiry/failure callbacks, or server verification in the inspected diff. Provider-boundary tests exercise the actual widget lifecycle with substituted SDK/DOM boundaries; this source review does not claim a live-provider render.
- The previous screenshot-theme finding is resolved in source: the harness now captures the mobile drawer in light mode, explicitly switches to dark before the dark capture, and restores light before the category capture. Restricted route results are recorded as `restricted_by_store` rather than represented as available forms.

Focused whitespace checks passed. No broad test suite, browser session, or QA mutation was executed by this reviewer. All findings raised by this review are resolved in the inspected source; final running-app acceptance remains with the integration owner.
