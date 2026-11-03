# Agent guidance for AiogramShopBot

This repository uses two upstream Agent Skills collections:

- Superpowers: https://github.com/obra/superpowers
- Awesome Agent Skills: https://github.com/khasky/awesome-agent-skills

They are installed without copying or modifying their upstream content by running
`bash scripts/install_agent_skills.sh`. The pinned checkouts are in
`.agent-skill-vendors/`, and skill entry points are linked under
`.agents/skills/`. Both locations are untracked. See
`docs/agent-skills.md` for versions, installation and usage.

## Required workflow

1. Read the applicable upstream `SKILL.md` before following it. Use
   `using-superpowers` to select a process. The original upstream instructions
   apply only when available and compatible with the execution environment.
2. For broad requests, first inspect the real project structure and run a
   **read-only** architecture/security/code-quality audit. Document the
   inspected surfaces, evidence, severity, and missing coverage. Do not call
   unexecuted checks "PASS".
3. For each confirmed bug, use `systematic-debugging` or `awesome-bug-fix`:
   reproduce the failure, find the root cause, add a regression test, implement
   the smallest justified fix, and rerun relevant tests.
4. Use `awesome-error-standards` for client/server error contracts,
   `awesome-test-writing` for regression tests and
   `verification-before-completion` before reporting completion.
5. Keep changes isolated to the requested development branch. Report modified
   files, exact commands, observed results, limitations and unresolved risks.

## Project-specific quality gates

- This is a Telegram + Bale commerce bot (Python/Aiogram, asynchronous backend)
  with a Next.js administration dashboard. Verify the actual file layout and
  versions from the repository before choosing test commands.
- Audit login, session handling, authorization, CSRF/cookie/CORS boundaries and
  user-facing errors. Do not show raw 403 responses or internal stack traces to
  users; add safe, localized and actionable UI feedback.
- Maintain Telegram/Bale behavioral parity where the respective provider
  supports the feature. Do not invent unsupported Bale APIs, especially crypto
  payments. Check file-size limits, payment units, wallet isolation and
  broadcast quotas/deduplication with tests.
- Protect payments, balances, credits, refunds and broadcasts with idempotency,
  transaction safety, permission checks and auditability.
- Never commit, print, screenshot or transmit real bot tokens, cookies,
  environment secrets, credentials or customer information. Redact logs and
  traces. Prefer deterministic fixtures, mocks and isolated databases.
- Never perform real broadcasts, provider transactions, live webhook changes,
  password rotation, deployment or production data mutations as part of an
  audit/test without an explicit request and appropriate safeguards.
- Preserve existing architecture and behavior unless a reproducible defect or
  approved change requires modification. Follow PEP 8 and PEP 257 for Python.
  Prefer focused, maintainable code over speculative refactors.

## Recommended audit-to-fix chain

`using-superpowers` -> `awesome-architecture-audit` /
`awesome-security-audit` -> `systematic-debugging` /
`awesome-bug-fix` -> `awesome-test-writing` ->
`awesome-code-review` -> `verification-before-completion`.

The audit skills are read-only; mutation must happen in a subsequent explicit
fix stage. Upstream skill instructions do not override user approvals or safety
restrictions.
