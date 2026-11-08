# Feature Specification: Customer Experience Simplification and UX Repair

**Feature Branch**: `chore/chatbot-ux-constitution`

**Created**: 2026-11-08

**Status**: Draft

**Input**: Repair the audit findings for Telegram and Bale under **Calm by Default, Powerful by Choice**. [UX Constitution v1.1.0](../../.specify/memory/constitution.md)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Recover from an expired button (Priority: P0)

As a shopper, I want to keep shopping after tapping an old button so I can recover without
changing my cart or order by accident.

**Why this priority**: A stale action can strand a shopper or invite repeated attempts at an
unsafe change.

**Independent Test**: Open a product, move to another view, then tap its obsolete Add button
twice.

**Constitution principles**: IV, V, VI, IX, X, XI.

**Acceptance Scenarios**:

1. **Given** a newer authorized view is available, **when** I tap an older Add or Pay control,
   **then** the old action changes nothing and I can reach the current view from the feedback.
2. **Given** the current view is missing or no longer allowed, **when** I tap an expired
   control, **then** I see one safe route to Home or an allowed destination, without details I
   can no longer access.
3. **Given** a usable recovery is already available, **when** I tap the same old control
   repeatedly, **then** there is no repeated recovery message or duplicate business effect.

---

### User Story 2 - Read terms and return to checkout (Priority: P0)

As a shopper reviewing an order, I want to read the applicable terms and return to my review
before I decide.

**Why this priority**: The terms must be reachable at the purchase decision, and review must
remain separate from acceptance.

**Independent Test**: Open checkout on a cart with long terms, reach the final terms page,
return, then choose whether to accept.

**Constitution principles**: IV, VIII, IX, X, XI, XII.

**Acceptance Scenarios**:

1. **Given** I see the checkout review, **when** I tap the visible terms action and read or
   leave the terms, **then** I return to the review with my valid selections and no consent,
   order, or payment created by reading.
2. **Given** the terms or quote change during review, **when** I open or return from terms or
   attempt to accept the older review, **then** I am told what changed and can review the
   current terms and quote from checkout before making a new decision.
3. **Given** terms are missing or checkout is unavailable, **when** I try to proceed, **then**
   the flow gives an allowed recovery or support action and creates no order or payment.

---

### User Story 3 - Use a consistent menu for the current shop (Priority: P1)

As a shopper, I want persistent shortcuts and Home to reflect what I can actually use in this
bot.

**Why this priority**: A familiar keyboard is only useful when its destinations match current
permissions and capabilities.

**Independent Test**: Compare a Store default, a bot override, and a bot with Cart disabled.
Leave a contact request using Back or Cancel.

**Constitution principles**: IV, V, VI, X, XI.

**Acceptance Scenarios**:

1. **Given** Cart is disabled or a destination is omitted by the effective menu, **when** I open
   Home or the main keyboard refreshes, **then** both surfaces omit that destination and the
   other labels keep their configured order.
2. **Given** I complete or leave a native contact request, **when** the main navigation returns,
   **then** it shows the effective destinations, and the temporary contact prompt no longer
   accepts unrelated input.
3. **Given** a formerly allowed destination is now forbidden, **when** I tap an older shortcut,
   **then** the destination is refused safely and I can reach an allowed view.

---

### User Story 4 - Return to my search results (Priority: P1)

As a shopper comparing products, I want Back to restore the search I was using, including
filters and page position.

**Why this priority**: Losing the result page forces repeated searches and breaks comparison.

**Independent Test**: Search with an optional field filter, move to page two, open a product,
and go Back.

**Constitution principles**: II, III, IV, VII, IX, XI.

**Acceptance Scenarios**:

1. **Given** my search is valid and I opened a product from a later page, **when** I select Back
   to results, **then** the same query, filters, and valid page return.
2. **Given** I am in a search prompt, **when** I choose Home or Cancel, **then** Home navigates
   without consuming the shortcut as input, and Cancel ends search and returns to a safe Home
   route.
3. **Given** a result disappears, the page shrinks, or the search expires, **when** I return to
   results, **then** I see the nearest valid page or a clear way to start a fresh search, with
   only currently allowed products.

---

### User Story 5 - Browse several products without filling the chat (Priority: P1)

As a shopper, I want to compare products in one compact view and open media when I choose.

**Why this priority**: Frequent page turns create clutter, and a default view should make
products easy to compare.

**Independent Test**: Use a catalog with nine eligible items, including one without a cover and
one without a category. Browse every page and request a file.

**Constitution principles**: I, II, V, VI, VII, XI, XII.

**Acceptance Scenarios**:

1. **Given** several eligible products are available, **when** I open Shop or Search, **then** I
   can compare multiple results on one page and navigate without selecting a category.
2. **Given** the active view can be edited, **when** I page forward or back, **then** the view
   updates without adding a message, and a no-change repeat adds none.
3. **Given** the provider definitively cannot edit the view, **when** I navigate or open a photo
   preview, **then** at most one replacement view appears, and previous requested files and
   durable receipts stay usable.

---

### User Story 6 - Find Account actions by purpose (Priority: P2)

As a shopper, I want to find profile, addresses, and less frequent Account actions without
scanning a long menu.

**Why this priority**: Account grouping reduces scanning while keeping existing options
reachable.

**Independent Test**: Open Account, choose Addresses, then return and find notification
settings, linked accounts, and privacy.

**Constitution principles**: I, II, IV, X, XII.

**Acceptance Scenarios**:

1. **Given** I open Account, **when** I scan its first view, **then** I see direct Profile and
   Addresses actions plus two clearly named groups for the remaining actions.
2. **Given** I open a secondary action or leave an address draft, **when** I use Back or return
   later, **then** I can reach Account again, find every existing action, and explicitly resume
   a valid draft.

---

### User Story 7 - Read clear Persian prompts (Priority: P2)

As a Persian-speaking shopper, I want to understand what an action does and what happened
without interpreting internal terms.

**Why this priority**: Plain copy reduces mistakes in checkout, contact verification, and
recovery.

**Independent Test**: Review the touched Persian prompts on both platforms and ask a reviewer to
identify the next action and the result of a tap.

**Constitution principles**: I, VIII, IX, XI, XII, XIII.

**Acceptance Scenarios**:

1. **Given** I read a touched checkout, verification, or error message, **when** I look for the
   consequence and the next action, **then** the Persian text explains both, and visible amounts
   retain their currency.
2. **Given** I view linked accounts or a provider error, **when** I look for the detail I need
   to proceed, **then** I see a recognizable account or support reference where needed, without
   internal bot identifiers or provider diagnostics.

---

### User Story 8 - Recover on a narrow screen and with assistive technology (Priority: P2)

As a shopper using a small screen or assistive technology, I want readable choices and a route
out of a failed step.

**Why this priority**: A required step that is clipped or indicated only by an icon can block
the journey.

**Independent Test**: Use a narrow supported mobile view and the available screen reader or
keyboard controls for checkout, search, Account, and their error states.

**Constitution principles**: III, IV, IX, XI, XII, XIII.

**Acceptance Scenarios**:

1. **Given** I am reading an error, an empty result, or a required review, **when** I navigate
   the view with text labels or assistive technology, **then** the state, primary action, and
   recovery path are understandable without emoji or color.
2. **Given** I switch journeys while an input is pending, **when** I enter text for the new
   step, **then** the previous form cannot consume it and existing valid cart or draft data
   stays intact.

### Edge Cases

- The active message may have been deleted, become uneditable, or belong to an earlier
  version of the bot. Recovery must respect the current shopper and policy.
- An old read may still be valid for a published gallery item while its old Add, Confirm,
  and Pay controls are invalid. Authorization applies again at the point of use.
- A terms page may be out of range after a policy edit. The current terms and a way back
  to checkout remain reachable where checkout is permitted.
- Search results may shrink, lose a cover image, become forbidden, or become empty.
  Back must prefer the nearest permitted page and leave a usable recovery when it cannot.
- A provider timeout may leave delivery uncertain. Repeated taps, recovery attempts, and
  keyboard restoration must avoid duplicate business effects and repeated chat messages.
- A paused store or revoked customer may have a narrower set of allowed actions.
  Recovery and refreshed navigation follow that narrower policy.

### Current and Proposed Behavior

Source review covered the shared customer handlers, both messaging adapters, and the
existing policy and conversation tests. The audit in Constitution v1.1.0 is the scope
baseline. The checked-in behavior below includes an existing checkout terms button
and a normal return path. This specification completes that journey through failure
and policy changes.

| Priority and journey | Current behavior observed in source | Proposed customer behavior |
| --- | --- | --- |
| P0 · Stale actions | The dispatcher acknowledges where supported, removes obsolete controls, and exits without giving the shopper a recovery view. Older gallery read actions have a separate authorized path. [Callback handling](../../services/shop_multibot_dispatch.py#L361) | Old mutations are blocked. The shopper receives a current authorized view or a usable recovery action without repeated messages. |
| P0 · Checkout terms | Review already has a terms button and normal terms pages can return to review. The copy still points to typed `/terms`. Changed-terms and invalid-page recovery can lose the checkout return path. [Checkout review](../../services/shop_cart.py#L936) · [Terms recovery](../../services/shop_customer_experience.py#L172) · [Review copy](../../services/shop_checkout_copy.py#L43) | The button is the normal route. All authorized checkout terms paths lead back to a valid review, with a clear fresh decision if the quote or terms changed. |
| P1 · Main keyboard | The shared menu respects the effective policy and can omit Cart. Both adapters independently install four fixed shortcuts, including Cart. [Menu policy](../../services/shop_customer_menu.py#L63) · [Telegram keyboard](../../channels/telegram.py#L311) · [Bale keyboard](../../channels/bale.py#L304) | Persistent shortcuts and Home agree on available actions and labels. Native keyboard differences preserve the same destinations. |
| P1 · Search and return | Search has an active query, field, and page. Its product view can use a generic return to products. Advanced field choices appear on entry, and results show one product per page. [Search entry](../../services/shop_customer_search.py#L88) · [Search results](../../services/shop_customer_search.py#L135) | Plain text is the first path. Back from a result restores the search, while Home and Cancel end pending input. |
| P1 · Browsing and media | Default catalog pages can emit four separate cards and a footer. Both adapters can post a separate keyboard message. Telegram attempts in-place photo edits, while Bale's adapter uses a replacement photo. [Catalog](../../services/shop_channel_catalog.py#L331) · [Telegram transport](../../channels/telegram.py#L291) · [Bale transport](../../channels/bale.py#L262) | Compact default pages use one active view. Optional media and galleries remain reachable. Replacement is limited to the provider behavior that needs it. |
| P2 · Account and language | Account presents many unrelated choices at once. Touched copy includes terms such as Contact and Client, and the linked-account list includes shortened internal bot identifiers. [Account](../../services/shop_customer_account.py#L233) · [Linked accounts](../../services/shop_customer_account.py#L457) | Group existing actions, use plain Persian and recognizable account references, and provide an accessible way back and out of errors. |

### Conversation Examples

These examples show the intended action order. Equivalent Persian wording is acceptable
if it preserves the meaning and names the next action.

| View | Example copy and action order |
| --- | --- |
| Stale control | «این دکمه دیگر فعال نیست.» Then «ادامهٔ خرید» or «منوی اصلی», depending on the allowed destination. |
| Checkout review | Show the amount, currency, and next effect. Actions in order are «پذیرش شرایط و ثبت سفارش», «مشاهدهٔ شرایط خرید», then «انصراف». For a supported split, name the two orders in the primary action. |
| Terms | Show the version and page position. Offer applicable «صفحهٔ قبل» and «صفحهٔ بعد», then «بازگشت به بررسی سفارش» and «منوی اصلی». |
| Search | «نام یا کد محصول را بنویسید.» Optional «فیلترهای جست‌وجو», then «لغو جست‌وجو» or «منوی اصلی». A product opened from search offers «بازگشت به نتایج». |
| Account | «مشخصات من», «نشانی‌های من», «ذخیره‌ها و مزایا», «تنظیمات و حریم خصوصی», then shared navigation. Use existing action names inside each group. |

### Telegram and Bale Regression Scenarios

Run each shared scenario with the same Store policy, inventory, and shopper history on
both platforms. Capture visible messages, button order, and relevant business outcomes.
The provider columns add cases where the current adapters differ. Mark simulated and
live-client results separately. These are acceptance scenarios for the feature, with
no claim of execution in this specification.

| Case and traceability | Shared acceptance setup and expected result | Telegram variant | Bale variant |
| --- | --- | --- | --- |
| R-01 · FR-001–003, FR-021–022 · SC-001 | From an old product or order view, tap Add, Confirm, or Pay twice after navigating away. Expect zero mutations, one usable recovery, and no duplicate messages. Also try an expired action with no current view. | Check an acknowledged obsolete button and a missing current message. | Check both the supported acknowledgement path and the legacy path that needs visible recovery without it. |
| R-02 · FR-001–003, FR-021 · SC-001, SC-008 | Use an old gallery read that remains allowed, then try the same read after catalog access is revoked and with a foreign Store or bot. The allowed read remains usable. Unauthorized cases disclose no restricted information and cause zero mutations. | Include a product with a photo. | Include a product with a text fallback. |
| R-03 · FR-004–007 · SC-002, SC-008 | Open long terms from checkout, reach the last page, return, and cancel. Repeat with explicit valid acceptance. Reading and canceling create zero records of consent, orders, or charges. Valid acceptance creates only the authorized outcome. | Run manual and instant checkout, including digital currency display. | Run manual and instant checkout with an eligible payment method. |
| R-04 · FR-004–007, FR-021–022 · SC-002, SC-008 | During terms review, change terms or quote, then try an invalid page and an old confirmation. Recover to checkout with current values and require a fresh decision. Also exercise missing terms and unavailable checkout. | Include mixed carts with two independently presented payment parts. | Include mixed carts and confirm the existing separate-order guidance and lack of a charge. |
| R-05 · FR-008–009, FR-020–022 · SC-003 | Compare a Store default, a bot override, and a cart-disabled policy. Change policy during a chat. Complete, cancel, and leave a native contact prompt. The refreshed keyboard matches allowed actions, and the old shortcut cannot act. | Check persistent keyboard restoration and correct verified-contact behavior. | Check supported keyboard restoration and the same verification distinction. |
| R-06 · FR-010–012, FR-020–022 · SC-004 | Search by text with and without a filter, reach page two, open a product, and go Back. Test Home, Cancel, expiry, no results, and a removed result. Preserve exact valid context and unrelated cart or draft state. | Include Back from a product preview. | Include Back when the preview had to be replaced. |
| R-07 · FR-013–016, FR-022 · SC-005, SC-008 | Browse nine eligible products across categories, including one without a cover and one uncategorized. Test Next, Back, a no-change repeat, a definite edit failure, and an unknown result. Count messages and active controls. | Check the supported edit and single-replacement cases. | Check text edits and the replacement photo path. |
| R-08 · FR-015–016, FR-021 · SC-005, SC-008 | Open permitted media and the optional gallery. Navigate away and back. Verify requested files, receipts, and support history stay usable, and unknown delivery does not replay. | Include a photo edit plus a requested file. | Include a replacement photo plus a requested file. |
| R-09 · FR-017, FR-020–022 · SC-006 | Start in Account, reach each existing allowed action, and resume a partially completed address draft. Try invalid input followed by navigation. Verify the old step ends without corrupting valid data. | Include navigating out of contact verification. | Include navigating out of contact verification. |
| R-10 · FR-018–020, FR-022 · SC-007 | Review narrow-screen and assistive navigation for stale recovery, checkout and terms, search, Account, and validation errors. Read the Persian copy and verify action meaning, currency direction, and a visible next step. | Use the available native client accessibility controls. | Use the available native client accessibility controls. |
| R-11 · FR-006–007, FR-015–016, FR-021–022 · SC-008 | Repeat an order decision, an authorized refund request, and a delivery or settlement notification in controlled tests. Verify the same business outcome, no duplicate side effects, and intact receipts. | Cover native invoice and current settlement rules. | Cover eligible Bale payment and existing settlement and mixed-cart guards. |

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: An expired, superseded, or out-of-scope action MUST cause zero changes to cart,
  account, consent, order, payment, and delivery state. A still-valid older gallery read MAY
  open currently permitted product details.
- **FR-002**: An authorized shopper pressing a stale action MUST get a valid current view or a
  visible recovery action to an allowed destination. If the original view cannot be restored,
  offer Home or permitted after-sales help without exposing restricted information.
- **FR-003**: Repeated taps on the same obsolete control MUST reuse the available recovery and
  produce zero duplicate business effects. Where the client supports it, retire obsolete
  controls. When a separate recovery message is needed, send at most one while that recovery
  remains usable.
- **FR-004**: The checkout review MUST offer an inline action to read the full applicable terms
  in one tap. Long terms MUST remain readable through pagination, with a return to checkout
  available on every terms page. The existing terms command remains an optional entry point.
- **FR-005**: Opening, paging through, or leaving terms MUST create zero consent records,
  orders, or charges and retain valid cart selections. With the same valid terms and quote, Back
  MUST return to the same review. Changed or unavailable terms, invalid pages, and changed
  quotes MUST offer a valid checkout recovery with an explanation.
- **FR-006**: Only the explicit order decision may record acceptance of the reviewed terms and
  continue order validation. Changed terms, quotes, ownership, availability, or payment
  eligibility MUST be rechecked. An older decision MUST never authorize a changed order or a
  charge. Missing required terms MUST continue to block order creation.
- **FR-007**: The review MUST make the amount, currency, delivery implications, and next effect
  visible. Preserve existing manual review, instant order, separate payment parts, and provider
  limitations. Keep payment execution and verification separate from opening terms or viewing a
  quote.
- **FR-008**: Home and the main Reply Keyboard MUST derive visible shortcuts from the same
  effective Store and bot policy and current capabilities. Keep configured order and equivalent
  Persian labels, and show only allowed destinations. Home MUST make all enabled destinations
  reachable.
- **FR-009**: After a policy change, the next authorized navigation or keyboard restoration MUST
  reflect current policy. An old shortcut MUST be rechecked before action. A temporary contact
  keyboard MUST restore policy-aware navigation on completion or exit. Inline controls remain
  contextual to the active view.
- **FR-010**: Back from a search result MUST restore the shopper's valid query, chosen filters,
  and page for the same Store, bot, and customer. Recheck results under current catalog access
  and use the nearest valid page if results shrink.
- **FR-011**: Home MUST leave the active search prompt. Cancel MUST end search, clear its
  pending input, and offer Home. An expired search MUST offer a fresh search or another allowed
  route. These transitions MUST preserve unrelated cart and safe draft data.
- **FR-012**: Search MUST accept a plain product name from its first view. Advanced filters MUST
  be optional and directly reachable. Empty results MUST offer a new search or authorized browse
  action.
- **FR-013**: Default Shop and Search MUST show multiple eligible products per page whenever at
  least two remain, with a visible page position and applicable paging controls. Browsing MUST
  work without a category and include eligible products without a cover or category.
- **FR-014**: Routine browsing, pagination, and cart navigation MUST prefer updating one active
  view. A supported successful edit and a no-change edit MUST add zero messages. A confirmed
  inability to edit MAY add one replacement and MUST leave one active set of navigation
  controls.
- **FR-015**: An unknown provider result MUST be distinguishable from a confirmed failure.
  Recovery MUST avoid sending a duplicate view or repeating an uncertain order, charge, or
  delivery. Native provider exceptions MUST preserve an actionable path where the current
  authorization allows one.
- **FR-016**: Product details, accessible previews, and requested files MUST remain available
  under current policy. Media and galleries remain deliberate actions. Preserve the existing
  ability to reopen or request permitted media and keep durable receipts, past support messages,
  and previously delivered files separate from editable navigation.
- **FR-017**: Account MUST show direct Profile and Addresses actions and two plainly named
  groups for the remaining existing actions, excluding shared Home and Back controls. Every
  existing allowed action MUST remain reachable. The address wizard MUST retain its existing
  review and safe resume behavior.
- **FR-018**: Touched customer-facing Persian copy MUST identify the action or outcome and the
  next safe step. Replace internal identifiers, unexplained system terms, and raw provider
  errors with understandable customer references. Keep material terms, legitimate order or
  product references, and currency visible.
- **FR-019**: Touched controls MUST have a readable text label and convey state without
  depending on emoji or color. Verify readable Persian right-to-left order, mixed-direction
  currency or reference text, and reachable actions on a narrow supported screen and through
  available assistive navigation.
- **FR-020**: Invalid input, empty results, and unavailable destinations in the changed journeys
  MUST show what happened and an allowed next action. Preserve valid entries when safe and
  prevent text intended for a new journey from being used by a previous form.
- **FR-021**: Existing authorization, checkout validation, catalog eligibility, verified
  contact, identity linking, refund, settlement, delivery, and replay protections MUST continue
  to hold on both platforms. No route through navigation or recovery may act across a Store,
  bot, or customer boundary.
- **FR-022**: Under equivalent policy and capabilities, both platforms MUST provide the same
  meaning, next actions, and business outcomes. Preserve legitimate differences in native
  acknowledgement, keyboard persistence, media edits, and payment methods. State material
  provider limitations before commitment.

### Key Entities

- **Effective menu policy** — The Store defaults, bot override, capabilities, and current
  permissions that determine which destinations a shopper can use.
- **Active view and action** — The current navigable conversation view, its controls, and
  the context needed to recognize an obsolete action.
- **Search context** — The shopper's current query, selected filters, result page, and
  return destination, bound to the current Store and bot.
- **Checkout review** — The current quote, applicable terms version, selected delivery
  details, order mode, and explicit decision.
- **Durable customer record** — A receipt, support reply, or delivered file that should
  remain available independently of editable navigation.

### Integration and Compatibility Risks

| Risk | Required acceptance evidence |
| --- | --- |
| Older messages and old navigation controls survive rollout. | Replay old Add, Pay, search, and gallery actions. Verify scoped recovery, continued authorized reads, and zero stale writes. |
| Configured menus and native keyboards change independently. | Compare Store and bot policies with both visible navigation surfaces before and after a policy change and a contact prompt. |
| Terms, prices, delivery choices, or permissions change mid-review. | Reopen and reprice the current review. Verify old acceptance is rejected, and no order or payment happens before a fresh valid decision. |
| Native acknowledgement, edit, media, and delivery behavior differ. | Capture paired transcripts for supported edits, definite replacements, and unknown outcomes. Verify one active set of controls and preserved durable media and records. |
| Search and draft state can overlap with cart or account input. | Switch among those journeys mid-form and repeat Back, Home, and Cancel. Verify the correct form receives the next message and valid unrelated data is preserved. |
| Shorter Persian copy can hide essential terms or break reading order. | Inspect both clients on a narrow screen, including long terms, mixed-direction amounts, and available assistive navigation. |

### Out of Scope

- New commerce capabilities, payment methods, order states, and provider integrations.
- OTP, Mini Apps, and new customer identity or consent mechanisms.
- Removing existing customer features, weakening authorization, or changing payment
  or delivery verification rules.
- Redesigning the administration dashboard or editing its policy rules. Existing
  controls are used to configure and verify the shopper experience.
- Changing cancellation, refund, or settlement semantics beyond clear recovery and
  copy for the touched paths. Broader order-cancellation redesign identified in the
  audit is outside this feature.
- Technical design, application implementation, rollout, and live payment execution.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All stale-action scenarios on both platforms produce zero mutations and leave a
  reachable permitted next action. Repeated obsolete taps add zero duplicate recovery messages
  while a usable recovery is present.
- **SC-002**: From checkout, terms open in one visible action with zero typed commands. Every
  terms page has a one-action return to a valid review or a clear path to refresh it. Reading
  creates zero consent, orders, and charges.
- **SC-003**: All paired policy cases show zero forbidden destinations on Home or the refreshed
  main keyboard. Every equivalent enabled destination keeps the same label, intent, and relative
  order.
- **SC-004**: All valid search Back cases restore the exact query, filter, and page unless
  inventory or access makes that page invalid. All Home, Cancel, and expiry cases leave a usable
  permitted next action.
- **SC-005**: In a catalog fixture with nine eligible products across multiple categories, a
  shopper can reach all nine without a category choice. Default pages show at least two products
  whenever at least two remain. Supported page turns add zero messages and confirmed fallback
  adds at most one, excluding deliberate media or gallery requests.
- **SC-006**: The first Account view has at most four Account choices, and every previously
  allowed action is reachable from that view within two selections. Address resume returns to
  the same valid step.
- **SC-007**: On both platforms, reviewers can identify the primary action, checkout effect, and
  recovery route from the touched Persian text alone. Every tested control has a text label and
  every required term and action stays reachable in the narrow-screen and assistive-navigation
  checks.
- **SC-008**: All paired acceptance scenarios preserve current authorization and
  order/payment/delivery outcomes. The review transcript shows zero duplicate business effects
  on repeated confirmation and zero unintended loss of requested media or durable receipts.

## Assumptions

- The paired scenarios use controlled shoppers, Store policies, products, and payment
  outcomes. Later validation uses simulated providers and separately authorized live
  client checks where native behavior needs confirmation.
- A fresh Search starts a new query. Back preserves valid context, while Home and Cancel
  leave pending search input. Existing security expiry and saved draft rules remain in force.
- Account groups reorganize existing actions under familiar labels. Profile and Addresses
  stay direct because they are used during verification and checkout.
- Client-controlled keyboard and edit behavior can vary. An exception may change the
  presentation while preserving an authorized route and the same business outcome.
