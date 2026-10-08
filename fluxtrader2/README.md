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
| 2026-10-08 | **fluxtrader2: the paper test running (green 2026-10-05); the screener phase (P8) has read its last source in hand — R30 (2026-10-08, Vadim's "1"): the US index and the ETF flows as MARKET-direction and sizing information on the whole basket, in R6's frame. Direction: 0 of 27 clear. The Nasdaq 100's last hour carries into crypto's next one to four hours in each of five years (one time in two hundred among eighteen numbers, the same on the S&P 500) but is worth less than a round trip on the basket pays — closed by cost; the day's move, the move into a close and crypto's lag over a day say nothing; yesterday's ETF flow says nothing half a year can see. Sizing: the index's session clears at 4h — the basket moves a quarter more while the US index is open, every year, a fifth of it beyond crypto's own volatility — a described row for whatever rule comes next, nothing for P7. Not shown to trade profitably yet.** **(1) P7 — paper trading of R14, LIVE since 2026-09-25 17:00 UTC on `fluxtrader2-serve`.** R14 is a simple model on price-bar features that forecasts a pair's next-day move against the other pairs; on data nobody had looked at (R16) it earned +33 USDT a trade on 10,000 after costs, 3.6 trades a day, and failed one of five criteria — the one that sample could not pass. Vadim funded the paper test by override. Health 2026-10-05 02:05 UTC: green (2,712 decisions, 40 taken, 3 open, 0 late, 0 missing bars, model `model_2026-09-30`); the first refit on the host PASSED (2026-09-30); the first monthly identity check (2026-10-01) PASSED (`checks/check_2026-10-01.md`). Claude reads `vm.sh serve-status` monthly, next on or after 2026-11-01 01:30 UTC. The money is read once (R17): at ≥ 600 trades and ≥ 6 months, earliest 2027-03-25. **(2) P8 — the screener: thirteen reads, nothing clears its costs** (PLAN P8 and §8): the twelve's model carries nothing to outside names (R18, R19); the exchange's own numbers per name — funding, premium, open interest, long/short, taker flow — nothing at one day (R20, R21) and nothing at 3 and 7 days once counted in actual returns (R22–R25, re-executed 2026-09-30); the US index (R26) and the ETF flows (R27) nothing per name; a new perpetual sold at launch and held a week (R28) did not confirm on F3+F4 (R29, −176 USDT a trade); the index and the flows as market direction (R30) closed by cost. Parked rows and their revival triggers: PLAN §7. **(3) Data in hand, all audited:** the archive's depth, metrics, funding and tape summaries; 40 wide-universe pairs; the premium index; US500/US100 one-minute bars 2020 → 2026-09; Farside ETF flows; DefiLlama unlock snapshots; Binance announcements. | **fluxtrader2 needs from Vadim: decision F (PLAN P8) — what the screener phase does after R30, if anything.** Recommended (F1): P7 alone, with the index's session carried as a sizing row into the next registered rule. The others: (F2) the spot-hedged funding carry — a scope decision (a spot leg; yield, not a forecast); (F3) the unlock read (90 events, sees only a large effect); (F4) F5's 69 launches — not recommended; (F5) a maker-priced reading of the index's last hour on F3+F4 — one shot, the only cells left for it. Earlier, 2026-10-08, "1": R30 (read). 2026-10-05, "D1 a": R29 (read, parked); "C1": R28. 2026-09-30, "(A1) (B1)": R23's second stage not run, the outside-names search parked. |

### Handoff — where the next session starts (written 2026-10-08; rewritten, not appended to, at each handoff)

Everything up to here is committed. Nothing is running on the work VM (`fluxtrader2-work`, stopped); the serve host
(`fluxtrader2-serve`) runs P7 by itself (health 2026-10-05 02:05 UTC: green — 2,712 decisions, 40 taken, 3 open, 0 late,
0 missing bars, `check True`, `err None`, model `model_2026-09-30`).

**One decision is open: P8 decision F** (PLAN P8, the options listed there and in the status row above) — what the screener
phase does after R30, if anything. R30 (the index and the ETF flows as market-direction and sizing information on the
basket) was registered, amended once before any real bar was read (the lag's b: the 24-hour slope, recorded in the block),
run and read on 2026-10-08: direction 0 of 27 clear, the index's last hour a certified but sub-cost continuation (parked,
PLAN §7, revival = F5 above); the session a sizing fact (ix_open CLEARS at 4h) carried as a described row into the next
rule. The mode: measure, with P7's clock running in the background — the wait forbids only touching R14 or the serve path.

In this order:

1. **P7.** Claude runs `./fluxtrader2/scripts/vm.sh serve-status` once a month, next on or after 2026-11-01 01:30 UTC:
   `check True`, `err None`, `late 0`, `missing24h 0`, model age < 30 d. The money is read once (R17), earliest 2027-03-25.
2. **Decision F is Vadim's**, in a fresh session. Nothing is registered. Whatever is registered next carries R30's sizing
   row (the basket's |move| a quarter larger while the US index is open; partial +0.059 on volratio_4h at 4h) as a
   described row, and the market-factor confirmation folds F3+F4 are unread — one shot for any market-wide rule.
3. **A thing to carry into any next idea on young names** (R21–R25, R28–R29): the typical case and the mean part ways
   there — register the statistic that a real position earns (the mean, in actual returns, with the tail in it), expect
   the share of names that explode to differ between periods, and do not read a stop as a cure.
4. **A thing to carry into any next ceiling audit** (R30): a planted test on made-up bars is run BEFORE the real bars and
   can amend a registration — R30's lag feature was mis-specified (the hourly contemporaneous slope misses a slow follower)
   and the test caught it; the amendment is in the block with its reason. And a feature with a time-of-day pattern
   (ix_open) gets a hard null from whole-day shifts, which keep the time of day: the family bar read 7.85, not ~2.5.

Where the outputs are (pulled, not in git): R30 — `output/market_index.md`, `output/market_index/` (`screen.parquet` the
direction rows with verdicts, `screen_sizing.parquet`, `screen_all.parquet` R6's rows beside, `screen_null.parquet` every
draw, `reference.parquet` US500 and R6's features, `money_view.parquet`, `size_view.parquet`, `coverage.parquet`,
`minute_age.parquet`, `validity.json`), `output/market_etf.md`, `output/market_etf/` (the same less the sizing), the logs
`output/logs/r30a.log`, `r30b.log`; R29 — `output/listing/r29/`, `output/listing/r28_recheck/`, `output/listing/r29_*check*.json`,
`output/backtest/r29_costwide_check.json`; R28 — `output/listing/r28/`; the events audit — `output/events_inventory.md`,
`output/events_known_at.csv`, `output/events_binance_unparsed.csv`; R27 — `output/audit/r18_transferbook_1d_etf`,
`output/audit/twelve_etf`; R26 — `output/audit/r18_transferbook_1d_index`, `output/audit/twelve_index`; the re-execution of
R22–R25 — `output/horizon/*_actual`, `output/backtest/r24_pool_actual`, `output/backtest/r25_read_actual`,
`output/backtest/actual_table.md`; R6 — `output/market.md`, `output/market/` (R30's validity reproduces it to the digit).

Things learned the hard way: money is counted as a position earns it — a shortcut (a log, a cost in bps of the entry size)
is measured against the exact figure before a gate reads it (`scripts/actual_describe.py`); a result far outside its
expected band is checked trade by trade before it is believed (R25: the unit of profit was wrong); a check that merges two
whole slices does not fit the work VM's 16 GB (compare name by name); `vm.sh bg …` with its output piped or redirected
does not return until the job ends (the job itself is detached and safe) — run it bare and watch the log; a history
published today is not the history that was published — measure it against archived copies before a feature reads it
(the unlock schedules: half of them re-drawn); DefiLlama re-keys a token over the years, so a comparison across copies
goes by ticker, not by id (`events.align`); and the Wayback Machine answers 429 to a browser's User-Agent sent by a
script and serves a plain one at once (`events.WB_UA`; `ft2/etf.py` still sends the browser string); a check of the
inputs is itself code written the same day — when it says FAIL, describe what it counted before touching anything (R28: a
name that had gained months, two launches priced from another file), fix the check, keep the first output; a noise
estimate that decides a gate is read beside plainer ones (R28: the block bootstrap's se was the smallest of three); and a
number quoted into a registration from another table is checked against the rule that defines it (R30 quoted R6's 1h
bar as 0.046 — the registered rule gives 0.061; the run recomputes, nothing hinged on it).

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
