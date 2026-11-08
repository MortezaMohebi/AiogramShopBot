# Official login reference inspection — 2026-11-06

| Product | Official URL inspected | Observed emphasis |
|---|---|---|
| Vercel | https://vercel.com/login | Clear login title, email, supported providers and optional authentication methods. |
| Linear | https://linear.app/login | Short login title and real email/provider/passkey choices; no architecture explanation. |
| Stripe | https://dashboard.stripe.com/login | Email/password, recovery, remember choice and actual provider alternatives. |
| GitHub | https://github.com/login | Username/email, password, recovery and passkey; concise account navigation. |
| Shopify | https://accounts.shopify.com/store-login | Brand, email continuation and actual providers; CAPTCHA is shown when required. No challenge was completed. |
| Cloudflare | https://dash.cloudflare.com/login | Email/password, visibility control, real providers and remembered login method. |
| Notion | https://www.notion.so/login | Email continuation, supported providers and account navigation. It also has a product tagline; this product's login does not need one. |
| Supabase | https://supabase.com/dashboard/sign-in | Email/password, actual providers and recovery/account links. |

Vercel/GitHub/Supabase content was available from public page retrieval. Linear/Stripe/Shopify/Cloudflare/Notion were additionally inspected in the browser because their retrieved responses were loading/JavaScript shells. No reference accounts were signed into.

Applied principle: show the task and authentication options this application really supports. The native dashboard supports username/password, optional MFA and configured CAPTCHA; it has no public self-service recovery or SSO flow to advertise. Its login keeps the existing MFA field and challenge enforcement, removes slogans and security claims, and moves the request reference into support details.
