# Local Windows/WSL test deployment

Use the `feat/first-run-owner-email-20261107` branch with Docker Desktop's WSL
integration and one remotely managed Cloudflare Tunnel. This keeps PostgreSQL,
Redis and FastAPI on the private Docker network. The dashboard is published
only to the Windows/WSL loopback address. No router port forwarding is needed.

## Cloudflare routes

Create a named tunnel in Cloudflare **Networking > Tunnels**. The domain must
already be in Cloudflare DNS. Add two **Published application** routes to the
same tunnel (the service URL is reachable by the `cloudflared` container on the
Compose network):

| Public hostname | Service URL | Purpose |
| --- | --- | --- |
| `admin.example.com` | `http://next-admin:3000` | Dashboard and mobile PWA |
| `hooks.example.com` | `http://webhook-gateway:8080` | Telegram/Bale webhook POST only |

For the dashboard hostname, configure a Cloudflare Access self-hosted
application with an **Allow** policy restricted to your own email before
starting the tunnel. Do not put an Access login challenge on the webhook
hostname: Telegram/Bale cannot complete browser login. The gateway rejects
all non-webhook routes. Access on the dashboard adds another login on the phone;
the application still requires its own administrator account and MFA.

## WSL setup

Open an Ubuntu WSL shell with Docker Desktop running and WSL integration
enabled. Work on the Linux filesystem (for example, `~/src`), not `/mnt/c`.

```bash
git clone --branch feat/first-run-owner-email-20261107 \
  https://github.com/MortezaMohebi/AiogramShopBot.git ~/src/AiogramShopBot
cd ~/src/AiogramShopBot
cp .env.template .env
cp .env.next-admin.example .env.next-admin
mkdir -p .secrets
chmod 700 .secrets
```

Fill the two local env files with distinct random secrets. `POSTGRES_PASSWORD`
and `REDIS_PASSWORD` are required. Set the *same* `NEXT_ADMIN_BRIDGE_SECRET`
in both files. Generate each plain secret with `openssl rand -hex 32`; generate
the Fernet `SHOP_SECURITY_ENCRYPTION_KEY` with
`openssl rand -base64 32 | tr '+/' '-_'`. Keep all generated values off Git and
out of chat.

Set these exact origins, with no trailing slash:

```dotenv
# .env
MULTIBOT_WEBHOOK_BASE_URL=https://hooks.example.com
SHOP_ADMIN_SECURE_COOKIES=true
NEXT_ADMIN_BRIDGE_ENABLED=true
NEXT_ADMIN_BRIDGE_SECRET=<same-secret-as-next-admin>
SHOP_SECURITY_ENCRYPTION_KEY=<fernet-key>

# .env.next-admin
NEXT_ADMIN_PUBLIC_ORIGIN=https://admin.example.com
NEXT_ADMIN_BRIDGE_SECRET=<same-secret-as-backend>
NEXT_ADMIN_SESSION_SECRET=<different-random-secret>
```

Copy only the tunnel token (the `eyJ...` value from Cloudflare's installation
command) into `.secrets/cloudflare-tunnel-token`, with **no** command prefix.
The token file is mounted as a Docker secret; the token is not a Compose
environment value, a URL parameter, or a tracked file.

For a **wholly empty** local PostgreSQL volume, initialize once:

```bash
docker compose -f docker-compose.yml -f compose.local-tunnel.yml config --quiet
docker compose -f docker-compose.yml -f compose.local-tunnel.yml build bot next-admin
docker compose -f docker-compose.yml -f compose.local-tunnel.yml up -d --wait postgres redis
docker compose -f docker-compose.yml -f compose.local-tunnel.yml run --rm --no-deps bot \
  python -m scripts.initialize_registry_database
docker compose -f docker-compose.yml -f compose.local-tunnel.yml up -d --wait
```

**Existing data:** do not run the initializer. Back up `postgres_data` and
follow the reviewed Alembic migration path in `scripts/deploy.sh info`. The
Compose overlay and `docker compose down` do not delete the named or bind
mounted data; never use `down -v` to update this installation.

Visit `https://admin.example.com/setup` through Access and create the first
administrator. Once created, setup closes and login becomes the entry point.
Open the same hostname on Android Chrome or iPhone Safari, log in through
Access and the dashboard, then install it from the browser. A previously
installed copy may need removal and installation again after changing the
PWA name/icon in **Settings**.

## Verify before enabling bots

```bash
docker compose -f docker-compose.yml -f compose.local-tunnel.yml ps
curl -fsS https://admin.example.com/manifest.webmanifest
curl -fsS -o /dev/null https://admin.example.com/pwa/icon/512
curl -fsS https://hooks.example.com/_edge/health
```

The admin checks require the allowed Access login in a browser; a plain
unauthenticated `curl` may receive an Access redirect. Verify that
`https://hooks.example.com/login` returns 404 and that the webhook domain is
**not** a general API route. Only after these checks, register the Telegram and
Bale bots in Dashboard > Bots and activate their receivers. Telegram requires
a public HTTPS webhook on a supported TLS port; the Cloudflare hostname uses
443 without forwarding the local 8080 port.

To stop the test without deleting data:

```bash
docker compose -f docker-compose.yml -f compose.local-tunnel.yml down
```
