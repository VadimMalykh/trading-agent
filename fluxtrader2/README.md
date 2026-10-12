# fluxtrader2 — a from-scratch trading system built on the same data

**Started 2026-09-15.** A parallel project inside this repository. It shares the data the
always-on collector (`fluxtrader-1`) has gathered since 2022 and **nothing else**: no model,
no feature code, no policy, no conclusion from the first project is imported or assumed. The
goal is the same as the first project's — a system that generates profitable trades — but the
path is chosen from measurements made here, not inherited.

**Entry point for a fresh session: this file, then [docs/PLAN.md](./docs/PLAN.md).** The
first project's entry point (`docs/BACKLOG.md` at the repo root) has one row pointing here and
otherwise knows nothing about this folder.

## Status

| date | where we are | needed from Vadim |
|---|---|---|
| 2026-10-12 (last) | **fluxtrader2: R36 READ — the slow book on the 188 screener members: 0 of 4 clear, the lean ABSENT, and the book-imbalance line is CLOSED at every horizon and universe in hand.** The 158 members' books were fetched (0 failed files; 122 list inside the window), 30 reused, the 44 files in hand unchanged by md5; validity PASS (188 names, 485 whole days, 410 shifts, the frames and the harness's unit to 0.0, funding on every cell). On the members the slow level reads +19 bps a leg at 7 days — the OPPOSITE sign, u 0.5, p 0.78 — and +7 at 3 days; the raw +1 (CLOSED) and −2. The lean lives on the 30 members that are in R10's forty (−69 a leg at 7 days, the same cells R35 read) and is not there on the other 158 (+10): a property of large, old names, absent on the younger, thinner names a screener picks from. The power paragraph's assumption failed — the se did not fall with the names (34 against 36), because the members move 1.3× as much and carry the young-name tail (every tenth's median sits 1.5–2 % a week under its peers' mean). One deviation of the record: the first run carried R35's cost 15 and label; the read step was made again at the registered 25, the numbers identical. Nothing in money; R37 does not exist. The members' book stays as data in hand. Work VM stopped.** | **fluxtrader2 needs from Vadim: P8 decision M (PLAN P8 decision M) — the book line is closed; recommended (M1) the forced-flow signature at 1–4h per name with breadth (H3: open interest falling + a far move + an extreme taker ratio → a reversal; metrics on 199 names in hand, a day, no fetch, confirmable on F3+F4); (M2) the premium around the funding settlement (H4); (M3) the size signal as a described row, nothing to run; (M4) seasonality / the carry; (M5) P7 alone.** |
| 2026-10-12 (latest) | **fluxtrader2: P8 decision L decided ("L1") and R36 REGISTERED (PLAN §8) before any member's depth file was fetched — R35's read, unchanged in frame, family, null and gate, on the 188 screener members' book (R18's universe: 158 names fetched for 2023-04 → 2024-08, 30 reused from R34; ≈ 62 GB of the VM's 138 GB free, measured after R34), cost 25 bps a leg fixed from the members' proxy round trip; the power written first (7-day MDE ≈ 50: a true −56 found two times in three, a true −30 one time in four); a winsorised M and the by-tenth medians beside the mean for the young-name tail; a clear licenses one registration (R37, the smallest priced book on the members), nothing in money here. Next: the universe in the module and its test (commit), the chain on the VM (fetch ≈ 2 h, ingest ≈ 1 h, the read), the read.** | **fluxtrader2 needs from Vadim: nothing until R36 is read.** |
| 2026-10-12 (late) | **fluxtrader2: R35 READ — the slow book at 3 and 7 days: 0 of 4 clear, every row NOT DETECTABLE; the imbalance question is closed at every horizon in hand.** Validity PASS (43 names, 485 whole days, 410 shifts, the frames and the harness's unit to 0.0, funding on every cell, the depth files unchanged by md5). On the 43 names' F1+F2, the names whose ±1 % book has been bid-heavy for a month do worse over the next week by 56 bps a leg beyond their own drift (m_c at 7 days; −28 at 3 days; the raw −29 / −16) — every row the registered sign, the same sign in F1 and F2, earned after the first day — and the noise is twice the expectation: se 36 at 7 days (u −1.6, MDE 100, seven times the cost of 15), u −1.99 at 3 days against the bar of 2, the raw's 3-day p_family 0.051 against 0.05. Two rows at the bar's edge, none over it; the gate as written passes neither. What the numbers add: the shifts' centres are large (−32 at 7 days: the persistently bid-heavy names drift down over these months — a lasting link the null removes and a rank IC's t does not), the by-tenth medians fall cleanly from the ask-heaviest to the bid-heaviest tenth (−44 → −157 bps) under jumpy means, the 32 carry more than the eleven, the within-month part is nothing at every hold. PARKED as "real at one day, not shown to pay at a week on 43 names": the sample's power, not the sign, fails it — a true −56 needs about four times the names to be found one time in two. Nothing in money; R36 does not exist. Work VM stopped.** | **fluxtrader2 needs from Vadim: P8 decision L (PLAN P8 decision L) — recommended (L1) the same read on the 188 screener members' book (≈ 45 GB, a day or two of fetch; the 7-day MDE falls to ≈ 50 against −56); (L2) the forced-flow signature (H3), no fetch; (L3) the settlement premium (H4); (L4) F3+F4 of the 43 for the slow book — not before L1; (L5) P7 alone.** |
| 2026-10-12 (night) | **fluxtrader2: P8 decision K decided ("go with K1") and R35 REGISTERED (PLAN §8) before any code was written — the slow book at a longer hold: the month's mean of the ±1 % imbalance (found twice at one day, −0.055 on both universes) and the raw imbalance as a family of two, at 3- and 7-day holds in R22's frame (the mean label-against-peers of the top tenth minus the bottom tenth, halved, bps a leg, actual returns with funding inside; every admissible whole-day shift as the null, 410 of them) on the 43 names' F1+F2 hourly cells; cost 15 bps a leg fixed; the sign registered negative; a clear licenses one registration (R36, the smallest priced book at that hold), nothing in money here. Expectation: 3 days NOT DETECTABLE, 7 days a coin flip. Next: `horizon --book` and its tests (commit), the run on the work VM, the read.** | **fluxtrader2 needs from Vadim: nothing until R35 is read.** |
| 2026-10-12 (evening) | **fluxtrader2: R34 READ — the breadth step is NOT DETECTABLE by its gate, and the book-imbalance question (§7 (b), open since 2026-09-22) is CLOSED.** The 32 outside names' books (2023-04 → 2024-08, 7.5 GB zipped, 0 failed files, the twelve's files untouched by md5) were fetched, ingested and screened the same day; validity PASS to 0.0 (R33's 36 rows reproduced in the same run). On the 32 the demeaned imbalance at one day reads IC −0.013 (t −1.7, se 0.0075), both folds negative, above the 0.0106 bar in size, but p_family 0.22 on the larger of two nulls — half the twelve's −0.022 and inside noise. What did replicate: the RAW imbalance's one-day lean (−0.036, t −3.3, p 0.015 — P2's row found a second time on names its screen never saw), carried on these names by the SLOW part (−0.056, p 0.025) — the opposite split from the twelve. So the lean is a property of these perpetuals' books, but the part a daily rule could trade did not travel, and the part that did is what R9 and R11 already failed to turn into money at a daily round trip. The size signal replicates whole (the demeaned book predicts the next move's size at every horizon, t 5–20 on 43 names) — a sizing fact for any future rule, no instrument of its own. Nothing in money; R35 not licensed; the 32's book stays as data in hand (DATA.md). Pooled 43 names (described, `output/ceiling_depth_both.md`): the demeaned part −0.015 (t −2.2, p_family 0.080), under the gate on the pooled cells too; the raw −0.037 (p 0.01) and the slow part −0.056 hold; the size signal t 20. P7 runs by itself (last health 2026-10-05 green). Work VM stopped.** | **fluxtrader2 needs from Vadim: the next pick, P8 decision K (PLAN P8 decision K) — the screener phase is out of registered candidates again; the list and a recommendation are in the handoff.** |
| 2026-10-12 (later) | **fluxtrader2: P8 decision J decided ("let's go with J1") and R34 REGISTERED (PLAN §8) before any file was fetched — the breadth step: the demeaned ±1 % imbalance screen of R33, unchanged, on the 32 names of R10's forty that the collector never recorded, over the same months (F1+F2), their archive book 2023-04-01 → 2024-08-31 fetched under it (≈ 18 GB of the work VM's 151 GB free, measured first); the gate R33's with the size bar fixed at R33's 0.0106 (the 32 have a taker proxy of about 15 bps a round trip and no maker measurement); validity = R33's twelve-name rows reproduced in the same run, raw = lvl30 + dm, the twelve's depth files unchanged by md5. A clear licenses one registration, R35 (a priced per-name rule, confirmed on F3+F4); a miss parks the twelve's lean as the twelve's. Expectation: a clear somewhat likelier than not, under the 32's own taker bar. Next: the module's universe path and its tests (commit), then the chain on the VM (fetch ≈ 1 h, ingest, the screen), then the read.** | **fluxtrader2 needs from Vadim: nothing until R34 is read.** |
| 2026-10-12 | **fluxtrader2: P8 decision H decided ("let's go as recommended"), two registrations written, built, tested, run on the work VM and read the same day, each step its own commit (PLAN §8 R32, R33). R32 `trend1d` — the basket's 30-day sign (R6's one-day row, IC +0.070, five of five years, never acted on) traded on every pair for a day — FAILED its stage-1 gate on the per-year condition: taker net +10.7 bps a trade [−11.0, +32.3] on 14,672 trades / 1,578 days, both nulls p ≤ 0.025, but 2020 −7.1, 2022 −14.5 and 2024 −21.4 against a bar of −5. All the money is the long side (+35.5 [+4.9, +66.1]): after an up-month the basket rose +56 bps a day, after a down-month +4, so the short side has no gross and pays the round trip; the long side itself is −63 in 2022 — R8's shape. Held until the sign flips the costs fall from 12.7 to 0.9 a trade and the net is +22: the years fail it, not the costs. PARKED, no variant, decision I not opened, F3+F4 never read (as registered). R33 — the ±1 % book imbalance demeaned by the pair's trailing month, a ceiling screen on P2's cells (F1+F2, eleven names) — validity PASS to 0.0 (P2's raw row and its 200-draw null reproduced exactly), and the demeaned feature CLEARS at one day: IC −0.022 (t −3.3, se 0.007), p 0.005 on BOTH nulls (day shuffles and whole-day shifts), F1 −0.025 / F2 −0.020, above the maker bar 0.0106 and the taker bar 0.0182. The within-month part is 80–100 % of the imbalance's variance and carries more than half of P2's −0.039: R9's reading of 2026-09-22 ("the IC lives in the slow level") was wrong. A hypothesis on seen cells, nothing in money; reported beside: the same feature predicts the SIZE of the next move strongly (vol IC +0.05 at 15m, t 18). The paper test (P7) runs by itself; last health 2026-10-05 green. Work VM stopped.** The rest of the status (P7, the earlier screener reads, data in hand) is the 2026-10-09 row below. | **fluxtrader2 needs from Vadim: P8 decision J — the breadth step after R33's clear (PLAN P8 decision J): recommended (J1) the archive's depth for the forty of R10 (32 outside names, ≈ 8 GB zipped, a day), the same screen on their exploration cells, a priced rule only on a clear there and confirmed on F3+F4; (J2) the 188 screener members (≈ 45 GB, days, disk may need to grow); (J3) price the rule on the twelve now — forbidden by R33's gate, not recommended; (J4) P7 alone.** Decision H decided 2026-10-12 → R32 (failed, parked), R33 (clears). Decision G 2026-10-09 "G1"; F revised the same day → R31. |
| 2026-10-09 | **fluxtrader2: the paper test running (green 2026-10-05); the screener phase's last item in hand, R31 (Vadim's F5, registered, built, tested and read stage 1 the same day): the US index's last hour traded at its sign on the whole basket as a maker, when the hour's move is at least one of the index's own hourly sigmas, held four hours, with a 15-minute serving lag. Stage 1 on the seen bars (2020-05 → 2024-08) PASSED the gate as written — maker net +2.05 bps a trade [−6.24, +10.34], both nulls p 0.010, no calendar year under −5 — and says what R30 said in money: the gross is real (+6 … +9 bps a trade, every year), the costs take it back, the net is about zero; the long side nets +8 [−3, +18] and carries the basket's drift, the short side −4; the lag and a tighter threshold change nothing the sample can see. F5's premise as written on 2026-10-08 was corrected in the block before any number: the 4h bar R30 missed was already the maker bar, so the room was a threshold, not a price. Stage 2 (F3+F4, the only confirmation cells no market-wide question has read) is P8 decision G, DECIDED 2026-10-09 (Vadim's "G1"): NOT RUN — with the measured noise it could confirm a true +2 about one time in twenty-five; R31 parked, F3+F4 unspent for the market factor. Not shown to trade profitably yet.** **(1) P7 — paper trading of R14, LIVE since 2026-09-25 17:00 UTC on `fluxtrader2-serve`.** R14 is a simple model on price-bar features that forecasts a pair's next-day move against the other pairs; on data nobody had looked at (R16) it earned +33 USDT a trade on 10,000 after costs, 3.6 trades a day, and failed one of five criteria — the one that sample could not pass. Vadim funded the paper test by override. Health 2026-10-05 02:05 UTC: green (2,712 decisions, 40 taken, 3 open, 0 late, 0 missing bars, model `model_2026-09-30`); the first refit on the host PASSED (2026-09-30); the first monthly identity check (2026-10-01) PASSED (`checks/check_2026-10-01.md`). Claude reads `vm.sh serve-status` monthly, next on or after 2026-11-01 01:30 UTC. The money is read once (R17): at ≥ 600 trades and ≥ 6 months, earliest 2027-03-25. **(2) P8 — the screener: fourteen reads, nothing clears its costs** (PLAN P8 and §8): the twelve's model carries nothing to outside names (R18, R19); the exchange's own numbers per name — funding, premium, open interest, long/short, taker flow — nothing at one day (R20, R21) and nothing at 3 and 7 days once counted in actual returns (R22–R25, re-executed 2026-09-30); the US index (R26) and the ETF flows (R27) nothing per name; a new perpetual sold at launch and held a week (R28) did not confirm on F3+F4 (R29, −176 USDT a trade); the index and the flows as market direction (R30) closed by cost; the index's last hour as a maker-priced basket rule (R31) +2 bps a trade net on seen bars, inside its noise. Parked rows and their revival triggers: PLAN §7. **(3) Data in hand, all audited:** the archive's depth, metrics, funding and tape summaries; 40 wide-universe pairs; the premium index; US500/US100 one-minute bars 2020 → 2026-09; Farside ETF flows; DefiLlama unlock snapshots; Binance announcements. | **fluxtrader2 needs from Vadim: P8 decision H — the brainstorm's pick (PLAN P8 decision H): recommended (H1) the basket's 30-day trend at a one-day horizon (R6's own 1d row, IC +0.070, 5 of 5 years, never acted on) and (H2) the demeaned ±1 % book imbalance at 1d as a ceiling screen, registered together on seen bars; (H3) the forced-flow signature at 1–4h, (H4) the funding-settlement premium, (H5) seasonality, (H6) the carry.** Decision G decided 2026-10-09, "G1": R31's stage 2 not run, R31 parked with F3+F4 unspent. Earlier the same day: decision F revised, "let's go with F5" → R31. 2026-10-08, "1": R30 (read). 2026-10-05, "D1 a": R29 (read, parked); "C1": R28. 2026-09-30, "(A1) (B1)": R23's second stage not run, the outside-names search parked. |

### Handoff — where the next session starts (written 2026-10-12, after R34 was read; rewritten, not appended to, at each handoff)

Everything up to here is committed. The work VM (`fluxtrader2-work`) is stopped; the
serve host (`fluxtrader2-serve`) runs P7 by itself (health 2026-10-05 02:05 UTC: green — 2,712 decisions, 40 taken, 3 open, 0 late,
0 missing bars, `check True`, `err None`, model `model_2026-09-30`).

**One question is open — P8 decision M, the next question after the book line closed (PLAN P8 decision M; recommended M1: the
forced-flow signature at 1–4h per name with breadth, a new mechanism on data in hand, a day, no fetch).** Today's six reads, each
registered before it ran and committed as it was read: R32 (`trend1d`) PARKED — the years fail it, not the costs; R33 CLEARS on the
twelve (the within-month imbalance at one day); R34, its breadth step on 32 fresh names, NOT DETECTABLE while the RAW imbalance
replicates through its SLOW part — §7 (b) closed; R35, the slow book at 3 and 7 days on the 43, NOT DETECTABLE on every row with the
registered sign on every row (−56 a leg at 7 days, MDE 100); R36, the same on the 188 screener members, the lean ABSENT (+19, the
opposite sign; present on the 30 large names inside, −69; absent on the 158) — the book-imbalance line is CLOSED at every horizon and
universe in hand. The mode: measure, with P7's clock running in the background — the wait forbids only touching R14 or the serve path.

In this order:

1. **Decision M.** On M1, a NEW ceiling registration (§8 R37) in R20's frame: the three ingredients defined exactly (the hour's OI change
   from `metrics`, the hour's |move| in its own sigmas, the hour's taker ratio), the interaction and its single parts as the family,
   horizons 1h and 4h, the universe (the twelve and the members, metrics in hand), both nulls, the money view in actual returns on the
   extreme tenth, the gate (p_family ≤ 0.05, both folds, the bar) and what a clear licenses (a priced rule, then F3+F4 — the members'
   metrics for F3+F4 are in hand from R25); commit; run on the work VM; read; commit. On M2 the same shape on the premium index.
2. **P7.** Claude runs `./fluxtrader2/scripts/vm.sh serve-status` once a month, next on or after 2026-11-01 01:30 UTC:
   `check True`, `err None`, `late 0`, `missing24h 0`, model age < 30 d. The money is read once (R17), earliest 2027-03-25.
3. **A thing to carry into any next book rule** (R33, R34): the imbalance's one-day lean is found twice (eleven names, then 32) but the part that travels is the SLOW one; the demeaned book is a strong SIZE signal on all 43 (vol IC
   +0.05 at 15m, +0.03 at 1d, every month the same sign) — a sizing row for any rule that trades it; and R9's lesson stands beside
   the clear: a screen IC on the twelve did not turn into money at the top decile, so the rule's side, decile and price are
   chosen only after the breadth read, never from these cells.
4. **A thing to carry into any next basket rule** (R32, R31): a month's trend says when the basket rises, not when it falls; a
   long-only basket rule is R8's shape and 2022 refutes it on the bars in hand; the harness's nulls sit at the COST, so a p of 0.01
   certifies the gross, not the net; state the power from baskets a day, not trades a day.
5. **Operational** — `vm.sh bgsh` starts the job and then keeps the local ssh attached for minutes: run it in the background or
   with a short timeout and check `output/logs/<name>.log` on the VM; `scripts/r32_r33_chain.sh` is the pattern for a serial chain
   with done-markers.
6. **A thing to carry into any next idea on young names** (R21–R25, R28–R29): the typical case and the mean part ways there —
   register the statistic that a real position earns (the mean, in actual returns, with the tail in it), expect the share of
   names that explode to differ between periods, and do not read a stop as a cure.
7. **A thing to carry into any next ceiling audit** (R30): a planted test on made-up bars is run BEFORE the real bars and can
   amend a registration; a feature with a time-of-day pattern gets a hard null from whole-day shifts, which keep the time of day.

Where the outputs are (pulled, not in git): R32 — `output/backtest/trend1d/` (`report.md`, `results.parquet`, `decisions.parquet`, the three
`fills_*.parquet`, `null.parquet`, `meta.json`), the log `output/logs/r32.log`, the per-year and described tables by `scripts/r32_read.py`; R33 —
`output/ceiling_depth.md`, `output/ceiling_depth/` (`validity.json`, `screen.parquet`, `ic_daily.parquet`, `null_shuffle.parquet`, `null_shift.parquet`,
`move_vs_cost.parquet`, `variance_share.parquet`), the log `output/logs/r33.log`; R31 — `output/backtest/ixhour4h/` (`report.md`, `results.parquet`, `decisions.parquet`,
`fills_taker.parquet`, `fills_maker.parquet`, `null.parquet`, `meta.json`), the described rows `output/backtest/r31_lag0/`,
`r31_lag12/`, `r31_theta2/` (F1+F2 only), the log `output/logs/r31.log`; R30 — `output/market_index.md`, `output/market_index/`,
`output/market_etf.md`, `output/market_etf/`.

## The boundary with the first project

- **Data only.** Raw tables exported from the VM (candles, book snapshots, ladder, tape, funding,
  open interest, long/short ratios). See [docs/DATA.md](./docs/DATA.md).
- **No code imports** from `ml/train/` or `apps/`. If something there is genuinely reusable it is
  re-derived here, with its own test, so that this project's numbers have no hidden dependency.
- **Own exporter** (`scripts/export.sh`) reads the VM's raw tables into `fluxtrader2/data/raw/`.
- **No results, plans, protocols or conclusions of the first project are read or referenced.**
  This project knows the data and the goal, nothing else. Every number it acts on is measured
  here under its own protocol (PLAN §3).

## Layout

```
fluxtrader2/
  README.md          entry point and status (this file)
  docs/PLAN.md       the plan: principles, phases, decision table, protocol
  docs/DATA.md       what data exists, where it comes from, known defects
  Dockerfile         CPU analysis image for LOCAL use only
  requirements.txt   shared by the Docker image and the VM venv
  scripts/vm.sh      the work VM: create/setup/start/stop, push code, run jobs, pull results
  scripts/vm_setup.sh installs the VM (venv + deps); idempotent; the reinstall runbook
  scripts/export.sh  export raw tables from the collector's DB into data/raw/ (run on the work VM)
  scripts/ft2.sh     run any ft2 command in Docker locally — the only local way
  ft2/               the Python package (grows with the phases)
  tests/             pytest on synthetic data — `scripts/ft2.sh --test` (Docker, no VM needed)
  data/              exported slices, gitignored
  output/            results, gitignored
```

## Running

**Primary: the dedicated work VM `fluxtrader2-work`** (decided 2026-09-15: the MacBook is short on
disk, its CPU is shared, and a VPN toggle can kill a long download). Data lives there, every
CPU job runs there, and the VM is stopped when idle. No Docker on the VM; a plain virtualenv,
installed by `scripts/vm_setup.sh` (which is also the reinstall runbook).

```sh
./fluxtrader2/scripts/vm.sh start                 # Claude starts/stops it around work
./fluxtrader2/scripts/vm.sh run inventory         # push code, run `python -m ft2 inventory` there
./fluxtrader2/scripts/vm.sh bg p0 ingest          # long job, detached, log in output/logs/p0.log
./fluxtrader2/scripts/vm.sh pull                  # bring output/ (results, reports) back
./fluxtrader2/scripts/vm.sh stop
```

**Local (only for quick checks): Docker, never a host install** (repo rule, `AGENTS.md`):

```sh
./fluxtrader2/scripts/ft2.sh smoke          # builds the image on first use, prints versions
./fluxtrader2/scripts/ft2.sh --test         # unit tests on synthetic data (run before any VM job that uses new code)
./fluxtrader2/scripts/ft2.sh --shell        # interactive shell in the image
```

Compute for this project is **CPU only** for the foreseeable future; the plan's first months
are measurement, not model fitting (PLAN §6).
