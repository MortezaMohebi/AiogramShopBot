# Lazy media previews and skeletons

User-requested `lazysizes` integration on `feat/dashboard-ui-ux-polish`, Draft PR #19.

## Scope

Installed and pinned `lazysizes@5.3.2` through npm. The MIT notice is retained in `docs/licenses/lazysizes-MIT.txt`; no additional runtime dependency was introduced.

The media library and product media editor now show a 96×96 preview for PNG, JPEG, WebP and GIF files. The shared `MediaThumbnail`:

- Reserves its dimensions in server markup and displays a theme-aware skeleton until the real image loads.
- Imports lazysizes after hydration, avoiding library DOM mutations during SSR/hydration.
- Uses the existing same-origin authenticated `/api/admin/preview/product/{id}` proxy. Its session, Store checks, private/no-store caching, MIME handling and response headers are unchanged.
- Limits previews to supported raster MIME types and positive safe-integer media IDs. Document, audio, video and SVG records retain their existing preview links without inline image loading.
- Uses a per-element viewport threshold to avoid aggressive offscreen preloading. Native lazy loading remains available if the library chunk fails.
- Derives success from a real image load and positive natural width. Errors replace the skeleton with a Persian failure message; they are not mistaken for successful library completion.
- Remounts on media identity changes, so a previous image's events cannot settle a replacement. JavaScript-disabled browsers receive a noscript image fallback.

Existing preview links, upload/moderation/deletion flows, CAPTCHA/MFA images, application data loading and page Suspense boundaries remain unchanged. These previews load the existing original image; this change does not add a server-side thumbnail resizing service.

## Evidence

| Check | Result |
|---|---|
| Product-media render regressions | Baseline: 1 FAIL / 2 PASS; final: 3 PASS |
| Full dashboard unit suite | 254 PASS, 0 FAIL, 0 skipped |
| TypeScript, ESLint, production build | PASS |
| Focused independent source review | No open Critical, Important or Minor findings after two small fallback fixes |
| Isolated Codespace browser matrix | 13 PASS, 12 captures, no mutations or unexpected browser exceptions |
| Skeleton/error UI and RTL | 320, 390, 768, 1024 and 1440px; light and dark themes |
| Offscreen image | No request/source until scrolled into view; one request after reveal |
| Loading success and dimensions | Actual PNG decoded at natural width 96; reserved dimensions remain 96×96 |
| Source replacement | Fresh loading state and confirmed replacement source |
| Failure handling | Readable failure state; no repeated request for the failed image |
| JavaScript disabled | Noscript fallback actually completes and decodes |
| Temporary fixture | Removed after the run |
| Final Next.js MCP | PASS — metadata, routes, compilation issues, errors and page metadata |
| Final agent-browser React check | PASS — mounted page component tree |
| Visual review | Mobile loading/error/success captures inspected in both themes |

The browser fixture renders the production thumbnail and product-media components using actual dashboard styles/providers. Synthetic PNG/404 responses are intercepted at the existing preview URLs. All API mutations and external traffic are blocked. This tests UI behavior, not a live authenticated media transaction; no upload, deletion, moderation, messenger or payment operation was performed. Backend access-control behavior was not changed.

The earlier broader dashboard acceptance remains tracked separately in `UI_UX_ACCEPTANCE.md`. This scoped lazy-media pass does not replace that full authenticated route sweep.
