# First owner and email setup

Fresh startup creates schema and Store data but no staff identity. The owner
opens a private Codespace terminal and explicitly creates the first global
administrator, choosing the username and entering the password without shell
arguments or environment variables. An advisory lock and empty staff table
condition make that operation one-time; subsequent users use the existing
administrator invitation flow. Existing installations retain every account.

SMTP configuration is an optional private setup operation. Its credential
stays in the owner-only configuration file, never in a database or API response.
The application has no implicit SMTP destination or delivery before setup.
Email templates are Persian plain-text and HTML, with escaped dynamic content,
for invitation, password reset, MFA security notice and SMTP test. Email
must never by itself waive MFA or reveal a recovery code. If delivery fails,
the existing administrative recovery paths remain available.

The first milestone does not auto-send account recovery email: that requires
verified staff email addresses and an explicit enrollment flow. It does make
SMTP transport and templates ready and testable for that next milestone.
