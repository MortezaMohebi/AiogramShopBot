<h1 align="center">AiogramShopBot</h1>

<p align="center">
  <strong>🛍️ Production-style Telegram shop bot with crypto payments, admin flows, FastAPI webhooks, and multibot support.</strong>
</p>

<p align="center">
  <a href="https://t.me/demo_aiogramshopbot">
    <img src="https://img.shields.io/badge/Live_Demo_Bot-blue?logo=probot&logoColor=white" alt="Live bot"/>
  </a>
  <a href="https://t.me/ilyarolf_dev">
    <img src="https://img.shields.io/badge/Contact_me-blue?logo=telegram&logoColor=white" alt="Business offer"/>
  </a>
</p>

[![Python](https://img.shields.io/badge/Python_3.12-3776AB?logo=python&logoColor=%23fff)](https://www.python.org/downloads/release/python-3127/)
[![Dockerhub](https://img.shields.io/badge/Docker_Hub-2496ED?logo=docker&logoColor=fff)](https://hub.docker.com/r/ilyarolf/aiogram-shop-bot)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?logo=postgresql&logoColor=white)](https://www.sqlite.org/)
[![Bitcoin](https://img.shields.io/badge/Bitcoin-FF9900?logo=bitcoin&logoColor=white)](https://github.com/bitcoin/bitcoin)
[![Dogecoin](https://img.shields.io/badge/Dogecoin-C2A633?logo=dogecoin&logoColor=white)](https://dogecoin.com/)
[![Litecoin](https://img.shields.io/badge/Litecoin-A6A9AA?logo=litecoin&logoColor=white)](https://github.com/litecoin-project/litecoin)
[![Solana](https://img.shields.io/badge/Solana-9945FF?logo=solana&logoColor=fff)](https://github.com/solana-labs/solana)
[![Ethereum](https://img.shields.io/badge/Ethereum-3C3C3D?logo=ethereum&logoColor=white)](https://github.com/ethereum)
[![BinanceCoin](https://img.shields.io/badge/Binance-FCD535?logo=binance&logoColor=000)](https://github.com/binance)
[![Tether](https://img.shields.io/badge/Tether-168363?&logo=tether&logoColor=white)](https://tether.to/)
[![USD Coin](https://img.shields.io/badge/USD%20Coin-2775CA?&logo=usd-coin&logoColor=white)](https://www.usdc.com/)

**AiogramShopBot** is an open source Telegram shop bot built with **Aiogram 3**, **FastAPI**, **SQLAlchemy async**, **PostgreSQL**, **Redis**, **Docker Compose**, and **SQLAdmin**. It helps you sell **digital goods** and **physical goods** inside Telegram with built-in **cryptocurrency payments**, **shopping cart**, **purchase history**, **admin tools**, **shipping**, **reviews**, **coupons**, **analytics**, **referrals**, and **multi-language support**.

This repository is designed for developers and product teams who need a production-style Telegram ecommerce bot with a web admin panel, payment processing, localization, and scalable deployment.

## ✨ Why This Project

- Sell digital and physical products directly in Telegram.
- Accept crypto top-ups with Bitcoin, Dogecoin, Litecoin, Solana, Ethereum, Binance Coin, USDT, and USDC networks.
- Manage inventory, users, coupons, shipping, reviews, media, and purchases from Telegram admin flows.
- Use PostgreSQL, Redis, webhook mode, and Docker-based deployment for production setups.
- Extend the project with FastAPI routes, SQLAdmin, repositories, services, and Aiogram handlers.

## 🚀 Core Features

- Telegram storefront with categories, subcategories, cart, checkout, and purchase history.
- Admin menu for announcements, inventory, user management, analytics, wallet operations, media, coupons, shipping, buys, and reviews.
- Crypto payment integration with KryptoExpress.
- Referral system with limits and anti-abuse rules.
- Localization through JSON translation files.
- SQLAdmin web panel for database objects.
- Docker Compose setup for local and production-like environments.
- Multibot mode with one main bot and managed child bots.

## 🧰 Tech Stack

- Python 3.12
- Aiogram 3
- FastAPI
- SQLAlchemy async
- PostgreSQL
- Redis
- Alembic
- SQLAdmin
- Docker Compose

## ⚡ Quick Start

### 🖥️ Interactive deployment

Run the installer script on your VPS:

```bash
sudo sh -c "$(curl -fsSL https://raw.githubusercontent.com/ilyarolf/AiogramShopBot/refs/heads/master/scripts/deploy.sh)"
```

### 💻 Local development

```bash
git clone https://github.com/ilyarolf/AiogramShopBot.git
cd AiogramShopBot
pip install -r requirements.txt
python run.py
```

You will also need PostgreSQL, Redis, environment variables, and webhook/reverse proxy configuration.

Full setup guide:
- [Deployment and environment variables](docs.md#deployment-and-configuration)
- [Local run example](docs.md#local-development-example)

## 🎬 Product Walkthrough

### 💳 User balance top-up

![Top Up Balance Demo](https://i.imgur.com/j2l7fHc.gif)

### 🛒 Product purchase flow

![Purchase Flow Demo](https://i.imgur.com/yEUw32h.gif)

### 🧾 Purchase history

![Purchase History Demo](https://i.imgur.com/t5sA38N.gif)

### 👛 Admin wallet withdrawal

![Wallet Demo](https://i.imgur.com/gjkRFVb.gif)

More Telegram bot GIF demos, admin flow examples, and screenshots are available in [docs.md](docs.md#demo-gallery).

## 📚 Documentation

- [Full documentation](docs.md)
- [Deployment and configuration](docs.md#deployment-and-configuration)
- [User manual](docs.md#user-manual)
- [Admin manual](docs.md#admin-manual)
- [Referral system](docs.md#referral-system)
- [Cryptocurrency forwarding](docs.md#cryptocurrency-forwarding)
- [SQLAdmin panel](docs.md#sqladmin-web-admin-panel)
- [Multibot mode](docs.md#multibot-experimental)

## 🌍 Community

- [Contributing guide](CONTRIBUTING.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Security policy](SECURITY.md)
- [Support](SUPPORT.md)

## 🎯 Use Cases

- Telegram shop bot for digital products
- Telegram bot for physical goods with shipping
- Crypto-funded Telegram marketplace
- Telegram multibot commerce setup with one manager bot
- Aiogram ecommerce starter project
- FastAPI + Aiogram + SQLAlchemy production template
- Telegram admin panel and back office automation

## 🤝 Commercial Contact

- Demo bot: [@demo_aiogramshopbot](https://t.me/demo_aiogramshopbot)
- Commercial requests: [@ilyarolf_dev](https://t.me/ilyarolf_dev)

## 💖 Donate

- BTC: `bc1q2kv89q8yvf068xxw3x65gzfag98l9wnrda3x56`
- DOGE: `D8BFXqDM7MHf3A4j3kC8wWEN8DqRLVQjax`
- LTC: `ltc1q0tuvm5vqn9le5zmhvhtp7z9p2eu6yvv24ey686`
- SOL: `Avm7VAqPrwpHteXKfDTRFjpj6swEzjmj3a2KQvVDvugK`
- ETH: `0xB49D720DE2630fA4C813d5B4c025706E25cF74fe`
- TON: `UQD0QetwXoYTsmbZWVbE_z_JUFh54RVVRUxCbCHQkLsl3Hfn`
- USDT ERC20: `0xB49D720DE2630fA4C813d5B4c025706E25cF74fe`
- USDT BEP20: `0xB49D720DE2630fA4C813d5B4c025706E25cF74fe`

## ⭐ Star History

<a href="https://www.star-history.com/?type=date&repos=ilyarolf%2FAiogramShopBot">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=ilyarolf/AiogramShopBot&type=date&theme=dark&legend=top-left&sealed_token=pbKbpm2_oq5Q5jYCMb2wjqRDjC7XPo2NlHUvUa30rQTnIBrQP3MFFWNOvQ5rdbX8R5iODu7-_eLVER1wLvk940VDyqYd057DwiVmHC3g1oBvdZHnoi3rsElANV3UXSYgpsE8QHXiRvzuZb_k5yet8L-qXF53SiTdfv5zI1lgfKnMY-K-fb5Uw24dKPXO" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=ilyarolf/AiogramShopBot&type=date&legend=top-left&sealed_token=pbKbpm2_oq5Q5jYCMb2wjqRDjC7XPo2NlHUvUa30rQTnIBrQP3MFFWNOvQ5rdbX8R5iODu7-_eLVER1wLvk940VDyqYd057DwiVmHC3g1oBvdZHnoi3rsElANV3UXSYgpsE8QHXiRvzuZb_k5yet8L-qXF53SiTdfv5zI1lgfKnMY-K-fb5Uw24dKPXO" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=ilyarolf/AiogramShopBot&type=date&legend=top-left&sealed_token=pbKbpm2_oq5Q5jYCMb2wjqRDjC7XPo2NlHUvUa30rQTnIBrQP3MFFWNOvQ5rdbX8R5iODu7-_eLVER1wLvk940VDyqYd057DwiVmHC3g1oBvdZHnoi3rsElANV3UXSYgpsE8QHXiRvzuZb_k5yet8L-qXF53SiTdfv5zI1lgfKnMY-K-fb5Uw24dKPXO" />
 </picture>
</a>



## Optional Cloudflare Worker transport (Telegram)

This fork supports `TELEGRAM_API_MODE=cloudflare_worker` with a configurable
`TELEGRAM_WORKER_URL` and a separate secret stored in the Worker and VPS
environments. Unlike an open URL-rewriting proxy, the Worker authenticates
requests and forwards only Telegram Bot API and file-download paths.

The receiving side can use `TELEGRAM_UPDATE_MODE=webhook` (original behaviour)
or `TELEGRAM_UPDATE_MODE=polling` to get updates through the Worker without
a public Telegram-facing callback endpoint. **Bale remains independent**.

- [Cloudflare Worker deployment and security guide (Persian)](docs/CLOUDFLARE_WORKER.fa.md)
- [Telegram/Bale feature parity and API differences (Persian)](docs/CHANNEL_PARITY.fa.md)

These features are on the **Draft PR branch**, not deployed or live-tested.

## Persian shop dashboard, native Bale wallet and IRR

The Draft PR branch also contains an independently editable product/catalogue
model, private media uploader, product testimonials, Persian/RTL SQLAdmin
templates, and native Bale wallet invoice/verification flow.

- Canonical catalogue and invoice prices are **integer Iranian rials**.
- Optional `SHOP_DISPLAY_UNIT=TOMAN` changes text display only.
- Real Bale wallet checkout is **disabled by default** via
  `BALE_WALLET_CHECKOUT_ENABLED=false` until live payment/shipping tests.
- The legacy Telegram crypto wallet is not used for Bale transactions.
- Old Telegram cart/coupon/shipping features have **not** yet been migrated into
  the cross-platform services; see the parity matrix for open work.

[Phase 2 implementation and safety report](docs/PHASE2_STATUS.fa.md)

## Shared checkout foundation (Telegram + Bale)

The draft fork now includes common multi-item baskets, product quantities,
merchant-defined coupons, address capture, shipping methods, immutable order
line snapshots, customer order history/cancellation, and a guarded Persian
order-review dashboard.

**No money is collected by this shared checkout path.** New requests use
`pending_review` / `approved_unpaid` and must not be interpreted as paid
orders. The previous single-item Bale Wallet implementation stays disabled
until multi-item settlement and provider verification are implemented and
tested. Telegram legacy purchase history remains separate.

[Phase 3 checkout status and safety contract (Persian)](docs/PHASE3_SHARED_CHECKOUT.fa.md)

## Shared payment intents (draft, opt-in only)

The Telegram/Bale shared order flow now includes immutable payment intents,
verified pre-checkout, success-receipt settlement, atomic product/coupon
allocation, Telegram Stars pricing (XTR), native Bale wallet invoices in IRR,
and an auditable refund process.

All payment and Stars refund flags default to **false**. The existing
`pending_review` cart request remains unpaid until an operator reviews it.
Physical Telegram invoices require a verified provider token and an
explicitly configured IRR minor-unit factor. Real API, migration and
concurrency tests are deferred to final integration.

[Phase 4 payment safety and refund contract (Persian)](docs/PHASE4_PAYMENTS.fa.md)

## Shared non-crypto capabilities (draft Phase 5)

New cross-platform code includes merchant IRR store credit with an immutable
ledger; approved, confirmed shop-credit purchases/refunds; opt-in referral
rewards on verified fiat payments; consent-based marketing campaigns; and
read-only Persian admin analytics that keep Telegram Stars, IRR and issued
credit separate.

The old shared admin login is replaced with individually provisioned staff
accounts and deny-by-default roles. No default password or production account
is installed automatically.

**All financial adjustments and payment providers remain disabled by
default. No live Bot API or database tests have been run.**

[Phase 5 scope, operational controls and deferred verification (Persian)](docs/PHASE5_ENGAGEMENT.fa.md)

## Media safety and two-platform Broadcast (draft Phase 6)

The shared dashboard accepts media up to the official **Bale multipart** limits:
10 MB per photo and 50 MB per video/audio/document. File IDs are stored
separately for each Telegram/Bale bot; original media stays in private storage.

Consent-only marketing campaigns now include ordered image/video/audio/PDF
attachments and a durable recipient outbox. Broadcast runs in bounded,
administrator-approved batches. Bale supports optional `standard` or paid
`business` broadcast mode; paid mode is disabled by default and requires
pre-uploaded file IDs belonging to the same Bale bot.

Webhook update IDs are recorded per platform and bot before handling. Replayed
updates are not executed again; uncertain outcomes require manual review.

**The new code is not deployed or live-tested.** Do not enable paid Business
broadcast or merge this draft before final Test → Debug → Retest.

[Phase 6 Bale media limits, broadcast and deduplication (Persian)](docs/PHASE6_MEDIA_BROADCAST.fa.md)

## Fully automatic opt-in Broadcast worker (draft Phase 7)

After an administrator approves recipients and starts a campaign **once**,
a separate shared worker drains the entire PostgreSQL outbox. It honors
per-bot and per-user pacing, opt-out and block state changes, supports
ordered media, and stores durable progress, manual-reconciliation receipts
and audit entries. Managers can pause/resume/cancel and view progress in
Persian SQLAdmin.

Bale Business API remains opt-in and requires a confirmed *exact*
per-campaign upper bound on billable API messages. Uncertain external
delivery is never blindly retried after a restart. Docker Compose includes
an optional `broadcast-worker` service rather than one container per user.

All worker/dispatch flags are **OFF by default**; no live delivery,
PostgreSQL migration or provider tests have occurred.

[Phase 7 automatic Broadcast and operational safety guide (Persian)](docs/PHASE7_DURABLE_BROADCAST.fa.md)

## 📄 License

[MIT License](LICENSE)
