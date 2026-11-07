# Commerce UI and copy audit

Scope: 27 console page modules, eight commerce blocks, and the existing customer-note retention action. No API, authentication, permission, payment, deletion-consent, or dependency contract changed.

## Inventory and findings

| Routes | Observed problem | Applied correction |
| --- | --- | --- |
| Products: list, new, edit, digital | Database/migration/storage terminology, mixed-language actions, generic empty state; disabled pagination links still navigable | Task-focused labels; preserve publication and historical-order consequences; distinct search-empty copy; native disabled pagination; license-code fields remain private |
| Categories | Database filler and edit inputs identified only to assistive technology | Remove heading filler; visible edit labels; consistent publication and save labels |
| Media | Repeated implementation/security copy, narrow action rows, actionable disabled links | Preserve private-until-approved meaning; simplify upload/preview labels; wrap actions and pagination; native disabled pagination |
| Orders | Technical search/export label and boundary links | Persian task labels, keep unpaid approval/payment distinction, native disabled pagination |
| Shipping | Database filler; edit controls lack visible labels | Visible price/unit/order labels and specific actions |
| Fulfillments | Raw lifecycle/type values and English Store terminology | Persian verified lifecycle/type labels; isolate tracking and amounts; preserve payment/receipt boundaries |
| Finance | Python/API/Ledger details in routine copy and unnamed confirmation fields | User-facing financial actions and accessible confirmation names; preserve uncertain-refund warnings and manual evidence |
| Reports | Channel card always said 30 days, including 7/90/365-day reports | Pass selected period into the existing shared channel card; preserve separate currencies and old-record limitation |
| Reviews | Boundary links remain actionable and delete controls cannot wrap | Native disabled pagination and wrapping destructive controls; existing approval and confirmation unchanged |
| Coupons | Edit form lacks visible field labels; English/technical filler | Persistent labels including units/date timezone; task-focused save wording |
| Payment accounts | Provider/Store/Backend terminology and raw account values | Persian account/state/provider labels; explain token requirement only; existing proofs, version fields and grants unchanged |
| Digital deliveries | Raw status buttons and primary failure codes | Persian state labels; active-filter semantics; failure codes available under support details; no retry action added |
| Campaigns: list, new, detail | Worker/API terminology, unnamed confirmation fields, raw failure code | Plain sending/setup labels; accessible confirmations; support details for codes; approval/start/cost/unknown-delivery consequences preserved |
| Customer notifications | Outbox/Subscription/Dispatch implementation explanation | Plain queue/subscription labels; exact known status labels; retain that queue counts are not proof of receipt |
| Customers: list, detail, retention | Generic/no-match state, Audit/Block terminology; retention action discards backend count | Distinguish empty records from search matches; plain history/restriction labels; display validated eligible/deleted count from existing action response |
| Store customers: list, detail | Store/Identity/Customer terminology and mixed-direction IDs | Domain labels and bidi isolation; preserve separate balances, ownership verification and historical-order address scope |
| Support tickets: list, detail | Raw status filters, Store/Customer/Outbox/Timeout terms | Persian status filters and subtitle; active-filter semantics; preserve independently tracked customer delivery |
| Units of measure | Float/UoM/Stock/Cart/Increment jargon and blank category list | Persian terms, LTR codes/ratios, useful empty state; require category before adding a unit |

## Major component corrections

- Product editor: remove migration/database implementation copy; keep unit, stock and publication constraints; move correlation identifier into support details.
- Product bot access: remove Many2many/Allow/Deny implementation labels while retaining exact precedence and separately saved access rules.
- Category picker: name native edit dialog and ensure active-descendant refers to an existing option.
- Product media picker: file input sits inside its visible label so keyboard focus is visible; action rows wrap. Internal challenge/transport errors receive Persian text and unresolved outcomes keep check-before-retry guidance.
- Digital uploader: announce validation/errors separately from success, explain missing file, disable file changes while uploading and map internal challenge codes.
- Dashboard metric cards: remove unsupported claim that a published product is accessible from both bots; publication and per-bot grants remain distinct.
- Channel card: accept actual report period and provide an empty state.
- Order table: reviewed and retained; existing monetary formatting, semantic headers and status rendering remain appropriate.

Essential labels and helpful consequences were retained. Redundant descriptions and implementation details were removed; no marketing replacement was added. Support codes remain available in collapsible details.

## Retention action evidence

The existing backend returns `notes_eligible` for a dry run and `notes_deleted` after confirmed deletion. The action now checks `ok`, mode, and a nonnegative safe-integer count before showing a result. Invalid or mismatched receipts show an unresolved result; no automatic retry is introduced. Deletion still requires the existing checkbox and exact backend confirmation value.

## Verification

- Scoped ESLint: 37 owned TypeScript/TSX files, exit 0.
- Focused actual-action regression: `node --experimental-strip-types --test dashboard-next/tests/customer-retention-action.test.mts`, 11/11 pass. The count/receipt cases first failed against the previous action (10 expected failures; existing reauthentication case passed), then passed after the fix.
- Scoped `git diff --check`: pass.
- Whole-project typecheck, build, full suite and final browser/viewport/theme verification belong to the integrated UI/UX verification. They were not rerun in this scoped subtask. No live mutation, payment, deletion, or broadcast was used for testing.

## Remaining verification limits

Runtime appearance, physical-device behavior, keyboard focus return, 320px reflow, themes and backend-connected flows still require integrated browser evidence. Unknown future lifecycle values intentionally retain their supplied value rather than invent a completion/approval meaning. No new backend limitation was inferred from placeholder data.

## Exact reviewed ownership

`order-table.tsx` was reviewed without source changes. All other ownership stays within these modules, plus the narrow retention action and regression below.

- `dashboard-next/app/(console)/campaigns/[id]/page.tsx`
- `dashboard-next/app/(console)/campaigns/new/page.tsx`
- `dashboard-next/app/(console)/campaigns/page.tsx`
- `dashboard-next/app/(console)/categories/page.tsx`
- `dashboard-next/app/(console)/coupons/page.tsx`
- `dashboard-next/app/(console)/customer-notifications/page.tsx`
- `dashboard-next/app/(console)/customers/[id]/page.tsx`
- `dashboard-next/app/(console)/customers/page.tsx`
- `dashboard-next/app/(console)/customers/retention/page.tsx`
- `dashboard-next/app/(console)/digital-deliveries/page.tsx`
- `dashboard-next/app/(console)/finance/page.tsx`
- `dashboard-next/app/(console)/fulfillments/page.tsx`
- `dashboard-next/app/(console)/media/page.tsx`
- `dashboard-next/app/(console)/orders/page.tsx`
- `dashboard-next/app/(console)/payment-accounts/page.tsx`
- `dashboard-next/app/(console)/products/[id]/digital/page.tsx`
- `dashboard-next/app/(console)/products/[id]/edit/page.tsx`
- `dashboard-next/app/(console)/products/new/page.tsx`
- `dashboard-next/app/(console)/products/page.tsx`
- `dashboard-next/app/(console)/reports/page.tsx`
- `dashboard-next/app/(console)/reviews/page.tsx`
- `dashboard-next/app/(console)/shipping/page.tsx`
- `dashboard-next/app/(console)/store-customers/[id]/page.tsx`
- `dashboard-next/app/(console)/store-customers/page.tsx`
- `dashboard-next/app/(console)/support-tickets/[id]/page.tsx`
- `dashboard-next/app/(console)/support-tickets/page.tsx`
- `dashboard-next/app/(console)/uoms/page.tsx`
- `dashboard-next/components/blocks/product-editor.tsx`
- `dashboard-next/components/blocks/product-media-panel.tsx`
- `dashboard-next/components/blocks/product-bot-many2many-panel.tsx`
- `dashboard-next/components/blocks/category-many2one.tsx`
- `dashboard-next/components/blocks/digital-file-uploader.tsx`
- `dashboard-next/components/blocks/order-table.tsx`
- `dashboard-next/components/blocks/channel-performance.tsx`
- `dashboard-next/components/blocks/section-cards.tsx`
- `dashboard-next/app/(console)/customers/retention/actions.ts`
- `dashboard-next/tests/customer-retention-action.test.mts`
- `docs/qa/UI_UX_COMMERCE_AUDIT.md`
