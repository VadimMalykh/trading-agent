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
| 2026-10-12 (evening) | **fluxtrader2: R34 READ — the breadth step is NOT DETECTABLE by its gate, and the book-imbalance question (§7 (b), open since 2026-09-22) is CLOSED.** The 32 outside names' books (2023-04 → 2024-08, 7.5 GB zipped, 0 failed files, the twelve's files untouched by md5) were fetched, ingested and screened the same day; validity PASS to 0.0 (R33's 36 rows reproduced in the same run). On the 32 the demeaned imbalance at one day reads IC −0.013 (t −1.7, se 0.0075), both folds negative, above the 0.0106 bar in size, but p_family 0.22 on the larger of two nulls — half the twelve's −0.022 and inside noise. What did replicate: the RAW imbalance's one-day lean (−0.036, t −3.3, p 0.015 — P2's row found a second time on names its screen never saw), carried on these names by the SLOW part (−0.056, p 0.025) — the opposite split from the twelve. So the lean is a property of these perpetuals' books, but the part a daily rule could trade did not travel, and the part that did is what R9 and R11 already failed to turn into money at a daily round trip. The size signal replicates whole (the demeaned book predicts the next move's size at every horizon, t 5–20 on 43 names) — a sizing fact for any future rule, no instrument of its own. Nothing in money; R35 not licensed; the 32's book stays as data in hand (DATA.md). Pooled 43 names: a described run, `output/ceiling_depth_both.md`, in flight. P7 runs by itself (last health 2026-10-05 green).** | **fluxtrader2 needs from Vadim: the next pick, P8 decision K (PLAN P8 decision K) — the screener phase is out of registered candidates again; the list and a recommendation are in the handoff.** |
| 2026-10-12 (later) | **fluxtrader2: P8 decision J decided ("let's go with J1") and R34 REGISTERED (PLAN §8) before any file was fetched — the breadth step: the demeaned ±1 % imbalance screen of R33, unchanged, on the 32 names of R10's forty that the collector never recorded, over the same months (F1+F2), their archive book 2023-04-01 → 2024-08-31 fetched under it (≈ 18 GB of the work VM's 151 GB free, measured first); the gate R33's with the size bar fixed at R33's 0.0106 (the 32 have a taker proxy of about 15 bps a round trip and no maker measurement); validity = R33's twelve-name rows reproduced in the same run, raw = lvl30 + dm, the twelve's depth files unchanged by md5. A clear licenses one registration, R35 (a priced per-name rule, confirmed on F3+F4); a miss parks the twelve's lean as the twelve's. Expectation: a clear somewhat likelier than not, under the 32's own taker bar. Next: the module's universe path and its tests (commit), then the chain on the VM (fetch ≈ 1 h, ingest, the screen), then the read.** | **fluxtrader2 needs from Vadim: nothing until R34 is read.** |
| 2026-10-12 | **fluxtrader2: P8 decision H decided ("let's go as recommended"), two registrations written, built, tested, run on the work VM and read the same day, each step its own commit (PLAN §8 R32, R33). R32 `trend1d` — the basket's 30-day sign (R6's one-day row, IC +0.070, five of five years, never acted on) traded on every pair for a day — FAILED its stage-1 gate on the per-year condition: taker net +10.7 bps a trade [−11.0, +32.3] on 14,672 trades / 1,578 days, both nulls p ≤ 0.025, but 2020 −7.1, 2022 −14.5 and 2024 −21.4 against a bar of −5. All the money is the long side (+35.5 [+4.9, +66.1]): after an up-month the basket rose +56 bps a day, after a down-month +4, so the short side has no gross and pays the round trip; the long side itself is −63 in 2022 — R8's shape. Held until the sign flips the costs fall from 12.7 to 0.9 a trade and the net is +22: the years fail it, not the costs. PARKED, no variant, decision I not opened, F3+F4 never read (as registered). R33 — the ±1 % book imbalance demeaned by the pair's trailing month, a ceiling screen on P2's cells (F1+F2, eleven names) — validity PASS to 0.0 (P2's raw row and its 200-draw null reproduced exactly), and the demeaned feature CLEARS at one day: IC −0.022 (t −3.3, se 0.007), p 0.005 on BOTH nulls (day shuffles and whole-day shifts), F1 −0.025 / F2 −0.020, above the maker bar 0.0106 and the taker bar 0.0182. The within-month part is 80–100 % of the imbalance's variance and carries more than half of P2's −0.039: R9's reading of 2026-09-22 ("the IC lives in the slow level") was wrong. A hypothesis on seen cells, nothing in money; reported beside: the same feature predicts the SIZE of the next move strongly (vol IC +0.05 at 15m, t 18). The paper test (P7) runs by itself; last health 2026-10-05 green. Work VM stopped.** The rest of the status (P7, the earlier screener reads, data in hand) is the 2026-10-09 row below. | **fluxtrader2 needs from Vadim: P8 decision J — the breadth step after R33's clear (PLAN P8 decision J): recommended (J1) the archive's depth for the forty of R10 (32 outside names, ≈ 8 GB zipped, a day), the same screen on their exploration cells, a priced rule only on a clear there and confirmed on F3+F4; (J2) the 188 screener members (≈ 45 GB, days, disk may need to grow); (J3) price the rule on the twelve now — forbidden by R33's gate, not recommended; (J4) P7 alone.** Decision H decided 2026-10-12 → R32 (failed, parked), R33 (clears). Decision G 2026-10-09 "G1"; F revised the same day → R31. |
| 2026-10-09 | **fluxtrader2: the paper test running (green 2026-10-05); the screener phase's last item in hand, R31 (Vadim's F5, registered, built, tested and read stage 1 the same day): the US index's last hour traded at its sign on the whole basket as a maker, when the hour's move is at least one of the index's own hourly sigmas, held four hours, with a 15-minute serving lag. Stage 1 on the seen bars (2020-05 → 2024-08) PASSED the gate as written — maker net +2.05 bps a trade [−6.24, +10.34], both nulls p 0.010, no calendar year under −5 — and says what R30 said in money: the gross is real (+6 … +9 bps a trade, every year), the costs take it back, the net is about zero; the long side nets +8 [−3, +18] and carries the basket's drift, the short side −4; the lag and a tighter threshold change nothing the sample can see. F5's premise as written on 2026-10-08 was corrected in the block before any number: the 4h bar R30 missed was already the maker bar, so the room was a threshold, not a price. Stage 2 (F3+F4, the only confirmation cells no market-wide question has read) is P8 decision G, DECIDED 2026-10-09 (Vadim's "G1"): NOT RUN — with the measured noise it could confirm a true +2 about one time in twenty-five; R31 parked, F3+F4 unspent for the market factor. Not shown to trade profitably yet.** **(1) P7 — paper trading of R14, LIVE since 2026-09-25 17:00 UTC on `fluxtrader2-serve`.** R14 is a simple model on price-bar features that forecasts a pair's next-day move against the other pairs; on data nobody had looked at (R16) it earned +33 USDT a trade on 10,000 after costs, 3.6 trades a day, and failed one of five criteria — the one that sample could not pass. Vadim funded the paper test by override. Health 2026-10-05 02:05 UTC: green (2,712 decisions, 40 taken, 3 open, 0 late, 0 missing bars, model `model_2026-09-30`); the first refit on the host PASSED (2026-09-30); the first monthly identity check (2026-10-01) PASSED (`checks/check_2026-10-01.md`). Claude reads `vm.sh serve-status` monthly, next on or after 2026-11-01 01:30 UTC. The money is read once (R17): at ≥ 600 trades and ≥ 6 months, earliest 2027-03-25. **(2) P8 — the screener: fourteen reads, nothing clears its costs** (PLAN P8 and §8): the twelve's model carries nothing to outside names (R18, R19); the exchange's own numbers per name — funding, premium, open interest, long/short, taker flow — nothing at one day (R20, R21) and nothing at 3 and 7 days once counted in actual returns (R22–R25, re-executed 2026-09-30); the US index (R26) and the ETF flows (R27) nothing per name; a new perpetual sold at launch and held a week (R28) did not confirm on F3+F4 (R29, −176 USDT a trade); the index and the flows as market direction (R30) closed by cost; the index's last hour as a maker-priced basket rule (R31) +2 bps a trade net on seen bars, inside its noise. Parked rows and their revival triggers: PLAN §7. **(3) Data in hand, all audited:** the archive's depth, metrics, funding and tape summaries; 40 wide-universe pairs; the premium index; US500/US100 one-minute bars 2020 → 2026-09; Farside ETF flows; DefiLlama unlock snapshots; Binance announcements. | **fluxtrader2 needs from Vadim: P8 decision H — the brainstorm's pick (PLAN P8 decision H): recommended (H1) the basket's 30-day trend at a one-day horizon (R6's own 1d row, IC +0.070, 5 of 5 years, never acted on) and (H2) the demeaned ±1 % book imbalance at 1d as a ceiling screen, registered together on seen bars; (H3) the forced-flow signature at 1–4h, (H4) the funding-settlement premium, (H5) seasonality, (H6) the carry.** Decision G decided 2026-10-09, "G1": R31's stage 2 not run, R31 parked with F3+F4 unspent. Earlier the same day: decision F revised, "let's go with F5" → R31. 2026-10-08, "1": R30 (read). 2026-10-05, "D1 a": R29 (read, parked); "C1": R28. 2026-09-30, "(A1) (B1)": R23's second stage not run, the outside-names search parked. |

### Handoff — where the next session starts (written 2026-10-12, after R34 was read; rewritten, not appended to, at each handoff)

Everything up to here is committed. The work VM (`fluxtrader2-work`) is stopped unless the pooled run below is still in flight; the
serve host (`fluxtrader2-serve`) runs P7 by itself (health 2026-10-05 02:05 UTC: green — 2,712 decisions, 40 taken, 3 open, 0 late,
0 missing bars, `check True`, `err None`, model `model_2026-09-30`).

**One question is open — P8 decision K, the next question (PLAN P8 decision K; recommended K1: the slow imbalance level, found twice,
at a 3- and 7-day hold in actual returns on the 43 names' exploration cells — no fetch, half a day, nothing in money).** Today's four
reads: R32 (`trend1d`) PARKED — the years fail it, not the costs, and all its money is the long side; R33 CLEARS on the twelve (the
within-month imbalance, IC −0.022 at 1d, both nulls p 0.005); R34, its breadth step on 32 fresh names, NOT DETECTABLE (−0.013, p 0.22)
while the RAW imbalance replicates (−0.036, p 0.015) through its SLOW part — §7 (b) closed, the lean parked as the twelve's, R35 not
licensed. The mode: measure, with P7's clock running in the background — the wait forbids only touching R14 or the serve path.

In this order:

1. **Decision K.** On Vadim's pick, a NEW registration (§8 R35): the statistic (R22's frame, the mean in actual returns with the tail),
   the holds (3 d, 7 d), the universe (the 43 names whose book is in hand), the gate and what a clear licenses (a confirmation on
   F3+F4 after the book for 2024-09 → 2026-01 is fetched under it); commit; run on the work VM; read; commit.
2. **The pooled 43-name row of R34** (`vm.sh bg r34_pool ceiling --target pairs --family depth --universe both --draws 200`, log
   `output/logs/r34_pool.log`, `output/ceiling_depth_both.md`) — a described number: if this handoff still says "in flight", pull it,
   write its one line under R34's Result, stop the VM, commit.
2. **P7.** Claude runs `./fluxtrader2/scripts/vm.sh serve-status` once a month, next on or after 2026-11-01 01:30 UTC:
   `check True`, `err None`, `late 0`, `missing24h 0`, model age < 30 d. The money is read once (R17), earliest 2027-03-25.
3. **A thing to carry into any next book rule** (R33): the imbalance demeaned by its month is also a strong SIZE signal (vol IC
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
