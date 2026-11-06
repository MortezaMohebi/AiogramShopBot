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
