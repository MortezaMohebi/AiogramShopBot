# Login persistence and credential-manager correctness

User reports invalid credentials after owner MFA reset, plus Chrome offering to save a rejected password; explicitly requests Remember me and its behavior.

- Diagnose supplied Request ID using metadata only. Do not copy the supplied secret into tools, source, shell history or evidence. Actual sign-in can use browserAuth secure input only; one secure attempt was submitted and visibly rejected. No automatic password/MFA change.
- Add unchecked Remember me. Default: browser-session cookie, backend8h absolute/30m idle. Opt-in:30days absolute and idle, still revocable and version-bound. Infer remembered server sessions from their issued duration (no schema change). Keep fresh-proof requirements for sensitive actions. Backend returns the exact TTL; signed cookie and browser persistence must agree. Preserve the choice across the MFA step.
- Keep failed password form/value present, mark the error and stay on the same screen. Offer Credential Management storage only after confirmed full success and an allowlisted redirect; no API store on bad password, pending MFA or bad OTP. Unsupported/declined storage cannot break login. Correct autocomplete semantics remain intact; browser-native heuristics are not fully site-controlled.
- Map only known credential failures to401; an unknown internal401 must be a service error, not a false wrong-password claim. Correlate bridge errors safely without payload logging.
- Add regression tests for backend duration/revocation, actual BFF cookie/token behavior, initial checkbox, and browser store/persistence across both steps. Run relevant suites, Next checks/build, review, publish and retest existing private QA preview. Keep earlier pending component/whole-dashboard acceptance separate.
