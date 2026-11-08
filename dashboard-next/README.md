# Administration dashboard

Next.js16.4.3 / React19.2, Persian RTL, light/dark themes. Business rules and permissions live in the FastAPI backend; browsers never receive bridge/session signing keys or stored bot tokens.

```bash
npm ci
npm run dev
```

Configure `SHOP_FASTAPI_INTERNAL_URL`, matching `NEXT_ADMIN_BRIDGE_SECRET` and a separate `NEXT_ADMIN_SESSION_SECRET`. Production requires exact `NEXT_ADMIN_PUBLIC_ORIGIN` over HTTPS. Codespaces uses the generated private configuration from repository Setup. Keep the private backend/Dashboard outside the public webhook gateway.

Login checks password before a separate MFA screen. StoreContext limits active/current Stores; per-bot management always rechecks Store ownership. Credentials and receiver transitions are available only through `/bots/{id}` with the required role and recent authentication. Global bot connection/profile/transport pages and SQLAdmin are retired.

The request proxy restores Codespaces' loopback Origin only when exact configured forwarded hostname, loopback port, same-origin Fetch Metadata and action POST agree. Other Origins remain subject to Next's CSRF checks; no wildcard allowed origins are configured.

```bash
npm test
npm run typecheck
npm run lint
npm run build
```

Use the real running application and an isolated synthetic session for browser acceptance. See repository `docs/qa/` for source-specific reports. Package notices are shipped in `THIRD_PARTY_NOTICES.txt`.

Interactive console lists can use `useSectionList` with server-provided initial data, namespaced URL filters and a fixed, authenticated GET route. Use `SectionSearch` for removable filters and `useSectionCommand` with a typed Server Action for writes. Return a receipt or a stable error to the section, refresh only affected reads, and reconcile uncertain writes before resubmission. The bot catalog access panel is the reference implementation.
