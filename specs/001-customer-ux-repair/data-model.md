# Data model: Customer navigation and checkout context

This is a design for extending existing state, not a schema or API replacement.

## Scope and storage

- **Conversation:** authenticated ingress supplies platform and bot; the bot supplies Store.
  Normalized private-chat user identifies the shopper. Every lookup/mutation uses
  `(bot_id, platform_user_id)` plus matching Store and private-chat identity. Never derive
  scope, ownership or roles from a callback. Recheck current runtime, block and capability
  policy before recovery or action. Existing owned refund and paused after-sales exceptions
  retain their exact gates.
- **ShopCustomerChatState:** keep the existing key, action enum, `context_ref`,
  `address_draft`, `query_text` (100 chars), `query_field` (all/name/sku/description),
  `page` (0…10000 stored zero-based), `expires_at`, and confirmed `ui_message_id`.
  Extend the same row with one nullable SQLAlchemy JSON column, `view_state`. Candidate
  revision `20261108v001_customer_view_state.py` follows inspected head `20261107u004`;
  verify head again at implementation. No new table, index, enum, backfill or database
  rewrite. Apply before receiver cutover; old null/unknown-format state cannot authorize
  legacy consequential controls. Preserve old chat/draft data when initializing, and use
  scoped lazy adoption only for valid legacy fields. No destructive reset.
- **Bounded envelope:** version; active and pending view metadata (one each);
  one recovery marker; native keyboard/contact installation status; search stage/expiry;
  parked address resume metadata. A view stores generation, expiry, typed safe return target,
  visible-content/semantic signature and allowlisted logical callback slots (at most 32).
  Pending state also stores the operation token and confirmed, failed or unknown disposition
  as applicable; record a target ID only when known. Keep at most one quarantined target,
  and never pick an unknown target for future edits. Persist only bounded, validated routing
  references and fingerprints, no message text, raw provider payloads, credentials,
  addresses or financial data. Cap encoded JSON at 16 KiB, reject unknown formats safely, and avoid
  logging contents. New actionable views expire after at most 30 minutes; domain-specific
  review and search lifetimes still apply. Only confirmed current visible controls gain a
  new expiry; no implicit renewal of an old control.
- **Effective menu:** resolve Store default, Bot override and live capabilities through
  `effective_menu`; filter by current available actions and keep configured order. Store
  only a fingerprint plus installation state. It describes what was last installed and
  never grants access.
- **Search:** existing query/field/page hold the result snapshot, `view_state.search`
  distinguishes input/results/detail and owns the existing 15-minute search TTL. Start
  in plain-name input (default field), offer optional fields, and preserve a scoped Back
  through details and preview. End text capture before opening a result. Back and page
  turns validate expiry and current ACL, clamp to the closest valid page and persist it.
  When the page loses all rows during a concurrent catalog change, clamp/requery once
  then show an authorized empty state. Home and Cancel end search without altering cart or
  safe drafts. Expired context has a fresh Search or another allowed route.
- **Address and other forms:** `action`, `context_ref` and `expires_at` identify the
  currently awaited field only. Keep address values in `address_draft`; park the resumable
  step, its original expiry and origin in the envelope before switching flows. Adopt only
  valid legacy resume state with enough information; never renew expired drafts or commit
  an address merely by navigating. Existing address wizard validation, step-by-step input,
  review, and confirm stay intact. Explicit navigation wins before free text is routed;
  verify native contact against the active prompt and existing contact provenance rules.
- **Checkout:** derive review from existing scoped cart/revision, terms fingerprint, quote
  proof, address/shipping selection, order mode and payment eligibility. Terms paging and
  Back carry a typed checkout origin with non-sensitive cart/review references, resolved
  server-side. No independent consent, cart, quote, charge or order record is introduced.
  Rebuild a read-only review and compare current policy and proof on Back; use existing
  authoritative locked placement/consent path after an explicit fresh decision.
- **Durable records:** orders, consent, settlement, refunds, deliveries, support history
  and `ShopCustomerMediaReceipt` stay in their current tables/flows. A receipt, requested
  file or delivered message is not an editable view; its allowed read shortcut rechecks
  live scope. An action that can write from a durable message leads through a current
  authorized view; it never acts as a legacy authorization proof.

## View lifecycle and consistency

| State | Transition and invariant |
| --- | --- |
| Uninitialized / confirmed | Validate fresh private scope; for ordinary callbacks require matching message ID, current generation, slot and expiry. Inactive, unauthorized, foreign or invalid slots never invoke a mutating handler. Legacy allowlisted reads requery ACL; do not expand this exception by string prefix alone. |
| Action reserved | While serialized, atomically consume the active generation before invoking a consequential action. Keep current domain transaction, receipt and idempotency guards. Do not consume or clear an unrelated form on stale input. A second distinct update cannot reuse the consumed generation even if the first mutated then transport failed. |
| Pending view | Persist operation token and intended generation before provider I/O. Keep no ORM transaction open across navigation transport. Reuse the generation for a truly unchanged, valid confirmed view; never send solely to renew controls. |
| Confirmed / no change | Compare-and-set pending token and owner; publish only a positive provider message ID or the existing ID for a proven no-op with matching controls. Mark previously issued controls inert before best-effort retirement of a distinct old message. Do not strip a new view that reused its old message ID. |
| Definite edit inability | Reserve at most one replacement attempt for the transition. Keep the old generation inert. Publish only on confirmed replacement; a known send failure offers recovery on the next intentional eligible interaction. |
| Unknown / lost owner | Invalidate uncertain controls and do not resend or re-edit that target automatically. Preserve receipts and domain commits. Repeated obsolete taps cannot replay the attempt. An intentional new safe action such as Home may establish a fresh view without reusing the uncertain ID. |
| Obsolete control | Reuse a confirmed authorized current view if it supplies a visible route; otherwise reserve a single current-policy recovery per usable recovery/obsolete incident. Same-message obsolete controls cannot remove current markup. Clear old markup only on a distinct safely identified navigation message. |

Use the existing global receiver lease, a bounded local per-chat queue and a namespaced
PostgreSQL session advisory lock keyed by bot/user (different from receiver lease key).
Use one bound ORM connection for guarded ordinary commerce; do not hold two pool
connections per chat. Bound queue, lock and provider calls and release in `finally`;
invalidate the checked-out connection if unlock/cleanup cannot be confirmed. Verify
lease ownership before protected routing and before publishing; a lost owner stops
publishing and leaves any uncertain reservation inert. A later owner must acquire the
same lock, so existing handler commits cannot overlap new actions for that conversation.
An update the system cannot safely process is not replayed as a business operation.
Direct test dispatch uses equivalent in-process serialization for SQLite; actual lock,
connection lifecycle, independent chats, and restart/lease handoff require PostgreSQL
evidence. Native precheckout/settlement and published Runtime handlers retain their
own isolation and receipts.
