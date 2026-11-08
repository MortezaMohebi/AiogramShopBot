# No-domain QA from Debian WSL

This uses the latest test branch, Docker Desktop's **Debian WSL 2 integration**
and two temporary Cloudflare Quick Tunnels. No purchased domain, router port
forwarding, Cloudflare tunnel token or local `cloudflared` installation is
required. One URL is email protected for the administrator/PWA; the other URL
is public for Telegram/Bale, but its Nginx gateway only forwards authenticated
webhook paths and denies other backend routes.

**Important:** Every new Quick Tunnel gets a different hostname. An installed
PWA is tied to the old origin. Reconfigure the two origins, recreate the
affected services and re-register webhooks after a tunnel restart. This is for
short QA sessions, not a durable installation.

## Prepare on Debian

Run Docker Desktop on Windows and enable **Settings > Resources > WSL
Integration > Debian**. In Debian, `docker compose version` must succeed.
Clone the branch on the Debian Linux filesystem:

```bash
git clone --branch feat/first-run-owner-email-20261107 \
  https://github.com/MortezaMohebi/AiogramShopBot.git ~/src/AiogramShopBot
cd ~/src/AiogramShopBot
cp .env.template .env
cp .env.next-admin.example .env.next-admin
```

In `.env`, set `POSTGRES_PASSWORD`, `REDIS_PASSWORD`,
`SHOP_SECURITY_ENCRYPTION_KEY`, `NEXT_ADMIN_BRIDGE_SECRET` and
`TEST_ADMIN_EMAIL` to **your** email address. Set
`NEXT_ADMIN_BRIDGE_ENABLED=true`. Put the **same** bridge secret in
`.env.next-admin`, plus a different `NEXT_ADMIN_SESSION_SECRET`. For each
ordinary secret use `openssl rand -hex 32`; for the Fernet encryption key use
`openssl rand -base64 32 | tr '+/' '-_'`. Keep real values out of Git and chat.

For a completely empty local database only:

```bash
docker compose -f docker-compose.yml -f compose.quick-tunnel.yml config --quiet
docker compose -f docker-compose.yml -f compose.quick-tunnel.yml build bot next-admin
docker compose -f docker-compose.yml -f compose.quick-tunnel.yml up -d --wait postgres redis
docker compose -f docker-compose.yml -f compose.quick-tunnel.yml run --rm --no-deps bot \
  python -m scripts.initialize_registry_database
```

**Existing database:** do not initialize or use `down -v`; back up
`postgres_data` and follow `scripts/deploy.sh info` for migration.

## Start two tunnels and set exact origins

The first tunnel may show 502 until the application starts. Run these in
Debian, keeping the same Compose file pair throughout:

```bash
docker compose -f docker-compose.yml -f compose.quick-tunnel.yml up -d --no-deps cloudflared-webhooks cloudflared-admin
docker compose -f docker-compose.yml -f compose.quick-tunnel.yml logs --no-color --tail=80 cloudflared-webhooks cloudflared-admin
```

Copy each generated `https://...trycloudflare.com` address from the log of
its **own** service. Set the exact values without a trailing slash:

```dotenv
# .env
MULTIBOT_WEBHOOK_BASE_URL=https://<webhooks-url>.trycloudflare.com

# .env.next-admin
NEXT_ADMIN_PUBLIC_ORIGIN=https://<admin-url>.trycloudflare.com
```

Start/recreate the application after saving both env files:

```bash
docker compose -f docker-compose.yml -f compose.quick-tunnel.yml up -d --wait --force-recreate bot next-admin webhook-gateway
docker compose -f docker-compose.yml -f compose.quick-tunnel.yml ps
```

Visit the **admin** URL on the phone. The email-protected tunnel sends a PIN
to `TEST_ADMIN_EMAIL`; complete it, then use `/setup` for the first owner or
`/login` on an initialized installation. The webhook tunnel has no email
challenge: bots cannot complete one. Do not share either tunnel URL.

Check that `https://<admin-url>.trycloudflare.com/manifest.webmanifest`
returns the install manifest, that the admin `/pwa/icon/512` is a PNG and
that `https://<webhooks-url>.trycloudflare.com/login` returns 404. After
login and MFA enrollment, register/activate your test bots from the dashboard.

Quick Tunnels do not support SSE and have no uptime guarantee. For repeated
mobile PWA and webhook tests, use a stable hostname instead: a domain-backed
Cloudflare Named Tunnel, a Tailscale Funnel `*.ts.net` name, or an assigned
ngrok dev domain. These require a separate setup and possibly another account.
