<!--
Sync Impact Report
Version change: 1.0.0 → 1.1.0 (MINOR, new principles and materially expanded review guidance).
Modified principles:
  I. Calm by Default, Powerful by Choice → I. Minimal Cognitive Load and II. Progressive Disclosure
  II. Navigation Is Predictable and Recoverable → IV. Predictable Navigation and IX. Recoverable Errors
  III. Keep One Active Shopping View → V. Contextual Actions and VI. Minimal Message Clutter
  IV. Security at the Point of Risk → VIII. Low-Friction Checkout and X. Security at the Point of Risk
  V. Consistent Intent Across Telegram and Bale → XI. Telegram and Bale Parity
Added principles: III. Conversation First, VII. Clear Product Discovery,
  XII. Accessible and Localized Interaction, XIII. Plain Customer Language.
Expanded sections: Conversation Standards, Design and Review Gates, Governance.
Added content: source inventory, callback and message baseline, implementation priorities,
  and six required review fields per principle.
Removed sections: none.
Follow-up TODOs: none.
-->

# AiogramShopBot UX Constitution

## Core Principles

### I. Minimal Cognitive Load
**Purpose.** Make the next decision apparent at a glance.

**Mandatory rules.** Each view that needs a decision MUST state its purpose and present one
primary action or input. Related choices MAY form one choice group. Keep the current item, cart,
or order status visible when it affects that decision.

**Forbidden anti-patterns.** Competing primary actions, multiple unrelated questions in one
prompt, and duplicate actions that perform the same task in the same context.

**Allowed exceptions.** Home is a destination chooser. A review screen MAY show several facts
and offer an explicit edit or cancel action beside the primary confirmation.

**Measurable acceptance criteria.** For a default browse, search, cart, or address transcript,
identify one primary task at each decision. Count one requested input per text prompt and zero
duplicate actions within a view.

**Repository example.** Account currently displays profile, addresses, credit, wishlist, linked
accounts, referrals, notifications, language, and privacy together. Grouping these by intent
would retain access while shortening the first Account view.
[Account menu](../../services/shop_customer_account.py#L233)

### II. Progressive Disclosure
**Purpose.** Keep the first view calm while making advanced choices reachable.

**Mandatory rules.** Open Search ready for ordinary text. Place field selection, filters, full
descriptions, and other optional detail behind clear controls. Essential price, availability,
terms, and limitations MUST be visible before the decision they affect.

**Forbidden anti-patterns.** Required filter selection, expanding every optional control on
entry, or hiding a material term behind an optional detail control.

**Allowed exceptions.** Ask a focused clarification when the current input cannot safely
identify the intended item or action.

**Measurable acceptance criteria.** Starting at Search, a plain product name MUST reach results
in one text turn. A customer MUST be able to open a named advanced control and return with their
query and applicable filters retained.

**Repository example.** Search starts with the default field set to all, but it renders four
field choices up front. Keep the existing plain-text path and expose the field choices through
an explicit action. [Search entry](../../services/shop_customer_search.py#L88)

### III. Conversation First
**Purpose.** Let customers shop with familiar chat actions.

**Mandatory rules.** Core journeys MUST work through native chat messages and keyboards. Free
text MUST be routed to the current step and scoped to the verified bot and customer. Navigation,
cancel, and commands MUST take precedence over pending free-text input.

**Forbidden anti-patterns.** Making customers memorize commands or structured syntax to complete
a routine task, routing a navigation label into an old form, and introducing Mini Apps.

**Allowed exceptions.** Existing provider payment interfaces, authorized support links, and
deliberate cross-bot identity linking MAY leave the current chat step. State the destination and
next action.

**Measurable acceptance criteria.** Complete browse, search, cart, address, order, and support
journeys using visible controls and ordinary text. With an old form pending, select another
destination and prove the next input cannot populate the old form.

**Repository example.** The dispatcher clears cart and customer input on navigation. The
existing regression covers choosing Search while a cart form is pending.
[Navigation cleanup](../../services/shop_customer_experience.py#L72) ·
[Navigation regression](../../tests/test_beta_cart_form_navigation.py#L57)

### IV. Predictable Navigation
**Purpose.** Give customers a dependable route forward, back, and out.

**Mandatory rules.** Use the main Reply Keyboard for stable, enabled destinations. Home MUST
make the configured shared destinations reachable in their configured order. Use explicit Back,
Home, Cancel, or Resume where relevant. Back MUST restore valid query, filter, page, cart, or
draft context. Cancel MUST end pending input and state the result when a draft is discarded.

**Forbidden anti-patterns.** Policy-blind shortcuts, unnecessary keyboard replacement, ambiguous
Back destinations, and silent loss of a valid draft.

**Allowed exceptions.** The native contact request MAY temporarily replace the Reply Keyboard.
Restore the main keyboard after completion or exit. If context expires, state what happened and
offer the closest safe destination.

**Measurable acceptance criteria.** On both platforms, configure a missing or disabled
destination and confirm there is no misleading shortcut. From a paginated result, open an item
and return to the same page. Leave and resume an address draft at the same valid step.

**Repository example.** The dynamic Home menu filters Cart when disabled, while both adapters
hard-code Cart in the Reply Keyboard. The address wizard already demonstrates Pause and Resume.
[Menu policy](../../services/shop_customer_menu.py#L63) ·
[Telegram keyboard](../../channels/telegram.py#L311) ·
[Bale keyboard](../../channels/bale.py#L304) ·
[Address wizard](../../services/shop_address_wizard.py#L130)

### V. Contextual Actions
**Purpose.** Keep controls tied to the item and the decision they act on.

**Mandatory rules.** Inline Keyboards MUST expose applicable actions for the current item, page,
or form. Hide actions known to be unavailable. The backend MUST recheck scope, capability, and
relevant state or version before any mutation. Superseded controls MUST be retired when
supported and blocked at execution.

**Forbidden anti-patterns.** Executing a stale mutation, showing a Pay or Add action known to be
unavailable, and treating a hidden button as authorization.

**Allowed exceptions.** An older gallery card MAY open current product details through a
read-only action after a fresh catalog check. Any subsequent mutation MUST use the newly
rendered current controls.

**Measurable acceptance criteria.** After moving to a new view or changing a quote, an old Add,
Confirm, or Pay action MUST cause zero mutations. An allowed old gallery card MUST open only a
product visible under current policy.

**Repository example.** The dispatcher rejects a callback from a superseded message and permits
scoped gallery reads. The paired tests cover stale cart actions and older gallery cards.
[Callback guard](../../services/shop_multibot_dispatch.py#L361) ·
[Conversation tests](../../tests/test_beta_conversation_ux.py#L167)

### VI. Minimal Message Clutter
**Purpose.** Keep the conversation easy to scan and preserve meaningful history.

**Mandatory rules.** Routine navigation MUST prefer editing the active view. A confirmed
inability to edit MAY produce one replacement active view. A no-change edit MUST count as an
already rendered view. Treat unknown outcomes separately from confirmed edit failures.
Acknowledge callbacks through the supported provider path and retire superseded controls.

**Forbidden anti-patterns.** Reposting unchanged views, sending a separate acknowledgement
message when the visible view already confirms the action, and reusing a receipt or delivered
attachment as the editable view.

**Allowed exceptions.** Durable receipts, support messages, consented notices, requested files,
and deliberately opened bounded galleries MAY use separate messages. Provider-required keyboard
or media fallback MAY add the minimum output needed. It MUST preserve earlier media and leave
one current navigation set.

**Measurable acceptance criteria.** For a supported text edit, a Next or Back tap adds zero chat
messages. A confirmed edit failure adds at most one replacement outside documented exceptions. A
no-change edit adds zero. Verify receipts and requested media remain usable after navigation.

**Repository example.** Both transports send new gallery cards and a footer per page. Telegram
attempts in-place photo edits, while Bale's adapter sends a replacement photo. Telegram's text
edit fallback handles the broad bad-request class, creating a duplicate risk for a no-change
response. [Telegram transport](../../channels/telegram.py#L291) ·
[Bale transport](../../channels/bale.py#L262)

### VII. Clear Product Discovery
**Purpose.** Make products easy to find and compare in a chat.

**Mandatory rules.** Shop and Search MUST expose eligible products without requiring a category.
Categories MAY narrow the view. Default discovery MUST show multiple eligible products per page
when at least two are available, with a visible position and usable pagination when needed. A
product without a cover MUST remain selectable. Requested media MUST stay available subject to
current access policy.

**Forbidden anti-patterns.** Category gates, single-item default paging when multiple eligible
results are available, hidden products exposed by an old link, and deleting customer-requested
media during navigation.

**Allowed exceptions.** One eligible result MAY use a single card. An explicitly chosen detailed
view MAY show one product at a time. If native media is unavailable, use an accessible text card
and preserve access to the media through its authorized route.

**Measurable acceptance criteria.** With nine eligible products across two categories, including
an uncategorized product and one without a cover, open Shop without selecting a category, page
across all nine, open one and return to the same page. Search MUST show multiple matching
products when present, and must expose zero disallowed items.

**Repository example.** Shop opens the all-products listing and currently supports four cards
per page. Search currently sets its page size to one. Product media is separately routed by the
catalog. [Catalog listing](../../services/shop_channel_catalog.py#L307) ·
[Search pagination](../../services/shop_customer_search.py#L135) ·
[Media route](../../services/shop_channel_catalog.py#L544)

### VIII. Low-Friction Checkout
**Purpose.** Make the purchase decision clear and avoid avoidable work.

**Mandatory rules.** Reuse eligible saved details. For a new shipping address, use the shared
wizard with one field per step, Back, Cancel, safe Resume, and review before save. Ask for
shipping details only when required. Before commitment, show the final total and currency,
material terms, shipment or delivery implications, and whether the next step creates a request,
an order, or a payment. The checkout review MUST provide a visible way to open the applicable
terms and return to the review.

**Forbidden anti-patterns.** Collecting a shipping address for a digital-only purchase, forcing
customers to re-enter valid saved data, charging from a preview, and adding redundant
confirmations to the same decision.

**Allowed exceptions.** Require a fresh review when a quote or its terms change. Keep a legally
or provider-required confirmation and explain any separate payment parts before commitment.

**Measurable acceptance criteria.** Exercise a physical checkout with a saved address, a new
address, and a digital-only checkout. Count zero shipping prompts for digital-only and zero
repeated valid fields for the saved-address path. Duplicate confirmation MUST produce one
committed checkout outcome, with independently paid parts shown where applicable. Open terms and
return without losing the quote.

**Repository example.** Cart already delegates address selection to Account, and the shared
wizard saves only after confirmation. Checkout also separates preview from provider payment.
[Cart address entry](../../services/shop_cart.py#L714) ·
[Address review](../../services/shop_address_wizard.py#L224) ·
[Checkout preview](../../services/shop_cart.py#L868)

### IX. Recoverable Errors
**Purpose.** Tell customers what happened and give them a safe next step.

**Mandatory rules.** For invalid input, no results, expired state, unavailable actions, and
known failures, show a plain-language explanation and a useful recovery action. Preserve valid
input and cart data when safe. Label uncertain external outcomes truthfully and provide a status
or support route. Reconcile uncertain money movement or delivery before retrying.

**Forbidden anti-patterns.** Silent dead ends, generic retry prompts after a possibly completed
external action, clearing valid entries on a field error, and claiming success without verified
evidence.

**Allowed exceptions.** Ignore unrelated or unauthenticated traffic when replying would disclose
information or bypass policy. An obsolete control MAY recover through a current view or a brief
native notice with a usable next step.

**Measurable acceptance criteria.** Exercise an empty search, invalid field, expired callback,
and uncertain provider response. Every authorized case has a visible recovery route and
preserves applicable valid data. Uncertain outcomes trigger zero automatic duplicate side
effects.

**Repository example.** Empty search already offers alternatives. A stale shopping callback
currently clears controls and returns a status without a customer-facing recovery view.
[Empty search](../../services/shop_customer_search.py#L158) ·
[Stale callback path](../../services/shop_multibot_dispatch.py#L361)

### X. Security at the Point of Risk
**Purpose.** Protect accounts and transactions while keeping ordinary shopping easy.

**Mandatory rules.** Require only the proof needed for the current operation and reuse valid
proof when policy permits. Explain the reason in customer language at the point of need. Require
explicit confirmation for payment, refund, account linking, and destructive actions. Preserve
backend Store, bot, and customer checks, catalog access, expiry, and replay protections. Use
supported proof, such as the sender's own native contact or the existing verified linking flow.
A destructive action that changes an order MUST provide a review step before the state change.

**Forbidden anti-patterns.** Weakening backend security, asking for proof to browse public
items, treating typed or third-party contact data as proof, exposing credentials or private
data, and assuming an SMS OTP service exists.

**Allowed exceptions.** A typed phone number MAY be collected as contact information when
needed. It carries no ownership proof. A stronger check MAY be required by policy, provider, or
risk and MUST preserve the customer's safe progress. A clearly labeled request for review MAY
submit directly when it moves no money and leaves the order intact.

**Measurable acceptance criteria.** Anonymous-to-the-store browsing asks for zero verification
prompts when bot context permits it. Test sender-owned contact, typed and foreign contacts,
expired proof, unauthorized bot or Store, and repeated confirmation. Only properly scoped and
verified requests may mutate protected data.

**Repository example.** The Account flow distinguishes the sender's own contact from contact
information, and linking has separate claim and approval steps.
[Contact verification](../../services/shop_customer_account.py#L36) ·
[Identity linking](../../services/shop_identity_links.py#L87)

### XI. Telegram and Bale Parity
**Purpose.** Keep the meaning of a journey consistent across messaging platforms.

**Mandatory rules.** Under equivalent capabilities and policies, both platforms MUST use the
same action intent, destination labels, decision sequence, confirmation meaning, and recovery
paths. Shared services MUST own authorization and business state. Adapters MUST respect provider
capabilities and limits. Disclose a material limitation before commitment and give a supported
alternative.

**Forbidden anti-patterns.** Exposing a provider-unsupported action, requiring extra business
steps solely because of presentation differences, and pretending an unavailable provider
capability succeeded.

**Allowed exceptions.** Native acknowledgement, keyboard persistence, media replacement, payment
rails, and provider timing MAY differ. A capability exception MUST document the actual
difference, fallback, and customer-visible outcome.

**Measurable acceptance criteria.** Compare paired transcripts for the same policy and
inventory. Match semantic actions and outcomes. For each provider exception, test the fallback
and confirm the customer sees the consequence before committing.

**Repository example.** The Bale adapter skips a callback acknowledgement for its legacy ID path
and uses a replacement preview. Telegram has an in-place preview path. Checkout supports split
Telegram payments and asks customers with mixed Bale carts to place separate orders.
[Bale acknowledgement](../../channels/bale.py#L528) ·
[Telegram preview](../../channels/telegram.py#L36) ·
[Mixed-cart guard](../../services/shop_cart.py#L120)

### XII. Accessible and Localized Interaction
**Purpose.** Make actions and status understandable on narrow screens and with assistive
technology.

**Mandatory rules.** Use plain, consistent Persian labels and right-to-left layout where
applicable. Text MUST carry the action, outcome, and currency without relying on emoji, color,
or an image. Preserve readable order for mixed-direction values. The dashboard MUST support
keyboard navigation, visible focus, named controls, and feedback that assistive technology can
read.

**Forbidden anti-patterns.** Emoji-only actions, status conveyed only by color, unreadable
mixed-direction prices, clipped required terms, and a language control that implies unsupported
languages can be selected.

**Allowed exceptions.** Official brand names, order references, and searchable product codes MAY
retain their original script. An unsupported language MAY be described as information with a
clear way back.

**Measurable acceptance criteria.** Review a narrow mobile view and a keyboard or screen-reader
pass for the changed journey. Every actionable control has a text name, prices include an
unambiguous currency, and no required term or action is clipped.

**Repository example.** Persian action labels are shared in the menu. Account exposes a Language
action that reports Persian as the only active language. The dashboard already documents its
Persian RTL design. [Menu labels](../../services/shop_customer_menu.py#L20) ·
[Language action](../../services/shop_customer_account.py#L537) ·
[Dashboard overview](../../dashboard-next/README.md)

### XIII. Plain Customer Language
**Purpose.** Give people the information needed to act without making them learn system
internals.

**Mandatory rules.** Customer copy MUST describe what happened, what is needed now, and what the
customer can do. Put implementation details in operator diagnostics. Explain a technical or
provider term only when it affects an actual decision.

**Forbidden anti-patterns.** Raw exceptions, callback identifiers, internal bot identifiers,
provider error codes, and jargon that has no customer purpose.

**Allowed exceptions.** A customer-facing order reference, product code, currency, or support
reference MAY appear where it helps the customer identify or resolve a real issue. Introduce it
in familiar language.

**Measurable acceptance criteria.** Review customer-visible copy in both transcripts. Find zero
unexplained internal identifiers or technical error details. A customer can tell what an error
means and name their next safe action without inspecting a log.

**Repository example.** Profile uses Contact and Client terminology, and linked-account output
exposes a shortened bot identifier. A customer-facing bot name and an explanation of the
ownership check would serve the same purpose.
[Profile and verification copy](../../services/shop_customer_account.py#L252) ·
[Linked accounts](../../services/shop_customer_account.py#L457)

## Conversation Standards

**Calm by Default, Powerful by Choice.** AiogramShopBot is a multi-bot conversational
commerce platform for Telegram and Bale with a Next.js administration dashboard. Its mission
is to make customer journeys intuitive, predictable, and easy to scan. This constitution covers
customer-facing chat and notifications, published workflows that appear in chat, and dashboard
controls that shape or support those experiences. [Project overview](../../readme.md)

**Customer journey inventory.** This inventory describes the checked-in paths. Store policy,
bot capability, customer authorization, and publication status determine availability.

| Journey | Current surface |
| --- | --- |
| Entry and help | Start, Home, menu shortcuts, FAQ, terms, and maintenance or paused after-sales access. [Catalog](../../services/shop_channel_catalog.py#L87) · [Shared dispatcher](../../services/shop_multibot_dispatch.py#L47) |
| Discovery | All-products and category browsing, search and field selection, product details, reviews, and requested images or files. [Catalog](../../services/shop_channel_catalog.py#L307) · [Search](../../services/shop_customer_search.py#L88) |
| Cart and checkout | Add, change quantities, remove, apply a coupon, choose an address and shipping method, review terms and totals, and submit a manual or instant order. [Cart](../../services/shop_cart.py#L177) |
| Orders and payments | History, order details, shipping tracking, provider invoices or eligible Store credit, settlement, cancellation, and refund requests. [Orders](../../services/shop_orders.py#L63) · [Order details](../../services/shop_customer_experience.py#L260) · [Payment dispatch](../../channels/shop_payment_dispatch.py#L30) |
| Delivery and support | Physical delivery status, paid digital delivery, support tickets and replies, and order or payment assistance. [Settlement](../../services/shop_multibot_dispatch.py#L265) · [Customer support](../../services/shop_customer_support.py#L112) · [Acceptance baseline](../../docs/qa/BETA_STOREFRONT_P0_P6_ACCEPTANCE.md) |
| Account and preferences | Profile, contact verification, address book, wishlist, identity linking, language, privacy, and notification preferences. [Account](../../services/shop_customer_account.py#L96) · [Address wizard](../../services/shop_address_wizard.py#L130) |
| Engagement and automation | Store credit, referrals, stock alerts, consent-based campaigns, operational notifications, and published workflow steps and callbacks. [Engagement](../../services/shop_engagement_flow.py#L54) · [Notification dispatch](../../services/shop_customer_notification_dispatch.py#L45) · [Workflow ingress](../../services/shop_runtime/ingress.py#L90) |
| Operator controls | Store and bot menu and checkout policies in the dashboard, plus order, support, and campaign controls that shape customer outcomes. [Policy panel](../../dashboard-next/components/blocks/customer-experience-policy-panel.tsx) · [Policy API](../../dashboard/shop_customer_experience_api.py#L105) |

**Message and callback baseline.** Both adapters render shared `BotReply` data. For the
standard shopping path the dispatcher normalizes the update, acknowledges supported callbacks,
checks the active view, clears stale form input, runs the scoped handler, then edits or sends
the reply. Published workflow ingress has its own acknowledgement path. Native payment
updates use dedicated validation and settlement paths. [Reply contract](../../channels/contracts.py) ·
[Shared dispatcher](../../services/shop_multibot_dispatch.py#L338) · [Workflow ingress](../../services/shop_runtime/ingress.py#L57)

**Source audit and implementation order.** These are source observations and priorities for
later feature specifications. Historical acceptance reports describe their recorded commits.

1. Make rejected actions recoverable while preserving backend guards. The stale callback path
   strips buttons and returns a status without a recovery view. The checkout confirmation
   points customers to typed `/terms`, and cancellation of an unpaid request commits directly
   from its order-history button. Give customers a safe next view, a visible route to terms,
   and review of consequential cancellation. [Stale callbacks](../../services/shop_multibot_dispatch.py#L361) ·
   [Checkout copy](../../services/shop_checkout_copy.py#L43) · [Cancellation](../../services/shop_orders.py#L276)
2. Make navigation policy-aware and recover context. Static Reply Keyboards expose four
   destinations independent of the configured menu. Search builds a product view without
   a search-specific return target. Align Reply and Inline actions with policy and preserve
   the originating result context. [Menu policy](../../services/shop_customer_menu.py#L63) ·
   [Telegram keyboard](../../channels/telegram.py#L311) · [Bale keyboard](../../channels/bale.py#L304) ·
   [Search view](../../services/shop_customer_search.py#L173)
3. Reduce routine message volume and make discovery comparable. A catalog page can emit
   four new product messages plus a footer on either platform. Search starts with four field
   choices and renders one result per page. Keyboard restoration with Inline actions can add
   a separate message. Keep product media reachable while making default lists compact,
   keeping advanced filters optional, and separating durable milestones from editable views.
   [Catalog](../../services/shop_channel_catalog.py#L331) · [Search](../../services/shop_customer_search.py#L88) ·
   [Telegram send](../../channels/telegram.py#L291) · [Bale send](../../channels/bale.py#L262)
4. Simplify Account and review Persian copy. The Account view presents many unrelated choices
   together, and verification and linked-account views expose implementation terms. Group
   options by intent, use customer-facing names, and review both providers' transcripts and
   dashboard control labels. [Account and verification](../../services/shop_customer_account.py#L233) ·
   [Linked accounts](../../services/shop_customer_account.py#L457)

**Provider differences to preserve.** The current code uses different photo replacement and
callback acknowledgement paths, including a legacy Bale acknowledgement exception. Mixed carts
use independent order/payment parts on Telegram and a separate-order instruction on Bale.
Customer guidance MUST reflect the supported outcome before commitment.
[Telegram preview](../../channels/telegram.py#L36) · [Bale send](../../channels/bale.py#L262) ·
[Bale acknowledgement](../../channels/bale.py#L528) · [Mixed checkout](../../services/shop_cart.py#L120)

## Design and Review Gates

- A feature specification MUST map affected journeys to principle IDs and record the
  default path, optional controls, copy and button order, Back and Cancel behavior, and
  relevant errors. The plan MUST define how to check the measurable criteria and handle
  provider exceptions. Existing features MUST remain reachable during UX changes unless a
  maintainer explicitly approves a separate removal.
- The implementation review MUST include before-and-after transcripts or equivalent
  assertions for the affected steps on Telegram and Bale. Check state transitions, number of
  messages, active keyboards, and what remains available after leaving and returning.
  Include the relevant dashboard policy controls when behavior is configurable.
- Where relevant, verify stale and repeated callbacks, invalid or expired input, current
  authorization, delayed or unknown results, and zero duplicate side effects. For checkout,
  verify amount, currency, ownership, order state, and visible receipts. For localized
  changes, include a narrow-screen and assistive-technology review.
- Evidence MUST distinguish source inspection, simulated adapters, and live-client checks.
  Record any provider behavior that still requires live verification before claiming it
  works on the provider. Existing tests give starting points for paired transcripts.
  [Conversation tests](../../tests/test_beta_conversation_ux.py) ·
  [Catalog tests](../../tests/test_shop_channel_catalog.py) ·
  [Acceptance baseline](../../docs/qa/BETA_STOREFRONT_P0_P6_ACCEPTANCE.md)

## Governance

This constitution governs feature specifications, plans, reviews, and UX refactoring for the
stated scope. Contributors and AI agents MUST cite applicable principle IDs and verify the
corresponding criteria for every affected journey. Reviewers MUST resolve unmet requirements
in the changed flow before approval. Document pre-existing gaps separately so they can be
specified and addressed without quietly expanding the current change.

Amendments MUST record the proposed change, rationale, affected journeys, and transition steps
for behavior or tests. A maintainer MUST approve the amendment. Use MAJOR for incompatible
changes or removals, MINOR for added principles or materially expanded guidance, and PATCH for
clarifications that preserve obligations. Preserve the original ratification date and record the
amendment date. Provider exceptions remain subject to current authorization and safety rules.

**Version**: 1.1.0 | **Ratified**: 2026-11-08 | **Last Amended**: 2026-11-08
