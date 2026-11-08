# Local Windows Docker test and debug loop

Use this workflow for `feat/first-run-owner-email-20261107` when Docker Desktop
runs on Windows. WSL and Docker's WSL integration are not required.

The app runs in Docker Compose on the Windows host. Tailscale Funnel gives it
one stable public HTTPS origin without a purchased domain. An optional VS Code
Remote Tunnel offers authenticated access to the Windows project and terminal.
These are separate connections: the development terminal is never published by
Funnel. ChatGPT access to the VS Code terminal must be tested before relying on
it for a remote test/debug/retest loop.

## 1. Checkout and prerequisites

Use **PowerShell on Windows**. Choose a working directory on a drive with
enough space for the repository, PostgreSQL data and uploaded media. Docker
Desktop must be running in Linux container mode. A checkout inside Debian is
not needed for this route.

```powershell
docker version
docker compose version
git clone --branch feat/first-run-owner-email-20261107 https://github.com/MortezaMohebi/AiogramShopBot.git
Set-Location .\AiogramShopBot
Copy-Item .env.template .env
Copy-Item .env.next-admin.example .env.next-admin
```

The project directory must be accessible to Docker Desktop for bind mounts.
Keep the checkout, `postgres_data` and `media_data` on the same drive. Do not
publish ports 3000, 5000, PostgreSQL or Redis through a router or Windows
firewall; the Compose overlay maps the gateway only to Windows loopback port
8081.

## 2. Get one stable HTTPS origin

Install and sign in to [Tailscale for Windows](https://tailscale.com/docs/install/windows).
Enable MagicDNS, HTTPS certificates and Funnel for the tailnet when prompted.
From an **Administrator PowerShell**:

```powershell
tailscale funnel --bg 8081
tailscale funnel status
```

The first command may ask you to approve Funnel in a browser. Record the
displayed `https://<machine>.<tailnet>.ts.net` origin without a trailing slash.
It may temporarily return a gateway error until the Compose stack is running.
Funnel's public HTTPS endpoint maps to the local Docker gateway on port 8081;
it does not make the development terminal public.

## 3. Configure private environment files

Edit `.env` and `.env.next-admin` locally. Set at least these values:

| File | Setting |
| --- | --- |
| `.env` | `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `SHOP_SECURITY_ENCRYPTION_KEY`, `NEXT_ADMIN_BRIDGE_SECRET` |
| `.env` | `MULTIBOT_WEBHOOK_BASE_URL=https://<machine>.<tailnet>.ts.net`, `SHOP_ADMIN_SECURE_COOKIES=true` |
| `.env.next-admin` | The **same** `NEXT_ADMIN_BRIDGE_SECRET`, a different `NEXT_ADMIN_SESSION_SECRET` |
| `.env.next-admin` | `NEXT_ADMIN_PUBLIC_ORIGIN=https://<machine>.<tailnet>.ts.net` |

`SHOP_SECURITY_ENCRYPTION_KEY` is a URL-safe Base64-encoded 32-byte key
(Fernet). Generate independent random values for all secrets. In PowerShell,
the following function works without Python or OpenSSL:

```powershell
function New-RandomKey {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    [Convert]::ToBase64String($bytes).Replace('+', '-').Replace('/', '_')
}
New-RandomKey
```

Run `New-RandomKey` separately for the encryption key, bridge secret and
session secret. Keep `.env`, `.env.next-admin`, bot tokens, one-time setup codes
and passwords on your PC; never commit or paste them into chat. The public
origin must exactly match in both files, without a port or trailing slash.

## 4. Start from an empty local database

Only run the initializer if `postgres_data` has no existing installation.
Use a PowerShell array to avoid shell-specific line continuations:

```powershell
$composeFiles = @('-f', 'docker-compose.yml', '-f', 'compose.funnel-test.yml')
docker compose @composeFiles config --quiet
docker compose @composeFiles build bot next-admin
docker compose @composeFiles up -d --wait postgres redis
docker compose @composeFiles run --rm --no-deps bot python -m scripts.initialize_registry_database
docker compose @composeFiles up -d --wait
```

For an existing database, use the reviewed migration route instead of the
initializer. Do not use `docker compose down -v` to update the stack.

Check the local gateway and public origin:

```powershell
(Invoke-WebRequest http://127.0.0.1:8081/_edge/health).StatusCode
(Invoke-WebRequest https://<machine>.<tailnet>.ts.net/manifest.webmanifest).StatusCode
docker compose @composeFiles ps
```

For a **new empty installation**, obtain the one-time owner setup code locally:

```powershell
docker compose @composeFiles exec bot python -m scripts.first_owner_setup --browser-code
```

Open the public origin's `/setup` in your browser, complete the owner setup,
then use `/login`. The dashboard requires login and MFA after setup. Once
these work, register the test Telegram and Bale bots in the dashboard.

## 5. Optional authenticated terminal for remote debugging

Install VS Code on Windows and open the project folder there. In its Accounts
menu, choose **Turn on Remote Tunnel Access**, sign in with your GitHub account,
and open the displayed `https://vscode.dev/tunnel/...` URL with the same account.
Alternatively, run `code tunnel` in PowerShell and complete its sign-in. Keep
VS Code or the CLI tunnel running while remote access is needed.

Share the **public application origin** and, if using Remote Tunnel, its
`vscode.dev` link for a connection test. Do not share the GitHub sign-in code,
setup code, passwords or bot tokens. Test from this ChatGPT session whether
the authenticated browser actually exposes a working terminal. If it does,
inspect the app, logs and tests there; edit and rebuild on the same branch;
then retest the stable HTTPS URL. If the terminal is unavailable to this
session, run commands locally in PowerShell or in a local Codex/VS Code session
and paste only sanitized errors here.

```powershell
docker compose @composeFiles logs --tail=100 bot next-admin test-gateway
docker compose @composeFiles up -d --build --wait
```

The second command rebuilds and restarts the local stack after source changes.
The stable Funnel origin stays the same. Stop public access when testing ends
with `tailscale funnel --https=443 off` in Administrator PowerShell.
