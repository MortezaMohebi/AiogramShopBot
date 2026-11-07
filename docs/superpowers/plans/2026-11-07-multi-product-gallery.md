# Multi-product chat gallery Implementation Plan

> **For agentic workers:** Use subagent-driven development for provider transports and execute the shared catalog task in the current session.

**Goal:** Show four independently selectable photo product cards per catalog page in Telegram and Bale.

**Architecture:** Add `BotReply.cards` containing bounded child replies. The shared catalog selects four products under the existing entitlement predicate and builds one child card per product. Each transport sends the children as photo/text messages with their own inline controls, then returns the footer message ID for navigation state.

**Tech Stack:** Python, SQLAlchemy, aiogram, Bale Bot API, pytest.

**Spec:** `docs/superpowers/specs/2026-11-07-multi-product-gallery-design.md`

## Global Constraints

- Preserve existing customer-requested media and old chat messages.
- Keep Telegram and Bale behavior aligned using the same four-product catalog query.
- Enforce bot/store/product visibility and stock policy on each card and its callback.

## Review Focus

- A denied/unpublished product within the page never appears; test both providers.
- Products without a published cover yield usable text cards; test both providers.
- A final short page and out-of-range page are bounded; test both providers.
- Gallery page controls return to the same category after detail; test both providers.
- Provider send/edit failures never silently mark a page as delivered; test transport failure paths.

---

### Task 1: Shared catalog and contract

**Files:** `channels/contracts.py`, `services/shop_channel_catalog.py`, `tests/test_shop_channel_catalog.py`

**Interfaces:** `BotReply.cards: tuple[BotReply, ...] = ()`; each child uses existing `text`, `preview`, `rows`.

- [x] Add failing tests for four cards, pagination, access policy, missing cover, category return.
- [x] Run focused tests to observe the regression.
- [x] Select four permitted rows, build child previews with dedicated detail buttons and a footer with page controls.
- [x] Run focused tests and fix regressions.

### Task 2: Telegram transport

**Files:** `channels/telegram.py`, `tests/test_telegram_channel_transport.py`

- [x] Test four cards with photo/text fallback and page footer, including old inline invalidation.
- [x] Implement child delivery using existing preview and send logic; return footer ID.
- [x] Run Telegram focused tests.

### Task 3: Bale transport

**Files:** `channels/bale.py`, Bale transport tests.

- [x] Test four cards with photo/text fallback and page footer, including old inline invalidation.
- [x] Implement child delivery using existing preview and send logic; return footer ID.
- [x] Run Bale focused tests.

### Task 4: Integration verification

**Files:** any affected focused tests.

- [x] Run catalog, both transport and dispatcher suites.
- [x] Verify compile/build and inspect final diff for unrelated changes.
- [x] Commit only this feature's files to the existing feature branch.
