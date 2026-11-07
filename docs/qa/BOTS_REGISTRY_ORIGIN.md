# Bots Origin regression and active Registry cutover

Date: 2026-11-07. Draft PR #19.

Exact error digest 4184552278 came from Next Server Actions rejecting Origin http://localhost:3006 against the configured Codespaces forwarded host. It was not a database or Legacy row read failure. The proxy restores Origin only for POST actions with same-origin Fetch Metadata, exact configured Codespaces forwarded hostname and the matching loopback port. Cross-site/mismatched/missing-action inputs remain unchanged and Next CSRF validation stays enabled.

Validation: 306 Next tests PASS, Typecheck/Lint and production Docker Build PASS. Full Python baseline with the Registry-only ASGI entrypoint:1292 PASS,3 existing collection warnings. Production browser with an isolated synthetic session/Stores:3 PASS (authenticated /bots, real Store selection Server Action through forwarded headers, refresh); zero console/page errors. The fixture was removed. Unknown-action HTTP probes reached action parsing for trusted metadata and were rejected before actions for cross-site metadata.

Active3006 stack now imports no original bot.py/run.py dispatcher or SQLAdmin UI. Its /healthz reports runtime=registry. Two seeded Legacy bots and their credential/operations/events were removed after a private PostgreSQL backup and reference inventory; modern orders/products were empty and owner/MFA/Store were preserved. Global environment Tokens were removed from active app/worker configuration. Providers were not mutated or messaged. Webhook port8086 stays private.

This is the immediate fix checkpoint. Full repository removal of compatibility code/schema continues on refactor/remove-legacy-runtime and is not claimed complete by this checkpoint.
