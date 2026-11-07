# Store scope regression and connection readiness

Date: 2026-11-06. Draft PR: #19, branch: feat/dashboard-ui-ux-polish.
Tested application source: bb7594729d42b0ce23da1e7fd8a210d5a28bc38e.

## Reported errors and correction

The Codespace bridge log for request 0ed1edd0-d19c-4d9f-80db-691b7c1deecf identified HTTP 403 on an inactive Store's payment-accounts endpoint. The Registry's global default Store is not necessarily the session's current or active Store. Payment Accounts used that default; Stores requested protected policies for every granted Store, including inactive Stores.

Commit 2f8c79069bba9800c2989764ca566611dd99ad32 changes both pages to read the real StoreContext. Payment Accounts defaults to the current Store, offers only active Stores, and redirects stale/inactive query parameters before a protected read. Stores reads policies only for active Stores. Backend Store and role enforcement is unchanged. Nine regression tests failed against the earlier pages and passed after the correction. Genuine service failures still propagate.

A browser-discovered favicon 404 was corrected in bb7594729d42b0ce23da1e7fd8a210d5a28bc38e, reusing the existing Lucide Store icon with its third-party notices copied into both Docker runners.

## Validation

| Check | Result | Scope |
| --- | --- | --- |
| Next unit suite | PASS, 298/298 | Includes nine Store page regressions |
| Typecheck and Lint | PASS | Local source and final Docker build |
| Production Docker build | PASS | Latest source; standalone Dashboard rebuilt |
| Channel/Receiver/Runtime Python tests | PASS, 77/77 | Six focused suites; Fake Provider/offline |
| Real browser | PASS, 15 checks | Actual Next dev, Signed Bridge and isolated PostgreSQL |
| Console, page errors and failed HTTP responses | PASS, zero | Includes repeated client navigation/Back and conditional use warning monitoring |
| RTL/light/dark layout | PASS | 390px and 1440px; four captures attached |
| React inspection | PASS | Mounted StoreSwitcher found through agent-browser |
| Next MCP compilation | PASS | issues=[] |
| Browser-connected Next MCP errors | PASS | configErrors=[], sessionErrors=[] |
| Next MCP page metadata | PASS | Active /stores App Router page and boundaries identified |
| Synthetic fixture cleanup | PASS | Only generated QA session/Stores removed; private state files removed |

The final browser run was serial, after the production image build completed. An earlier attempt timed out while the QA dev server became unavailable during simultaneous work; it was restarted and the complete final run passed. A prior run also discovered the favicon 404. Failed attempts were not counted as passing acceptance.

The attached evidence.json contains the exact 15 checks and Next MCP responses. The browser used synthetic staff and two empty synthetic Stores in provider-free QA. It did not enter the owner's password, reset MFA, perform real authentication writes, send messenger messages or transact payments. The reported use() warning was not observed in the final run; no unrelated React/Next behavior was suppressed.

## Separate Telegram/Bale connection environment

Codespace: obscure-space-couscous-p7w6p4jrrxv3j59.
Checkout: /workspaces/AiogramShopBot-mcp-qa.
Docker project: telegram-bale-connection-ready.

| Component | Result |
| --- | --- |
| PostgreSQL, Redis, real FastAPI app, webhook gateway, production Dashboard | PASS, healthy |
| Durable Runtime worker | PASS, running |
| Dashboard /login and /favicon.ico on 3006 | PASS, HTTP 200 |
| Backend /healthz on loopback 8096 | PASS, HTTP 200 |
| Webhook gateway health on 8086 | PASS, HTTP 200 |
| Internal admin route through webhook gateway | PASS, HTTP 404 |
| Telegram webhook without required secret | PASS, HTTP 401 |
| Telegram getMe, @testmory2bot | PASS, read-only identity check |
| Bale getMe, @healer_bot | PASS, read-only identity check |
| Public webhook ingress | PENDING, port 8086 remains Private |
| Real webhook registration/delivery | NOT RUN; current provider destinations unchanged |
| Owner interactive login on 3006 | NOT RUN; current password hash/MFA profile preserved |

This stack uses a separate fresh current-schema database and separate volumes. The old live checkout, its dirty files and database were not reset or migrated. The existing QA provider tokens remain blank. Existing owner credentials/profile were preserved internally without printing secrets or changing the password. The connection configuration is private and ignored by Git; no tokens, session cookies, passwords, webhook paths or keys are included in this evidence.

Restart the prepared connection stack inside Codespace:

```bash
cd /workspaces/AiogramShopBot-mcp-qa
bash .codespaces/bot-connections/start.sh
```

Use Ports > 3006 for the private Dashboard. The cloud-browser forwarded URL reached GitHub's private-port sign-in, so that outer authentication path is not claimed as verified app login. Port 8096 stays private. Only webhook port 8086 needs external exposure for provider delivery; exposure and actual webhook registration remain separate final operations. Financial, paid broadcast and workflow publication were not activated.

Keep PR #19 Draft. This focused acceptance does not replace the previously incomplete full Dashboard role/detail and component-loading acceptance.
