# First owner and email setup Implementation Plan

**Goal:** Remove generated administrative identities and prepare configurable SMTP with safe Persian templates.

**Architecture:** Start schema without staff; create the first superadmin from a private owner command under a DB lock. Persist SMTP configuration only in the private env file and render strict template types.

**Tech Stack:** Python, SQLAlchemy, Docker Compose, stdlib SMTP, pytest.

**Spec:** `docs/superpowers/specs/2026-11-07-owner-email-setup.md`

## Tasks

- [x] Test first-run bootstrap creates zero staff and owner setup is single-use.
- [x] Replace fixed Codespace username/password and grant the chosen owner Store access.
- [x] Test private SMTP configuration and escaped template rendering.
- [x] Wire configuration to backend and validate optional SMTP connection.
- [x] Run focused and broad checks, then document the operator commands.

Focused validation: 61 relevant tests passed. Docker runtime verification awaits an environment with Docker and SMTP credentials.
