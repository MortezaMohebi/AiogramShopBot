# Component skeletons implementation plan

> **For agentic workers:** Execute inline with superpowers:executing-plans; the user approved the recommendation and requested implementation.

**Goal:** Keep authorized controls available while data sections stream; defer expensive Studio forms until rendered.
**Architecture:** Async Server Components inside keyed Suspense boundaries, signed GET reads, local handling of known upstream 5xx failures. Keep session/Store/role checks ahead of protected content. Use client dynamic imports for inspector/settings; retain parent draft/mutation state.
**Tech Stack:** Next.js 16.4.3, React 19.2, existing Tailwind tokens/Vazirmatn; no dependency added.
**Spec:** User-approved recommendation in this conversation: Products results, independent Orders list/review queue, one Dashboard overview response, selective Studio panels; RTL/themes/reduced motion; Thinking Orbs for ongoing actions.

## Constraints / review focus
- Preserve query normalization, pagination, permissions, Store isolation, redirects, action handlers and unknown outcomes.
- No global user-data cache, new endpoint, fake metric, automatic mutation retry, deployment or merge.
- Pending must not appear empty/zero; known 5xx replaces only its section. Other failures retain existing handling.
- Query/page changes reveal matching fallbacks; Studio selection changes during import use current props.
- Browser tests use isolated read-only fixtures and real render components; no live business operation.

## Task 1 — Streaming data sections
Files: products/orders/dashboard page.tsx; components/data/{products,orders,overview,skeletons,section-error,refresh}.tsx; lib/read-section.ts; tests/component-streaming.test.mts.
- [x] Add real-page regressions with controlled GETs: shell before products/overview, list before held queue, finance never requests queue, denied role never reads data, query preserved, 5xx distinct from empty and private errors hidden.
- [x] Run baseline; extract existing markup into typed data/view components; fetch in async children; add matching skeletons and safe error/GET refresh.
- [x] Add Suspense after authorization, keys from normalized queries; preserve Store layout validation.
- [x] Run focused/full unit/type/lint/build.
- [ ] Publish the reviewed source checkpoint.

## Task 2 — Studio panels
Files: components/workflows/editor.tsx and shared form skeleton; browser test.
- [x] Replace static inspector/settings imports with client dynamic imports and matching fallbacks. Leave canvas and state/mutation owners unchanged.
- [ ] Verify delayed panel loading, selection replacement and read-only save behavior in real editor.

## Task 3 — Acceptance/publication
- [ ] Browser: actual skeleton/view components under controlled server latency; pending/partial/loaded/error, five widths, both themes, reduced motion, controls.
- [ ] Check React/Next diagnostics, inspect captures, remove fixtures, stop dedicated runtime.
- [x] Independent final source review: no Critical or Important findings; 11 regressions independently passed.
- [ ] Publish to Draft PR19, preserve existing evidence; update ledger.

Ruling: continue the existing isolated feature worktree and PR19; the user's approval authorizes this implementation without another checkpoint.

## Verification blocker

Automatic approval review denied source upload to the existing private Codespace because destination-specific approval was not present. No alternate transfer or indirect execution was attempted. Local Chromium aborts on process-singleton socket creation (`EPERM`), and agent-browser cannot start its daemon. The temporary fixture was removed and the local dev server stopped. Browser matrix, Next runtime diagnostics and React mount checks remain pending; no UI PASS is claimed.
