Adds a typed Backend Action boundary so Workflow definitions can bind reviewed commerce operations with exact versions, trusted Store/Bot/customer context, atomic execution receipts and request-bound confirmation/approval proofs. Existing cart, search and support flows reuse the same business primitives.

The registry contains 15 explicit adapters and four discoverable unavailable contracts. Studio gains a typed Action node with five outcome transitions and an Action Catalog with filters, policies, schemas, contextual availability and limited safe dry-run. The Simulator remains deterministic and performs no business mutation.

Stacked on Draft PR #15 at `c3c6e79796f864f09df4deb0462cd36f221dbf9e`. Keep this PR Draft.

### Executed validation

| Gate | Result |
| --- | --- |
| Full Python, host and Codespace | 968 PASS; 3 existing collection warnings |
| Next unit tests | 99 PASS |
| Cloudflare Relay | 14 PASS |
| Compile, Typecheck, lint, production build | PASS in Codespace |
| Real PostgreSQL Actions / Signed HTTP | 11 PASS groups |
| Existing Workflow PostgreSQL regression | 4 PASS groups |
| Legacy Telegram/Bale journeys | Both PASS with Fake Providers |
| Actual browser | 35 PASS groups; 64 viewport/theme route combinations |
| Independent implementation review | No remaining Critical/Important findings after fixes |
| Repository GitHub Actions | Disabled after explicit authorization; persisted setting verified after reload |

Real PostgreSQL regressions cover concurrent identical claims, changed-input conflicts, stale cart revisions, single-use confirmation replay, rollback on invalid adapter output and lost-commit-acknowledgment recovery. Scoped fixes also cover legacy Bot disable gates, cleanup of unquotable carts and direction-aware typed output mappings.

### Evidence and boundaries

- [Implementation and contracts](https://github.com/MortezaMohebi/AiogramShopBot/blob/feat/bot-experience-layer2-action-registry/docs/ACTION_REGISTRY_LAYER2.md)
- [Acceptance report](https://github.com/MortezaMohebi/AiogramShopBot/blob/feat/bot-experience-layer2-action-registry/docs/qa/ACTION_REGISTRY_LAYER2_ACCEPTANCE.md)
- [Machine-readable evidence](https://github.com/MortezaMohebi/AiogramShopBot/tree/feat/bot-experience-layer2-action-registry/docs/qa/action-registry)

Verified application/runner tree: `e17aac89e2628bbd4c779b708b381938914c7677`; subsequent commits contain evidence/documentation only.

No live provider calls, payment capture, Broadcast, customer Workflow Runtime/routing, Layer 4 MCP, production deployment or merge. Return eligibility, returns, wholesale and admin notification remain explicitly unavailable until their real services/policies exist. Original checkout, five main Codespace services and data were preserved.
