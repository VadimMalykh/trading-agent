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
| 2026-09-30 | **fluxtrader2: the paper test running; the record of R22–R25 being corrected (Vadim decided "(1)" on 2026-09-30: the measure fixed, the four reads re-executed as registered — IN PROGRESS, see the handoff). Not shown to trade profitably yet.** **(1) P7 — paper trading of R14, LIVE since 2026-09-25 17:00 UTC on `fluxtrader2-serve`.** R14 is a simple model on price-bar features that forecasts a pair's next-day move against the other pairs; on data nobody had looked at (R16) it earned +33 USDT a trade on 10,000 after costs, 3.6 trades a day, and failed one of five criteria — the one that sample could not pass. Vadim funded the paper test by override. Health 2026-09-30 05:05 UTC: green (1,308 decisions, 25 taken, 0 late, 0 missing bars, 0 mismatches); the first refit on the host PASSED (2026-09-30 00:00 UTC: `model_2026-09-30`, `refits: 1`, no out-of-memory line). Claude checks the first causal check (2026-10-01 01:30 UTC), then `vm.sh serve-status` monthly. The money is read once (R17): at ≥ 600 trades and ≥ 6 months, earliest 2027-03-25. **(2) P8 — the screener: four reads, nothing clears its costs.** R18 and R19 (2026-09-27): on 188 names outside the twelve, picked monthly by volume alone, the twelve's model knows nothing, and neither four splits known beforehand nor a split that uses the future finds a group where it does. **R20 (2026-09-28)** asked instead what information the model does not use says about a name's next day against its peers — twelve numbers, no model. Funding and the gap between the perpetual and the spot price: nothing, closed. Open interest (the total size of positions open in a name): names with large open interest against their volume, and names whose open interest has been falling, did better the next day in both halves of the sample (correlation 0.033, t 3.98) — but the best of twelve meaningless numbers did as well in 6 % of trials against a bar of 5 %, so by the rule nothing passed. Even if real it is small: 0.033 is where trading the strongest tenth just pays its 18 USDT of costs on 10,000. No fold was spent. **R21 (2026-09-28)** then ran those open-interest numbers as a simulated book with costs on the same names — every hour buy the six names at the top of the ranking, sell the six at the bottom, hold a day: **it lost 17 USDT a trade on 10,000 after costs (8,214 trades; 1.6 USDT earned before costs of 19), so by the rule written beforehand it is closed.** The ranking is real but comes from one corner — names in a trading frenzy usually fall behind — and says nothing about which names rise. Nothing measured on names outside the twelve clears its costs at a one-day hold. **R22 (2026-09-28)** then asked whether holding 3 or 7 days changes that, for six signals: the tenth of names a signal ranks highest against the tenth it ranks lowest, in money. **Nothing passed and nothing was ruled out.** The open-interest numbers lean the right way and more so the longer the hold (11 USDT per 10,000 at one day, 25 at three, 59 at seven, against a round trip of 17.6), but the same book given the price moves of other weeks does as well one time in ten; and all of it is names in a frenzy falling behind, nothing that picks names that rise. 485 days hold only 69 weeks: the sample ran out, not the idea. **R23 (2026-09-29)** then tested the one leaning number — the open-interest score held 7 days — once, on 71 weeks nobody had read (2021-12 → 2023-04; open interest does not exist earlier), 141 names: **it came back.** The highest-ranked tenth against the lowest earned 67 USDT per 10,000 a week before trading costs (round trip 17.6), 2.4 times its noise, and none of 471 re-timed books did as well; first half 106, second half 28; 43 without the two collapse months of 2022. It is a measurement before costs, not a book: what trading these names cost in 2022 is unknown, and R21 showed a real ranking can lose money once traded. **R24 (2026-09-29)** then traded it as a book with costs on both samples read for it (2021-12 → 2024-08): six names bought, six sold, held 7 days, 5,054 positions. Per 10,000 USDT a week: 39 earned before costs, 21 paid, **17 left** — positive in both samples, 8 with the estimated spread and impact doubled, and the same trades with the direction left to a coin do as well one time in forty, which by the rule written beforehand makes the book a CANDIDATE. **Not certified:** the 17 is about as large as its noise (range −17 to +51), the second half of the early sample lost, and all of the money comes from the names sold (names in a frenzy). It is the first book outside the twelve that did not lose. **R25 (2026-09-29)** ran that book once on 69 unread weeks (F3+F4, 216 names). It passed its test with 70 USDT left per 10,000 a week — too good, and the check that followed found why: **the harness counts profit in log returns, a shortcut that overstates every sold position and understates every bought one on large moves, and this book sells the wildest names.** Counted as a position actually earns, the same trades LOSE: −11 and −17 on R24's two samples, −39 on the unread months (+32 there if a sold position is closed once it has lost its whole size — a different rule, and one trade makes most of that difference). The verdict is held until the re-execution is read; nothing is licensed. R14 and the paper test are not hurt by this (P7 stores prices, and R14 is +39 in actual returns against +34 as counted). F3+F4 are spent for this question; F5 is unread. Details: PLAN P7, P8, §8 R17–R25; parked data ideas (ETF flows, US indices, events): PLAN §9. | **fluxtrader2 needs from Vadim: nothing now.** He decided "(1)" on 2026-09-30 (fix the measure, re-execute R22–R25 as registered); Claude runs it. A book with a protective stop would be a new registration afterwards. Optional, unchanged: a little BNB in the futures wallet turns the fee discount on. Nothing of this project runs on fluxtrader1's VM — it is a data source only. |

### Handoff — where the next session starts (written 2026-09-30; rewritten, not appended to, at each handoff)

Vadim decided "(1)" on 2026-09-30: the unit of money is fixed and R22–R25 are re-executed as registered (PLAN §3 "The unit
of money", "The re-execution `actual`"). The code, its tests (98 pass) and the protocol are committed; **no re-executed
number has been read yet.** The serve host (`fluxtrader2-serve`) runs P7 by itself (health 2026-09-30 05:05 UTC: green;
the first refit PASSED).

In this order:

1. **The re-execution, on the work VM** (`fluxtrader2-work`; start it with `./fluxtrader2/scripts/vm.sh start`, stop it
   when the chain has ended). One chain, each step once, R22 → R23 → R24 → R25:
   `./fluxtrader2/scripts/vm.sh bgsh actual 'bash scripts/actual_chain.sh'`. Progress:
   `./fluxtrader2/scripts/vm.sh ssh 'cat ~/fluxtrader2/output/logs/actual.log'` — one `start` and one `done` line per
   step, the last line "the chain ended: every step done"; a step's own output is `output/logs/actual_<step>.log`. A
   step that failed stops the chain; started again, the chain skips the steps that are done (a guarded fold is read once
   per tag). About two hours in all.
2. **Read them in the registered order, one commit per read:** `vm.sh pull`, then for each of R22, R23, R24, R25 —
   validity first (`same_as_first_read.json` says PASS; the book checks; the reports' validity lines), then the gate as
   registered, then a "Re-executed 2026-09-30" paragraph under the block's first result in PLAN §8 (the first result is
   not edited), the plain-words result in P8, §7's row, this file. Reports: `output/horizon/r18_transferbook_1d_actual`,
   `output/horizon/pre_actual`, `output/backtest/r24_pool_actual` (pool.md, described.md),
   `output/backtest/r25_read_actual` (pool.md, described.md).
3. **Claude, on or after 2026-10-01 01:30 UTC — P7's first causal check.** `vm.sh serve-status`: the line's `check` field is
   no longer `None` and reports no mismatch. After that, `serve-status` once a month.
4. **Housekeeping, any time the work VM is up, on Vadim's word:** `data/*_before_r23.parquet`, `data/*_before_r25.parquet`
   and `data/cost_daily_wide_before_r24.parquet` did their job — the checks PASS — and can be deleted.

Four things learned the hard way: a result far outside its expected band is checked trade by trade before it is believed (R25: the unit of profit was wrong); a check that merges two whole slices does not fit the work VM's 16 GB (compare name by name, as `scripts/r23_check_inputs.py` does); `vm.sh bg …` piped into `grep` does not return until the job ends (the job itself is
detached and safe) — watch a job by its log's `wrote ` line; and a run's described checks live in `scripts/r20_*.py` and
`scripts/r21_*.py`, not in the ignored `output/` folder (R22's are the report's own tables).

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
