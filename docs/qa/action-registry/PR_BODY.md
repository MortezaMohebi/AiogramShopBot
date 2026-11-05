Add a versioned typed Backend Action boundary with Store/Bot/customer policies,
atomic execution receipts, request-bound customer/operator proofs, deterministic
simulation and limited Catalog dry-run. The registry exposes 15 explicit commerce
adapters and four honestly unavailable contracts. Legacy cart, search and support
flows reuse the same business primitives.

Workflow Studio gains a typed Action node with five outcome transitions and
validated variable/constant/context mappings, plus the real `/studio/actions`
Catalog with filters, availability, schemas and safe inspection. No customer
Workflow Runtime, messenger routing, MCP, live providers, merge or deployment is
included.

Validation and limitations: see
[`docs/qa/ACTION_REGISTRY_LAYER2_ACCEPTANCE.md`](../ACTION_REGISTRY_LAYER2_ACCEPTANCE.md)
and [`docs/ACTION_REGISTRY_LAYER2.md`](../../ACTION_REGISTRY_LAYER2.md).

Intended Draft PR base: `feat/bot-experience-workflow-builder`.

Creation is pending explicit permission to disable repository GitHub Actions and
verification of the saved Disabled setting. Do not create this PR while that
prerequisite is unresolved; its existing pull-request workflow could run.
