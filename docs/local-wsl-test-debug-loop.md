# Repeatable test, debug and retest from Debian WSL

This is the no-domain workflow for the `feat/first-run-owner-email-20261107`
branch. It uses two different outbound-only connections:

1. **Tailscale Funnel** on Windows publishes one stable `https://…ts.net`
   origin on port 443. The loopback-only Docker gateway sends restricted
   webhook POSTs to FastAPI and all other paths to the Next.js dashboard.
   Telegram and Bale use the same origin plus their opaque webhook paths.
2. **VS Code Remote Tunnel** runs in Debian. Its browser editor gives an
   authorized GitHub account access to the project, terminal and Docker logs.
   The development terminal is never exposed through Funnel.

The ChatGPT cloud workspace does **not** automatically become the PC's shell.
After both URLs exist, first verify that the ChatGPT browser can open the
dashboard and connect to the authenticated VS Code tunnel. Only then can an
agent claim to run a complete remote test/debug/retest loop from this chat.
Do not send bot tokens, setup codes, passwords or tunnel credentials in chat.

## Windows: stable public HTTPS

Install Tailscale for Windows from its official site, sign in and enable
MagicDNS, HTTPS and Funnel for the tailnet. In an **Administrator PowerShell**:

```powershell
tailscale funnel 8081
```

Approve the first Funnel enablement in the browser if prompted. Copy the
displayed `https://<machine>.<tailnet>.ts.net` origin; do not append a port or
slash. Docker Desktop must be running with WSL 2 integration enabled for
**Debian**. Its Windows loopback listener forwards to the container's
`127.0.0.1:8081` mapping. If Windows cannot reach
`http://127.0.0.1:8081/_edge/health`, check Docker Desktop integration before
testing the public URL.

Funnel is public. The dashboard still requires its own login and MFA. The
initial `/setup` requires a time-limited code obtained from the local backend
terminal. Finish first-owner setup promptly before registering bots.

## Debian: build and run the application

Keep the checkout in Debian's Linux filesystem, not `/mnt/c`:

```bash
git clone --branch feat/first-run-owner-email-20261107 \
  https://github.com/MortezaMohebi/AiogramShopBot.git ~/src/AiogramShopBot
cd ~/src/AiogramShopBot
cp .env.template .env
cp .env.next-admin.example .env.next-admin
docker compose version
```

Fill `.env` with `POSTGRES_PASSWORD`, `REDIS_PASSWORD`,
`SHOP_SECURITY_ENCRYPTION_KEY`, `NEXT_ADMIN_BRIDGE_SECRET`,
`NEXT_ADMIN_BRIDGE_ENABLED=true` and the exact
`MULTIBOT_WEBHOOK_BASE_URL=https://<machine>.<tailnet>.ts.net`. Fill
`.env.next-admin` with the same bridge secret, a different
`NEXT_ADMIN_SESSION_SECRET` and
`NEXT_ADMIN_PUBLIC_ORIGIN=https://<machine>.<tailnet>.ts.net`.
Keep `SHOP_ADMIN_SECURE_COOKIES=true`. Generate each plain secret with
`openssl rand -hex 32` and the Fernet key with
`openssl rand -base64 32 | tr '+/' '-_'`. Never commit these files.

Only for a **completely empty** local database:

```bash
docker compose -f docker-compose.yml -f compose.funnel-test.yml config --quiet
docker compose -f docker-compose.yml -f compose.funnel-test.yml build bot next-admin
docker compose -f docker-compose.yml -f compose.funnel-test.yml up -d --wait postgres redis
docker compose -f docker-compose.yml -f compose.funnel-test.yml run --rm --no-deps bot \
  python -m scripts.initialize_registry_database
docker compose -f docker-compose.yml -f compose.funnel-test.yml up -d --wait
```

For an existing database, back it up and use the reviewed migration path in
`scripts/deploy.sh info`. Never run the initializer on populated data or use
`docker compose down -v` to update the stack.

Check the local gateway and HTTPS origin:

```bash
curl -fsS http://127.0.0.1:8081/_edge/health
curl -fsS https://<machine>.<tailnet>.ts.net/manifest.webmanifest
curl -fsS -o /dev/null https://<machine>.<tailnet>.ts.net/pwa/icon/512
```

The setup form needs its one-time code from the backend container. Run the
documented first-owner setup command locally; keep its output private:

```bash
docker compose -f docker-compose.yml -f compose.funnel-test.yml exec bot \
  python -m scripts.first_owner_setup --browser-code
```

Visit `/setup`, enter that code locally, finish the owner account and MFA,
then use `/login` on subsequent visits. The same stable HTTPS origin works
on Android Chrome, iPhone Safari and the ChatGPT cloud browser. Register
test bots only after confirming login, webhook path isolation and receiver
readiness.

## Debian: authenticated development terminal

Use the official VS Code Linux CLI for the Debian x86-64 environment:

```bash
mkdir -p ~/tools/vscode-cli
cd ~/tools/vscode-cli
curl -fL 'https://update.code.visualstudio.com/latest/cli-linux-x64/stable' \
  -o vscode-cli.tar.gz
tar -xzf vscode-cli.tar.gz
cd ~/src/AiogramShopBot
~/tools/vscode-cli/code tunnel
```

Complete its GitHub sign-in and first-run license prompt yourself. Keep the
terminal running (or use VS Code's supported tunnel service mode after the
first interactive setup). The CLI prints a `https://vscode.dev/tunnel/...`
link. The connecting browser must use the **same GitHub account**. Share the
application's public origin and the `vscode.dev` tunnel link for a connection
test, but never share the GitHub login code, one-time owner code or any token.

When connected, the loop is: inspect UI/API via the public HTTPS origin;
inspect container logs and run tests through the authenticated development
terminal; edit/push on the same branch; pull/build/restart in Debian; retest
the unchanged HTTPS origin. If browser access to the VS Code terminal is not
available in this ChatGPT session, the public UI can still be tested here,
but terminal execution will need to run in a local Codex/VS Code session or
be relayed by the operator.
