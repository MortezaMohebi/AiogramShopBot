# Requirement-to-test traceability

FR/SC/R IDs reference the approved [specification](spec.md). File names in test columns
refer to `tests/` unless otherwise noted. Each listed check is planned, not an executed
result. P0/P1/P2 are delivery and verification gates; cross-cutting cases also run after P2.

| Requirement | Story / implementation surface | Automated evidence to add or extend | Paired acceptance / metric |
| --- | --- | --- | --- |
| FR-001 | US1; dispatch generation, authorization, gallery reads | `test_beta_conversation_ux.py`, `test_multibot_catalog_acl_offline.py`; assert state unchanged on stale/wrong-scope input | R-01, R-02 / SC-001, SC-008 |
| FR-002 | US1; authorized recovery in dispatch | `test_beta_conversation_ux.py`; active/missing/expired/current-but-unauthorized view | R-01, R-02 / SC-001 |
| FR-003 | US1; reservation and obsolete markup retirement | Same suite + PostgreSQL; distinct update IDs, one recovery, same-ID edit, restart | R-01 / SC-001 |
| FR-004 | US2; checkout review and terms pages | `test_beta_terms_navigation.py`; all pages and one-action return, standalone command | R-03, R-04 / SC-002 |
| FR-005 | US2; origin-bearing read-only review | Same + `test_beta_checkout_policy.py`; full text, invalid page and changed/missing quote/terms, zero writes | R-03, R-04 / SC-002, SC-008 |
| FR-006 | US2; existing order transaction, policy/quote revalidation | Same + `test_shared_payment_settlement.py`; explicit consent only, concurrent policy change, stale/repeated confirmation | R-03, R-04, R-11 / SC-002, SC-008 |
| FR-007 | US2; checkout copy, split and payment gates | `test_beta_checkout_copy.py`, `test_beta_mixed_split.py`, `test_beta_bale_mixed_cart.py`, `test_beta_bale_mixed_payment_guard.py` | R-03, R-04, R-11 / SC-002, SC-008 |
| FR-008 | US3; effective policy and native keyboard rows | `test_beta_customer_menu.py` and both transport suites; ordered labels, Store/Bot/capabilities | R-05 / SC-003 |
| FR-009 | US3; live action checks, native contact restore | `test_beta_customer_menu.py`, `test_beta_customer_account.py`, transport suites; first install, drift, cancel/exit | R-05 / SC-003 |
| FR-010 | US4; scoped search Back | `test_beta_customer_search.py`, `test_beta_cart_form_navigation.py`; later page, active ACL and clamp | R-06 / SC-004 |
| FR-011 | US4; search expiry and pending-input exit | Same tests; preserve cart, parked draft, original TTL and step | R-06 / SC-004 |
| FR-012 | US4; plain name default/optional filters | `test_beta_customer_search.py`; unfiltered entry, filter discovery, empty state | R-06 / SC-004 |
| FR-013 | US5; shared compact list renderer | `test_shop_channel_catalog.py`, `test_beta_customer_search.py`; nine eligible incl. no category/cover | R-07 / SC-005 |
| FR-014 | US5; edit/no-change/replacement policy | Both transport suites and paired view fixture; message and live-control counts | R-07 / SC-005 |
| FR-015 | US5; unknown outcomes, no replay | Both transports, `test_beta_digital_delivery.py`, `test_shared_payment_settlement.py`; timeout, rate limits, unexpected errors | R-07, R-08, R-11 / SC-005, SC-008 |
| FR-016 | US5; durable messages and deliberate media | `test_shop_channel_catalog.py`, `test_beta_conversation_ux.py`, `test_beta_paused_customer_support.py`, `test_beta_dispatch_paid_notification.py` | R-07, R-08, R-11 / SC-005, SC-008 |
| FR-017 | US6; Account groups and address wizard | `test_beta_customer_account.py`, `test_beta_cart_form_navigation.py`; all allowed actions and same resume step | R-09 / SC-006 |
| FR-018 | US7; Persian labels and copy | `test_beta_checkout_copy.py` and paired transcript checks; no raw provider errors, retain material information | R-10 / SC-007 |
| FR-019 | US8; readable control text and RTL | Assert text labels and review real clients with available assistive controls and narrow viewport | R-10 / SC-007 |
| FR-020 | US3/US4/US6–US8; actionable errors, no stale input | `test_beta_cart_form_navigation.py` + paired menu/search/account transcripts | R-05, R-06, R-09, R-10 / SC-003, SC-004, SC-006, SC-007 |
| FR-021 | All stories; commerce and scope invariants | ACL, account, terms, finance, receipt/refund/delivery and Runtime receiver suites + PostgreSQL | R-01, R-02, R-04–06, R-08–09, R-11 / SC-008 |
| FR-022 | All stories; equivalent intent, supported native differences | Paired native transport transcripts; native client acceptance where provider behavior matters | R-01, R-04–07, R-09–11 / SC-001–008 |

## Eleven paired regression cases

| Case | Shared assertions | Telegram and Bale variations |
| --- | --- | --- |
| R-01 | Old Add/Confirm/Pay twice, deleted/missing current view, expired and same-ID generation; zero business effects and at most one usable recovery. Include ack failure, concurrent distinct IDs and uncertain first attempt. | Telegram answer callback; Bale supported ack and legacy visible path. |
| R-02 | Permitted old gallery read still works; revoked product or foreign Store/Bot/customer discloses nothing and never mutates. | Telegram photo; Bale text fallback. |
| R-03 | Long terms one tap, last page, return and cancel; zero consent/order/charge until explicit valid acceptance in manual and instant modes. | Telegram digital currency and existing native flow; Bale eligible payment method. |
| R-04 | During terms, alter text/policy or quote, address/price/eligibility; bad page, missing terms, disabled checkout and old confirm. Fresh scoped review or allowed recovery; zero invalid order or charge. | Telegram two separately presented payment parts; Bale separate-order guidance and no charge. |
| R-05 | Store default, bot override, cart disabled, policy drift, older shortcut, complete/cancel/leave contact. Assert exact labels/order, verified contact provenance and restore once. | Telegram persistent keyboard behavior; Bale supported keyboard installation and explicit restoration. |
| R-06 | Plain query and optional filters, page two, product Back, shrinking or no results, expiry, Home/Cancel and unrelated draft/cart unchanged. | Telegram Back after an edited preview; Bale Back after replacement preview. |
| R-07 | Nine eligible products incl. uncategorized/no cover; compact pages, paging, no-op, definite edit failure, rate limit and ambiguous result. Count active controls and messages. | Telegram compatible preview edit/one replacement; Bale text edit/replacement photo path. |
| R-08 | Explicit gallery, preview and requested file; navigation never edits/deletes durable content. Reopen permitted media and keep receipts/support history; unknown delivery not replayed. | Telegram photo edit and file; Bale replacement and file. |
| R-09 | At most four Account choices, allowed action within two taps, resume draft at same step, invalid input followed by navigation. | Test native contact exit and keyboard recovery on each platform. |
| R-10 | Review Persian stale recovery, search, terms/checkout, Account and validation on narrow screens; verify all labels, mixed-script references/currency, visible next steps, accessible navigation. | Use available native assistive controls separately for each supported client; document unavailable modes. |
| R-11 | Repeat decision, authorized refund, delivery and settlement through fake providers and PostgreSQL. One authorized outcome, same side effects and intact durable receipts, also on unknown transport. | Telegram native invoice/settlement; Bale eligible settlement and existing mixed-cart guards. |

Use [quickstart.md](quickstart.md) to collect evidence. Expected outcomes and counts are
defined by the spec; no latency or live behavior measurement is inferred.
