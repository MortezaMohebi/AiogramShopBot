# Contract: Commerce view coordination and provider results

Internal interfaces; names describe responsibility, not new public methods or endpoints.

## Inputs and routing

- Authenticated ingress, live Bot/Store scope, normalized private user/chat and provider update ID
  are prerequisites. Preserve financial ingress and existing Runtime-owned callbacks and inbox
  receipts. Recognize only exact reserved commerce envelope and established legacy commerce
  families; stale commerce must bypass Runtime enrollment, form capture and workflow suspension
  before authorization. Keep a regression for fresh transitions out of an existing workflow.
- Standard inline data: `v1:<generation>:<slot>`. Use a URL-safe 12-character generation
  and a canonical 0–31 decimal slot. Require exact grammar, nonempty data, <=64 UTF-8 bytes,
  current generation, matching confirmed positive message ID, live expiry and allowed slot.
  Resolve server-held logical actions only; then run existing handler-level checks. Under this
  shape, the largest encoded callback is 18 bytes. A generation is a view discriminator, not
  a credential or a substitute for authorization.
- For rollout, old unversioned commerce writes and missing proofs are obsolete; do not dispatch
  their logical write. Allow only explicitly audited read-only legacy gallery/detail actions
  (and safe receipt reads if supported) through full live scope checks. Preserve published
  Workflow ownership, optional command aliases, and the separate finance path.
- A checkout Terms slot resolves an internal page + cart/revision + policy token + existing
  review proof. Recheck server-side before presenting any terms or returning. Invalid page,
  missing terms, changed proof and unavailable checkout return typed, read-only recovery;
  apply no acceptance on open/page/return. An old confirmation cannot be made fresh simply
  by refreshing the view.

## Presentation

The shared reply carries semantic purpose (navigation, durable event, requested media, or
temporary native contact) and ordered contextual inline actions. The coordinator resolves
effective native keyboard rows, using one keyboard kind per API call. Do not send a second
keyboard announcement on every interaction. A send that installs a native keyboard is
only for first install, policy drift, or contact exit/restoration (including explicit remove
when there are no allowed destinations). Contact and inline do not share native markup.
Classify installation separately from navigation and avoid automatic resend on ambiguity;
an intentionally fresh allowed interaction can restore it. Any reply text or note is subject
to authorization and the existing shared length/media policy. Fit product labels to the
64-character shared button limit and keep full names reachable in detail. Fit compact list
rows to the text budget without losing page position or recovery controls. Never truncate
terms, material checkout details, or amounts to fit a preview.

| Outcome | Adapter supplies | Coordinator obligation |
| --- | --- | --- |
| Confirmed edit or confirmed send | Same positive ID for edit or new positive ID for send | Publish reserved generation; retain the known pointer. |
| No change | Same ID only if the rendered controls and view signature match or the provider explicitly confirms equivalent edit | Zero new messages; do not advance to controls that were never published. |
| Definite edit inability | Known target mismatch/not editable/removed with operation-specific evidence, or documented unsupported media transition | At most one reserved replacement; stale-markup cleanup only when a distinct old navigation ID is safe. |
| Definite failure | Invalid payload, explicit rate limit or definitive non-delivery | No alternate resend for invalid content or throttling. Keep or offer the last provably safe route; later deliberate retry only as authorized. |
| Unknown | Timeout, ambiguous network or decode failure, unexpected error shape or lost owner | Do not resend/re-edit automatically. Quarantine uncertain target and suppress obsolete-tap replay. Explicit Home or another authorized fresh interaction can create a new target. |

Telegram can use compatible media edits and its documented persistence hint. Bale can edit
text/caption and inline markup, replaces a preview where media edit is unavailable, and
retains the legacy acknowledgement exception. Provider limits and evidence are in
[research.md](../research.md). Routine text navigation should add zero messages on a
supported edit/no-op, at most one on confirmed replacement. Those counts exclude deliberate
media, durable milestones and a necessary keyboard installation; measure each separately.

Acknowledgement failure is cosmetic: do not bypass validation or cancel recovery. Do not
delete customer history. Repeated receipt/invoice/refund/delivery actions retain existing
idempotency; delivery and financial paths never use the navigation fallback API.
If an unknown result leaves no confirmed view, the next deliberate authorized Home or
existing start command can establish a new one; repeated taps on the obsolete action
cannot retry it. No guarantee of message delivery is made during a provider outage.
