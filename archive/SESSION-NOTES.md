# archive/SESSION-NOTES.md — Verification details not otherwise preserved

Loaded only when a pointer is followed — never at session kickoff. Holds session
detail confirmed NOT already present in a commit message or in archive/POST-MORTEMS.md,
surfaced during the 2026-07-12 documentation-efficiency pass (HANDOFF.md rewrite to
the PROMPTS §3 template).

## squeeze_breakout §2 consultation-window experiment — interim test count (2026-07-11/12)
During the experiment session (before the revert in commit fd70f4c), the full suite
passed 248/248 (236 baseline + 12 new tests covering the amended gate's boundary
semantics in both directions and the SL-freeze mechanism). The revert removed both the
implementation and these 12 tests, restoring the 236-baseline suite confirmed green in
fd70f4c's own commit message. This number is not load-bearing for future work — the
tests it describes no longer exist in the tree — but is recorded here since it was not
otherwise written down anywhere durable.
