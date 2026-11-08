# Contract: Customer conversation on Telegram and Bale

This contract describes the existing public chat surface after the change. No HTTP endpoint,
payment method, chat command removal, or dashboard contract is introduced.

| View | Default and contextual actions | Back, Home, Cancel, or error |
| --- | --- | --- |
| Home and persistent keyboard | Allowed destinations in configured order and with the same Persian labels: Shop, Search, Cart, Orders, Account, Support, as policy/capabilities permit. A contact keyboard is a temporary replacement. | Recompute on authorized navigation and restore after contact completion, cancellation, or exit. Recheck a previously rendered shortcut before acting. Existing direct commands and owned after-sales routes retain their separate gates. |
| Old control | No original mutation or form clearing. A supported acknowledgement can point to a confirmed usable current view. If needed, make one safe visible recovery. | Re-render a safe current destination or offer allowed Home/after-sales; never expose a restricted route. Legacy Bale gets a visible route even if an acknowledgement is impossible. Repeated taps reuse it. |
| Browse and Search | Four eligible products per default page, visible position, applicable Previous/Next, textual product labels, optional category and gallery. Search initially accepts a product name, with optional filters. | Back from details/previews restores the scoped query, filter and valid page; clamp if results shrink. Empty or expired results provide allowed New Search/Browse/Home. Home and Cancel disarm search input and retain safe unrelated data. |
| Product detail | Text summary, existing contextual actions, accessible preview, explicit media/gallery and visible return target. | Use the originating list, gallery, or search Back. Deliberately requested files and durable records remain available when moving elsewhere. Older approved gallery/detail shortcuts recheck eligibility. |
| Cart and checkout | Show amount/currency, delivery consequences, mode, existing provider limitations and the next effect before explicit decision. Put visible Terms on the review. Keep `/terms` as an optional independent read. | Every terms page has one return action. Same valid review returns to equivalent selections and totals; policy/price/page drift explains the change and routes to a fresh review or current permitted Cart/Home/help. Cancel does not accept. |
| Account | Profile and Addresses direct; two groups, «خرید و امکانات» (credit, favorites, referral, stock alerts) and «تنظیمات و حساب‌های متصل» (linked accounts, notifications, language, privacy). Shared Back/Home excluded from four choices. | Each currently permitted action is within two selections from Account. Contact and address flows retain provenance checks, wizard steps, review and resume; invalid input leaves an actionable return. |
| After-sales and durable records | Existing orders, receipts, support, refunds and files retain access and rules. | Continue from authorized history or current actions. A receipt shortcut may open a safe current view, never treat its ID as current write authority. No editing/deleting durable content. |

**Customer copy:** use a text label on every touched control, optionally with an icon. Use
short Persian action and outcome phrases, e.g. «این دکمه دیگر فعال نیست. از منوی اصلی ادامه دهید.»,
«شرایط خرید تغییر کرده است؛ مبلغ و شرایط جدید را بررسی کنید.» and «بازگشت به نتایج جست‌وجو».
Isolate mixed-script amounts and legitimate references for RTL where supported; do not translate
or truncate contractual text. Name the provider limitation before commitment. Map known internal
errors to customer-facing text and one allowed next action; retain structured diagnostics internally.
