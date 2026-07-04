---
Purpose: Session playbook for Claude Code. The context window is disposable; CLAUDE.md + TRADING-RULES.md + HANDOFF.md + git + the journal ARE the memory. A session ending without writing state back has leaked its work.
---

# PROMPTS.md — Session Playbook

## 1. Session Loop (one session = one phase, or one bounded task within it)
```
/clear → ORIENT → PLAN → EXECUTE → VERIFY → CLOSE-OUT → commit → /clear
         read docs  topology  build w/   tests+DoD   write HANDOFF,
         +HANDOFF   +plan,    EXEC-      checklist   tick phase, BRAIN/
         +recon     approval  MOMENTUM   (fail→fix)  ROADMAP capture
```
ORIENT=CODE-RECON.md · PLAN=AGENTS.md Friction Loop+Verification Gate · EXECUTE=EXECUTION-MOMENTUM.md · VERIFY=BRAIN.md criteria + §4 exit criteria · CLOSE-OUT=HANDOFF + CLAUDE.md phase table.

## 2. Context-Clearing Rules
- `/clear` between phases, always — each phase starts from docs, not residue.
- `/clear` when switching session type (build↔bug↔strategy-change).
- Mid-phase context degradation → Close-Out (§5.4) → commit → `/clear` → Resume (§5.5). HANDOFF makes wipes lossless.
- `/compact` = mid-phase stopgap only; NEVER during VERIFY (summaries can drop the invariant being verified).
- NEVER `/clear` with uncommitted work or unwritten HANDOFF.
- A session touching strategy code may not end before its revalidation note (TRADING-RULES §5) is written.

## 3. HANDOFF.md (repo root; overwritten each close-out, read each kickoff, archived to commit msg on phase completion)
```markdown
# HANDOFF — <UTC ts>
Phase: <n> — <name>   Status: IN-PROGRESS|COMPLETE|BLOCKED
Done this session: <facts>
Not done / next action: <specific enough to start cold>
Open tensions: <deferred decisions, flagged risks>
Files touched: <paths>
Do NOT redo: <intentionally unfinished items>
```

## 4. Phase Exit Criteria (VERIFY must confirm ALL)
| # | Objective | Exit criteria |
|---|---|---|
| 1 | Scaffold | pip install clean from pins; migration creates all tables; secrets grep hook passes; .env.example committed, .env ignored |
| 2 | Data layer | tests prove complete==False never passes; 2nd fetch hits cache; precision registry correct for JPY + non-JPY pair |
| 3 | Indicators+regime | outputs match known-good refs; transition tests pass incl. 2-candle confirm + min-hold; per-pair calibration pass-rate notes written |
| 4 | Backtester | golden-run locked (fixed data→identical metrics); costs demonstrably reduce PnL vs zero-cost; same Strategy interface as live |
| 5 | trend_pullback | TRADING-RULES §5 gates 1–6 run+reported per pair; SL/TP tested both directions; near-miss journaling visible |
| 6 | range_reversion | as 5 + expansion-veto test proves stand-down on ATR spike |
| 7 | squeeze_breakout | as 5 + BB-width percentile pass-rate documented (not always/never-true) |
| 8 | Risk+execution | sizing tested; caps aggregate per-currency across pairs; breakers trip in simulated failures; order verify + rejection journaling proven vs practice API |
| 9 | Dashboard local | all routes reject unauthenticated requests; pair toggle off → next heartbeat excludes it; near-miss vetoes render on /signals; kill switch typed-confirm |
| 10 | PA deploy | DEPLOY-PYTHONANYWHERE.md smoke-test order-of-proof passes incl. remote pair toggle |
| 11 | Live gate | 60+ day forward report within tolerance of backtest; explicit user sign-off. **Claude Code never flips this alone.** |

## 5. Prompt Library

### 5.1 SESSION 0: Bootstrap (once)
```
Read CLAUDE.md, AGENTS.md, TRADING-RULES.md in full. No code.
Confirm in your own words, <300 words: (1) the purpose seed, (2) the seven
Prime Directives, (3) the three truth homes and what each owns, (4) HANDOFF.md's
role per PROMPTS.md §3.
Then initialize: git repo, .gitignore (instance/, .env, __pycache__), empty
HANDOFF.md, pre-commit secrets grep per AGENTS.md. Nothing else. Ask before first commit.
```

### 5.2 PHASE KICKOFF (template, fresh context)
```
Fresh session. Load: CLAUDE.md, TRADING-RULES.md, HANDOFF.md, PROMPTS.md §4 row for Phase <N>.
Starting Phase <N>: <objective>.
Before any code: (1) run the relevant slice of CODE-RECON.md — map what exists
that Phase <N> touches; (2) state verified topology per AGENTS.md (state,
feedback, blast radius, timing); (3) plan as short prose walkthrough + files to
create/modify; flag assumptions and Medium+ ambiguity per Entry Protocol.
Wait for approval. Phase is done only when VERIFY confirms all §4 exit criteria.
```

### 5.3 MID-SESSION VERIFICATION GATE (before any commit)
```
Stop. Run the AGENTS.md Verification Gate on what you just built, plus: does
anything contradict TRADING-RULES.md? Check §1 laws specifically — ATR/percentile
thresholds not raw percent, complete candles only, both-direction SL/TP tests,
no computed-but-unused indicators.
Report PASS/PARTIAL/FAIL per EXECUTION-MOMENTUM.md. PARTIAL/FAIL: list what
remains, fix, re-verify. No success claims you haven't adversarially tested.
```

### 5.4 SESSION CLOSE-OUT (before every /clear, no exceptions)
```
Ending session. In order:
1. Final Verification Gate on all uncommitted work.
2. Overwrite HANDOFF.md per PROMPTS.md §3 — cold-resumable without asking me anything.
3. If ALL §4 exit criteria pass: tick phase in CLAUDE.md, archive HANDOFF into
   commit message, empty HANDOFF.md.
4. Any feature idea surfaced → ROADMAP.md ## Feature Proposals now.
5. Any wisdom-grade lesson → BRAIN.md ## Wisdom (per its schema).
6. Propose commit message. Ask before committing. Never ship without consent.
```

### 5.5 RESUME INTERRUPTED PHASE (fresh context)
```
Fresh session. Load: CLAUDE.md, TRADING-RULES.md, HANDOFF.md.
Per EXECUTION-MOMENTUM.md: continue, don't restart. Verify HANDOFF's claimed
work is still valid (run the tests it claims pass), state the next action from
"Not done", confirm in one sentence, proceed. Respect every "Do NOT redo".
```

### 5.6 RECON / STUBBORN BUG
```
Fresh session. Load CODE-RECON.md; execute it against this repo, pointed at:
<symptom or subsystem>.
Read-only until the topology report is done. Cross-reference TRADING-RULES §1 —
the prior bot's failure catalog is your suspect checklist. End with ranked
hypotheses + the single cheapest experiment to falsify the top one.
```

### 5.7 STRATEGY CHANGE (any edit to strategies/, regime/, or risk params)
```
Fresh session. Load CLAUDE.md, TRADING-RULES.md, HANDOFF.md.
Proposed change: <describe>. Minimum Medium Ambiguity — never trivial.
Required sequence, no skipping: (1) state the hypothesis this change tests;
(2) confirm blast radius across BOTH backtest and live paths; (3) implement
behind config where possible; (4) rerun unit tests + golden runs + walk-forward
per TRADING-RULES §5; (5) write the revalidation note. If validation regresses:
revert — the old parameters won; result goes to ROADMAP or BRAIN, not main.
```

### 5.8 DASHBOARD-ONLY (Phases 9–10 iterations)
```
Fresh session. Load CLAUDE.md (Dashboard Pages + Journal Models), DEPLOY-PYTHONANYWHERE.md, HANDOFF.md.
Task: <page/feature>. Constraints: dashboard writes ONLY control_flags,
instrument_control, BacktestRun queue — never trading tables. Reuse Laser
Dashboard CRUD/template patterns. No JS frameworks; Chart.js CDN only.
```

## 6. Cadence
One phase per session target; long phases (4/5/8) span sessions via Close-Out→Resume. Every session: kickoff → gate before commits → close-out → commit → `/clear`. Docs written only at close-out (+ ROADMAP capture mid-session) so the phase table stays authoritative. **The user, not Claude Code, ticks Phase 11.**
