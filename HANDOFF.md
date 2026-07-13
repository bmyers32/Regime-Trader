# HANDOFF — 2026-07-12T23:15Z (carry hearing spec-mapping resolved; build starting)
Phase: carry-with-regime-conditioning (§6 slot 2 of 3)   Status: SPEC RESOLVED, PRE-CODE — build not yet run to verdict

Full spec-mapping proposal for slot 2 resolved and approved this session, including
signal-source resolution (the project's first non-OANDA data dependency) and four
user-approved amendments/riders, recorded below in full BEFORE any strategy code
exists, per PROMPTS.md §5.7. Momentum's hearing (slot 1) remains CLOSED/FAILED,
unchanged — see archive/POST-MORTEMS.md §6; nothing here reopens it.

## Signal-source resolution

The project's only existing financing-rate data (`scripts/fetch_financing_rates.py`)
is a single live OANDA snapshot applied as a constant across all history — a
defensible COST model (Wednesday-deferral convergence argument, archive/POST-MORTEMS.md
§6 A5(b)) but a degenerate SIGNAL: a constant differential never changes sign, so the
walk-forward has nothing to select. Resolution: fetch real historical central-bank
policy-rate (or best available proxy) series for all five currencies (USD, EUR, GBP,
JPY, AUD) from FRED (`api.stlouisfed.org`), the project's first non-OANDA external data
source. `requests` is already pinned — no new dependency.

| Currency | Series ID | Native frequency | What it actually is |
|---|---|---|---|
| USD | `DFF` | Daily | Effective Fed Funds Rate — true daily policy-adjacent rate |
| EUR | `ECBDFR` | Daily | ECB Deposit Facility Rate — true daily official policy rate |
| GBP | `IUDSOIA` | Daily | SONIA — proxy; FRED carries no continuously-updated official Bank Rate series |
| JPY | `IRSTCI01JPM156N` | Monthly | OECD-sourced Call Money/Interbank Rate for Japan — proxy (corrected during build: `IRSTCB01JPM156N`, the OECD "Central Bank Rate" code, returned zero live observations despite an active-looking series page; switched to the same `IRSTCI01` interbank-rate family AUD already uses) |
| AUD | `IRSTCI01AUM156N` | Monthly | OECD-sourced interbank/call-money rate — proxy for RBA cash rate |

Verified via WebSearch (FRED's own docs + series pages) that all five series exist and
are live; end-to-end fetch execution (real API key round-trip) has NOT run yet — same
"design now, execute at build time" split every other OANDA fetch in this repo follows.
**Execution note:** user registers `FRED_API_KEY` and attempts the fetch locally first;
if the local network intercepts it (TLS interception on financial-data domains has
bitten this project before — the Norton-antivirus precedent behind the standing
"OANDA fetches run on PA, not locally" rule), the fetcher runs from PA instead. Either
way the resulting snapshot is committed, so this choice doesn't gate anything
downstream.

### Amendment 1 — as-of / no-lookahead convention
Daily series (`DFF`, `ECBDFR`, `IUDSOIA`) apply from their observation date forward —
the observation date IS the effective date, no extra lag. Monthly OECD-proxy series
(JPY, AUD) apply from the **first day of the following month** forward, not their
nominal observation-month date — models OECD MEI's real publication lag. No backfill,
no interpolation either case. One new no-lookahead test required (`tests/test_rates.py`),
mirroring the precedent `RegimeResult.htf_window` set in `tests/test_backtest.py`.

### Amendment 2 — limitation, stated plainly
JPY is simultaneously the thesis's funding leg (both target pairs are JPY-quoted) and
the weakest proxy (monthly, not the BOJ's own published decision) — in the exact window
BOJ moved the most (NIRP exit → 1.0% across 2024-2026). The sign-stability exhibit below
shows this doesn't threaten the SIGN (differentials never approached zero this window),
but a future magnitude-based variant would need to revisit the source before it could be
trusted.

### Amendment 3 — pinned snapshot is TRACKED, not gitignored
(Correction from an internal contradiction in the first draft of this proposal, caught
in review before approval.) Candle history lives under `instance/` deliberately
gitignored — large, per-machine, PA-fetch-only, nothing anyone needs to audit later. A
hearing's rate evidence is the opposite: small, holds no secrets (historical percentage
rates only), must be reproducible on a fresh clone without re-hitting an external API or
trusting whichever machine fetched it. Fetched data is therefore committed as parquet
under a **new top-level `calibration/rates/` directory**, tracked in git, with a
fetch-date stamp — not under `instance/`. Gates run off that frozen, committed snapshot,
not a live re-fetch each run. The fetcher (`scripts/fetch_policy_rates.py`) stays
rerunnable on demand (e.g. a future §6 renewal re-pins a fresh snapshot), but
re-running it is a deliberate, committed act, not an automatic refresh. `FRED_API_KEY`
goes in `.env`/`.env.example`/`config.py`, same pattern every existing secret uses.

### Amendment 4 — sign-stability exhibit required before finalizing pairs/spec
Done below (research-derived first pass); a real-data recompute + HALT-check against it
is a required build step (see "Not done / next action" below) BEFORE any strategy code
is written.

## Sign-stability exhibit (PROVISIONAL — research-derived, not yet FRED-API-derived)

**Not the hearing's evidence of record.** Built from WebSearch summaries of real
central-bank decision coverage (Fed, ECB, BoE, BOJ, RBA), 2024-2026, current as of
2026-07-12 — a reasonable basis to decide which pairs are worth targeting, not a
substitute for the real pinned dataset. **Must be recomputed from the real fetched
`calibration/rates/` snapshot before any strategy code is built or any gate runs; any
disagreement on sign or static/dynamic classification for any pair HALTS for review.**
Pre-framed exception, NOT a halt trigger: amendment 1's monthly-proxy convention will
shift JPY/AUD's exact checkpoint values by up to ~a month vs. this table's
announcement-dated numbers — expected, not a discrepancy.

| Pair | Differential (base − quote) sign across 2024-2026 | Verdict |
|---|---|---|
| **USD_JPY** | +5.3% (mid-2024) → +2.6% (now) — never crosses zero | STATIC POSITIVE |
| **GBP_JPY** | +5.15% (mid-2024) → +2.75% (now) — never crosses zero | STATIC POSITIVE |
| EUR_USD | −1.4% to −2.4%, always negative | STATIC NEGATIVE |
| EUR_GBP | −1.25% to −2.25%, always negative | STATIC NEGATIVE |
| GBP_USD | −0.13%→+0.13%→−0.38%→+0.13% (mid-2024→now) | DYNAMIC — flips repeatedly |
| AUD_USD | −1.0%→≈0%→+0.73% (mid-2024→now, RBA's 2026 hiking reversal) | DYNAMIC — crosses once |

(Rate paths: Fed 5.375%→4.375%→3.625%; ECB 4.0%→3.0%→2.0%→2.25%; BoE
5.25%→4.50%→3.75%; BOJ 0%→0.25%→0.5%→0.75%→1.0%; RBA 4.35%→4.10%→3.60%→4.35%.)

Confirms the pairs decision's premise: USD_JPY/GBP_JPY are both static-sign for this
whole window — this hearing, as scoped, tests a **regime-conditioned static short-JPY
position**, not a dynamically-switching signal. AUD_USD (single crossover) and GBP_USD
(multiple flips — the most dynamic pair in the whole config, new information beyond
what was anticipated) are the pairs that would actually exercise signal *dynamics* —
both recorded as lawful §6-renewal candidates, not run this hearing.

## Spec-mapping (6 items, all resolved)

**C.1 Signal:** `direction="long"` if `rate[base]>rate[quote]` as of the current D-bar,
`"short"` if reversed, `None` on exact tie (momentum's own tie-case precedent). **No
minimum-differential threshold in the IS-search grid** — both target pairs' differentials
sit at 2.6-5.3 points all window, so a `{0,25bp,50bp}` floor would be structurally inert;
fixed at 0.0 (pure sign), not searched. Net effect: zero free *signal* parameters this
hearing, only the same execution parameters (`sl_atr_mult`, trail) every playbook already
searches. **Gate 4 scope caveat (binding on the eventual report):** because no signal
parameter exists to sweep, gate 4 here measures exit-parameter stability only — a PASS
must not be read as "the signal is robust" the way it was for momentum (where gate 4
caught N itself as the fragile dimension).

**C.2 Regime-conditioning (INTRINSIC — this hearing's own centerpiece), RESOLVED
suspend-only:** EXPANSION on the D-anchor blocks new entries only — journaled as a veto
(`vetoes=["expansion_regime"]`), reusing range_reversion's exact convention. Open
positions unaffected; normal SL/trail continues. Force-flatten was rejected: the
classifier needs 2 confirmed D-closes to enter EXPANSION, so a flatten would land ~2
days into a real vol event, after the ATR trail/SL already reacted — buying new engine
surface (none exists for mid-hold consult-and-flatten) for an exit that fires *later*
than exits already in place. Crash protection = sizing + trail; this gate's job is
refusing to *initiate*, which suspend-only does with zero new engine surface. D-anchor
EXPANSION is the right instrument: bypasses `regime_min_hold_bars` on entry (fast in),
`regime_confirm_bars=2` prevents 1-bar noise suspending a weeks-long hold, reuses the D1
classifier instance momentum already exercises.
Three riders: (1) pre-registered diagnostic — every losing stitched-OOS trade records
whether EXPANSION was ever confirmed during the hold; concentration there scopes any
FAIL to "under entries-only conditioning" and names mid-hold forced flatten as the
revival mechanism (not built this hearing). (2) hysteresis-lag rationale goes in
`carry.py`'s own docstring. (3) §1.7 pass-rate exhibit, binding: EXPANSION-vetoed bars
as share of would-be-eligible entries per pair — near-zero rate stated as decorative in
the verdict, not just reported.

**C.3 Gate/score structure:** (1) `regime.htf_window is not None` bootstrap; (2)
rate-history warmup both currencies; (3) EXPANSION veto (journaled); (4) tie check
(`None`). Spread/blackout are engine-level, not reimplemented. `confidence_score` fixed
1.0, signal-only §1.1 exemption.

**C.4 Exit:** same ATR/Chandelier trail (partial-at-1R + trail remainder) every
playbook uses, as-is — no new engine surface, directly inheriting slot 1's A3/A7 null
result on signal-flip exit as a revival mechanism. The new diagnostic this hearing adds
(C.2 rider 1) is about regime-driven exit timing, a different question than A3/A7
already closed.

**C.5 Pairs, RESOLVED USD_JPY + GBP_JPY:** both static-sign, JPY-funded ("carry's home
terrain"), reuse momentum's exact D1/H4 cache + cost_model + gate-script wiring.
**Honesty statement:** tests a regime-conditioned *static* short-JPY position, not a
dynamically-switching signal — IS/walk-forward exercises exit/stability params only.
**Correlation honesty, pre-registered verdict-combination reading** (both pairs
short-JPY, substantially one macro bet per §4.2): both FAIL → carry closed at home
terrain; both PASS → one strong JPY-carry result, not two independent confirmations;
split → informative divergence to diagnose, not narrate as "one pass is enough."

**C.6 Rollover interaction, checked against real numbers, reconciles cleanly:** signal
uses time-varying historical FRED differentials; engine cost uses a constant present-day
OANDA snapshot — explicitly NOT the same convention, stated not reconciled (rebuilding
`fetch_financing_rates.py` into a time series is a separate, larger scope — a ROADMAP
item if this hearing passes). **Sanity anchor:** slot 1 measured a net rollover CREDIT
on GBP_JPY (`rollover_cost=+55.47`). Current `cost_model.rollover_pips_per_day`:
GBP_JPY long=+1.063 (credit)/short=−2.316; USD_JPY long=+0.803 (credit)/short=−1.712.
Both pairs' carry signal says long throughout; both pairs' OANDA convention credits the
long side — reconciles cleanly, evidence the signal's economic logic and the engine's
cost model aren't fighting each other despite different snapshots in time.
**Direction of the divergence, named explicitly:** both target pairs' differentials
*narrowed* over the window (USD_JPY ~5.3%→~2.6%, GBP_JPY ~5.15%→~2.75%) as Fed cut and
BOJ hiked. The OANDA snapshot reflects today's narrower gap applied as a constant, so
early-window long trades — when true historical carry was roughly double today's — are
UNDER-credited relative to reality. The cost model is conservative for this thesis, not
generous. **A PASS survives this bias; a FAIL cannot be waved off as a rollover-model
artifact** — if anything the model understates this thesis's own tailwind.

## Pre-registrations (binding once code exists)
1. No-lookahead test for the rate cache (`tests/test_rates.py`).
2. EXPANSION-during-hold loss split (C.2 rider 1) — names mid-hold flatten as revival
   target if losses concentrate there.
3. EXPANSION-veto pass-rate exhibit (C.2 rider 3), binding §1.7 note.
4. Verdict-combination reading across the two short-JPY pairs (C.5).
5. Standard exhibits from slot 1's precedent: funnel, gross-vs-net, per-regime
   attribution, duty-cycle + rollover-share (primary for this thesis, not just context).

## Not done / next action
Build not started. In order: (1) `bot/data/rates.py` (`PolicyRateCache` +
`rate_asof(currency, date)` via `merge_asof(direction='backward')`, same idiom
`trend_pullback.py` uses for its own HTF-alignment merge) + `scripts/fetch_policy_rates.py`
(FRED fetcher, sibling to `fetch_financing_rates.py`/`fetch_history.py`) +
`FRED_API_KEY` in `config.py`/`.env.example`. (2) Run the fetcher, pin output to
`calibration/rates/` (committed). (3) **Recompute the sign-stability table above from
the real pinned data — HALT for review on any sign or static/dynamic disagreement**
(an M+1 date shift on JPY/AUD checkpoints is expected, not a halt). (4) Build
`bot/strategies/carry.py` (mirrors `momentum.py`'s shape) + `carry_params`/
`carry_calibration` in `instruments.yaml`. (5) `tests/test_rates.py`,
`tests/test_carry.py` — no-lookahead test, structure tests both directions,
EXPANSION-veto journaling test. (6) Register `carry` in
`scripts/{run_validation_gates,diagnose_gates,gross_vs_net}.py` (reuse momentum's D/H4
TF-pair generalization); add the EXPANSION-during-hold diagnostic + veto-rate exhibit.
(7) Run TRADING-RULES §5 gates 3/4/6 on USD_JPY and GBP_JPY, render every
pre-registered exhibit, verdict. (8) Close out: TRADING-RULES §6 slot-2-spent entry,
ROADMAP Closed Dispositions pointer, archive/POST-MORTEMS.md full writeup, HANDOFF
rewrite for next session.

Slot 3 (failed-breakout re-entry, continuation direction) remains unstarted after this
— unchanged from before this session, cached H1 only, no new fetch needed, must specify
the CONTINUATION thesis per the census correction (archive/CENSUS-PIVOT-CYCLE.md).

## Open tensions
TRADING-RULES §6's budget: 1 of 3 spent (momentum, FAILED), slot 2 (this) spec-resolved
but not yet run, slot 3 unstarted. Do not reopen trend_pullback, range_reversion,
squeeze_breakout, or the momentum hearing — all closed permanently. Do not retry
momentum on a different anchor TF (amendment A4 from that hearing, still binding).
GBP_USD and AUD_USD are recorded lawful §6-renewal candidates (dynamic differentials)
but are NOT licensed to run under this hearing's slot — a future renewal, not this one.

## Files touched this session so far
`HANDOFF.md` (this rewrite, full spec-mapping + 4 amendments recorded pre-code). No
code changed yet — build starts next.

## Do NOT redo
The signal-source research and sign-stability exhibit above are the settled proposal —
do not re-litigate FRED vs. mixed-source, or re-argue the EXPANSION-gate design
(suspend-only vs. suspend+flatten), or re-argue the pairs choice (USD_JPY+GBP_JPY vs.
AUD_USD/GBP_USD) — all three were explicitly decided by the user this session with
recorded riders. The provisional sign-stability table IS allowed to be superseded by
the real-data recompute (that's the point of amendment 4) — but only on sign/
classification grounds, not re-litigated wholesale.
