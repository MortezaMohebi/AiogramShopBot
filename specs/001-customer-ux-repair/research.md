# Research: Customer Experience Simplification and UX Repair

**Baseline:** checked-in source at `e636f4e`, inspected 2026-11-08. This is design evidence. No
provider calls, application tests, or timing benchmarks were run during planning.

## Repository baseline

| Surface | Current ownership and behavior | Gap or constraint |
| --- | --- | --- |
| Ingress and leases | `channels/contracts.py` normalizes private-chat identity. `services/shop_multibot_supervisor.py` owns receiver lease and durable update claims; `services/shop_runtime/ingress.py` first handles published workflow callbacks. `services/shop_multibot_dispatch.py` owns ordinary commerce; precheckout and settlement have separate paths. | A claim deduplicates one provider update, not separate updates produced by repeated taps. Preserve Runtime and financial routing order. |
| Active view and editing | `services/shop_multibot_dispatch.py` (`_send`, `dispatch`) tracks `ui_message_id` and handles callbacks. `channels/telegram.py` and `channels/bale.py` send, edit, remove markup, and acknowledge. | Stale handling precedes some current-policy checks, can terminate without recovery, and a message ID alone cannot distinguish controls after an in-place edit. Ack errors can interrupt handling. Broad error fallback can duplicate views. |
| Menu, contact and Account | `services/shop_customer_menu.py` resolves Store default, Bot override and capabilities. `services/shop_channel_catalog.py` renders Home. Adapters hard-code native shortcuts. `services/shop_customer_account.py` and `services/shop_address_wizard.py` own verification and address steps. | Home and the native keyboard can diverge. Account is flat. A native contact prompt must not persist after the user leaves; contact provenance remains enforced. |
| Search and forms | `models/shop_customer_navigation.py` stores bot-scoped state. `services/shop_customer_search.py` owns query/field/page and eligible results. `services/shop_customer_experience.py` clears stale forms. `services/shop_customer_support.py` uses the same active-form fields. | Search pagination bypasses expiry on some paths, details lack search-specific Back, and shared form expiry/reference can collide with a parked address draft. |
| Catalog and media | `services/shop_channel_catalog.py` lists four cards and a footer, and exposes deliberate gallery/detail callbacks. `services/shop_bot_catalog_acl.py` and scoped queries enforce publication/access. `channels/media_policy.py` routes media; media receipts track confirmed sends. | Default list creates chatter. Explicit old gallery reads are deliberately allowed only after current policy checks. Preserve text fallback, file access, explicit resend, and bot-scoped file cache. |
| Cart, terms and payment | `services/shop_cart.py` owns cart, preview and locked placement. `services/shop_checkout_policy.py` resolves applicable terms and policy fingerprint. `services/shop_customer_experience.py` renders Unicode-safe terms pages; `services/shop_checkout_copy.py` formats review. `channels/shop_payment_dispatch.py` executes payments separately. | Checkout has a Terms action and quote proof already. Changed/invalid terms recovery can lose checkout origin. Existing proof, locking, consent, split behavior and all payment verification remain authoritative. |
| Other customer messages | `services/shop_customer_orders.py`, `services/shop_orders.py`, `services/shop_engagement_flow.py`, support and checkout modules own customer copy; `services/shop_customer_notification_dispatch.py` and settlement paths deliver durable records. | Copy is distributed. Revise only touched messages. Preserve order references, reviewed totals, support history, paid notifications, and delivered files. |
| Validation and policy configuration | `tests/test_beta_conversation_ux.py`, `test_beta_terms_navigation.py`, both `test_*_channel_transport.py` suites, ACL and commerce tests; `compose.beta-qa.yml` and `scripts/beta_*_e2e.py`. Dashboard policy API: `dashboard/shop_customer_experience_api.py`; panel: `dashboard-next/components/blocks/customer-experience-policy-panel.tsx`. | Extend tests with recorded actual IDs, native markup, and business-state assertions. Existing dashboard is a test input; no policy redesign. |

## Decisions

1. **Decision:** Keep one coordinator in the existing commerce dispatch path. Bind ordinary
   inline actions to a versioned view and an allowlisted slot. Authorize recovery from live
   scope and policy before presentation. Preserve separately verified read-only gallery links.
   **Rationale:** UI validity cannot be inferred from provider message ID, and fake or old
   payloads must not trigger form clearing, invoice issuance or writes. **Alternatives:**
   message ID only fails on edits; signing every existing payload exceeds the 64-byte limit
   at boundary sizes; treating every old control as live weakens authorization.
2. **Decision:** Use one bounded nullable versioned JSON field on the existing chat-state row
   plus short compare-and-set updates. Serialize interactive processing per bot/user with a
   bounded process queue and PostgreSQL session advisory lock on the same checked-out
   connection as the ORM session. It survives existing handler commits and protects lease
   handoff. Fence finalization with the reservation and verify lease handling. **Rationale:**
   Durable generation, recovery and keyboard state must
   survive restarts and coordinate with independently expiring search/draft context. The
   existing 100-character `context_ref` is a live form field and cannot hold the action map.
   **Alternatives:** process memory loses proofs and recovery across restart; Redis introduces
   a new storefront consistency boundary; a row lock alone releases at handler commits;
   new tables and general event sourcing are disproportionate. No database transaction is
   held open across navigation provider I/O. PostgreSQL concurrency evidence is mandatory.
3. **Decision:** Reuse checkout policy fingerprint and existing cart/revision/quote proof as
   the terms origin. Factor a read-only review resolver from the existing preview, used for
   terms open/return, and keep `_place_order` the only explicit order/consent path.
   **Rationale:** Paginating text does not require creating a cart, accepting terms or
   preparing a payment. Changed policy/quote yields a fresh review, not implicit acceptance.
   **Alternatives:** a separate Terms consent action or new order/quote model would duplicate
   authority. Policy changes ordered before decision validation must be observed; verify the
   existing writer/reader ordering, and if necessary coordinate policy reads with the existing
   policy writers in the order transaction (including default/override insertion races).
4. **Decision:** Produce ordered, allowed actions once from effective policy; use them for
   Home and native keyboard restoration. Reuse query/filter/page and existing catalog ACL
   queries; render four products per default page with optional filters and gallery.
   **Rationale:** Consistency comes from one authorization and presentation model. Compact
   rendering preserves visibility of eligible products without exhausting media budgets.
   **Alternatives:** static adapter shortcuts, forced category or field choice, or another
   search service all add drift or steps.
5. **Decision:** Use a typed edit/send result and provider-specific capability checks. Unknown
   outcomes are quarantined; only confirmed inability to edit may replace once. Keep receipts
   and requested files out of the editable pointer. **Rationale:** An ambiguous response may
   follow a successful API call. **Alternatives:** falling back on all HTTP 400/404, blind
   retry, or deleting old chat history are unsafe. Exact no-change/uneditable responses are
   classified only with reviewed evidence; unrecognized errors take the conservative path.
6. **Decision:** Extend pytest/fake transports and the guarded PostgreSQL QA harness; use
   controlled native client checks only for provider behavior and accessibility.
   **Rationale:** Offline fixtures can prove domain outcomes and message counts, but cannot
   prove lock behavior or actual client rendering. The historical storefront runner hard-codes
   callback message ID 1 while fakes emit IDs above 100, omits edit endpoints, and uses a
   legacy one-line address. Commerce inherits this fixture. **Alternatives:** claiming old
   results for this branch, mocking all database concurrency, or requiring production tokens.

## Provider capability evidence

Attached official snapshot: `official_bot_docs_2026-11-02_complete.zip`, read in place as
reference only. Archive entry paths below refer to that snapshot.

| Area | Telegram | Bale | Design consequence |
| --- | --- | --- | --- |
| Edit message / preview | [Updating messages](https://core.telegram.org/bots/api#updating-messages), archive `telegram/bot-api.md:353–365`: text, caption, media and inline markup; adapter already tries photo edit and cached IDs. | [Edit text](https://docs.bale.ai/#editmessagetext), [caption](https://docs.bale.ai/#editmessagecaption), [markup](https://docs.bale.ai/#editmessagereplymarkup), `bale/bot-api.txt:871–894`; no documented equivalent media edit in snapshot. Current adapter clears markup and sends a replacement preview. | Keep Telegram media edits where supported; intentional Bale photo replacement is one supported transition, not an edit retry. Text edits and markup retirement remain provider-specific. Do not infer a general edit age from deletion rules. |
| Callback acknowledgement | [answerCallbackQuery](https://core.telegram.org/bots/api#answercallbackquery); adapter uses zero cache time. | [answerCallbackQuery](https://docs.bale.ai/#answercallbackquery), archive `bale/bot-api.txt:737–747`; current adapter skips legacy callback IDs beginning with `1`. | Ack is best effort, independent of business dispatch and visible recovery. Legacy clients use existing authorized view or visible route. |
| Reply/Inline keyboards | [ReplyKeyboardMarkup](https://core.telegram.org/bots/api#replykeyboardmarkup) supports a persistence hint; an edit accepts inline markup only (or none). | [ReplyKeyboardMarkup](https://docs.bale.ai/#replykeyboardmarkup), `bale/bot-api.txt:362–390` documents keyboard/contact/removal; does not promise Telegram persistence or one-time flags. | Explicitly restore allowed shortcuts after contact and on policy drift, without relying on client flags for authorization. Never install Reply Keyboard via edit or mix both markups in one send. Use visible text labels. |
| Payload and media limits | [Inline buttons](https://core.telegram.org/bots/api#inlinekeyboardbutton), [sending files](https://core.telegram.org/bots/api#sending-files); shared limits below. | Archive `bale/bot-api.txt` includes 1–64 callback bytes, 4096 text and bot-scoped IDs; media/caption constraints vary by method. | Keep shared max 4096 text, 64 callback UTF-8 bytes and 1024 preview caption; existing terms chunking remains. Preserve current uploads and adapter limits (e.g. decimal 10 MB photo/50 MB other project limits where applicable, and conservative voice-to-document routing). Do not infer universal URL or multipart limits from a different method. |
| Failures, throttling and uncertainty | Current generic bad request can cause a resend. [Telegram FAQ](https://core.telegram.org/bots/faq#my-bot-is-hitting-limits-how-do-i-avoid-this) calls out rate limits. | Current adapter accepts broad HTTP 400/404 on edits; timeout, malformed response or network failure can be ambiguous. No comparable Bale rate guarantee used. | Scope exact known edit errors per adapter and operation, with response fixtures; no fallback for bad content, throttling or ambiguous results. Native behavior for error wording, retired controls, contact restoration and assistive navigation remains to be verified during implementation. |

## Technical risk register

| Risk | Impact | Mitigation and release evidence |
| --- | --- | --- |
| Lease handoff or concurrent distinct callbacks | Stale writes, out-of-order edits | Same-chat ordering and fenced writes, no provider replay after unknown; PostgreSQL overlap/restart/barrier tests and durable deltas (R-01, R-11). |
| Old messages/rolling receiver cutover | Inert shortcuts or unsafe writes | Additive schema first, controlled single-receiver cutover, legacy safe reads and authorized recovery. No downgrade that accepts obsolete actionable controls without an explicit compatibility review (R-01–02). |
| Terms or quote changes mid-review | Wrong consent/order amount | Preserve authoritative final validation, test same-version text edits, policy transitions and price/delivery/payment drift; no order or charge until valid explicit decision (R-03–04, R-11). |
| Provider delivery ambiguous or markup cannot be removed | Duplicate messages or visually old buttons | Per-adapter conservative outcomes; backend generation invalidates controls independently of visual cleanup; paired transcripts with no-change, definite failure and unknown (R-07–08). |
| Policy/draft context overlap | Forbidden shortcut or loss of data | Live policy lookup and distinct search/draft lifetimes; validate current input ownership before routing text (R-05–06, R-09). |
| Short copy or RTL changes obscure meaning | Accidental decisions, inaccessible navigation | Check amounts, delivery, terms and action labels with native narrow-screen/assistive Persian review (R-10). |
| Historical fakes accept wrong assumptions | False release confidence | Repair fixture IDs and transport results; keep offline, PostgreSQL and native evidence labeled separately. |

No unresolved architecture decision blocks task breakdown. Provider-client behavior listed above
is a validation gate; it is not presumed supported. Unknown transport outcomes already have a
defined safe behavior.
