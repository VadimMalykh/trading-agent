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
| 2026-09-29 | **fluxtrader2: one thing running, one decision open. Not shown to trade profitably yet.** **(1) P7 — paper trading of R14, LIVE since 2026-09-25 17:00 UTC on `fluxtrader2-serve`.** R14 is a simple model on price-bar features that forecasts a pair's next-day move against the other pairs; on data nobody had looked at (R16) it earned +33 USDT a trade on 10,000 after costs, 3.6 trades a day, and failed one of five criteria — the one that sample could not pass. Vadim funded the paper test by override. Health 2026-09-27 22:05 UTC: green (648 decisions, 14 taken, 0 late, 0 missing bars, 0 mismatches). Claude checks the first refit on the host (2026-09-30 00:00 UTC, `journalctl -u ft2-decide` not OOM-killed) and the first causal check (2026-10-01 01:30 UTC), then `vm.sh serve-status` monthly. The money is read once (R17): at ≥ 600 trades and ≥ 6 months, earliest 2027-03-25. **(2) P8 — the screener: four reads, nothing clears its costs.** R18 and R19 (2026-09-27): on 188 names outside the twelve, picked monthly by volume alone, the twelve's model knows nothing, and neither four splits known beforehand nor a split that uses the future finds a group where it does. **R20 (2026-09-28)** asked instead what information the model does not use says about a name's next day against its peers — twelve numbers, no model. Funding and the gap between the perpetual and the spot price: nothing, closed. Open interest (the total size of positions open in a name): names with large open interest against their volume, and names whose open interest has been falling, did better the next day in both halves of the sample (correlation 0.033, t 3.98) — but the best of twelve meaningless numbers did as well in 6 % of trials against a bar of 5 %, so by the rule nothing passed. Even if real it is small: 0.033 is where trading the strongest tenth just pays its 18 USDT of costs on 10,000. No fold was spent. **R21 (2026-09-28)** then ran those open-interest numbers as a simulated book with costs on the same names — every hour buy the six names at the top of the ranking, sell the six at the bottom, hold a day: **it lost 17 USDT a trade on 10,000 after costs (8,214 trades; 1.6 USDT earned before costs of 19), so by the rule written beforehand it is closed.** The ranking is real but comes from one corner — names in a trading frenzy usually fall behind — and says nothing about which names rise. Nothing measured on names outside the twelve clears its costs at a one-day hold. **R22 (2026-09-28)** then asked whether holding 3 or 7 days changes that, for six signals: the tenth of names a signal ranks highest against the tenth it ranks lowest, in money. **Nothing passed and nothing was ruled out.** The open-interest numbers lean the right way and more so the longer the hold (11 USDT per 10,000 at one day, 25 at three, 59 at seven, against a round trip of 17.6), but the same book given the price moves of other weeks does as well one time in ten; and all of it is names in a frenzy falling behind, nothing that picks names that rise. 485 days hold only 69 weeks: the sample ran out, not the idea. **R23 (2026-09-29)** then tested the one leaning number — the open-interest score held 7 days — once, on 71 weeks nobody had read (2021-12 → 2023-04; open interest does not exist earlier), 141 names: **it came back.** The highest-ranked tenth against the lowest earned 67 USDT per 10,000 a week before trading costs (round trip 17.6), 2.4 times its noise, and none of 471 re-timed books did as well; first half 106, second half 28; 43 without the two collapse months of 2022. It is a measurement before costs, not a book: what trading these names cost in 2022 is unknown, and R21 showed a real ranking can lose money once traded. **R24 (2026-09-29)** then traded it as a book with costs on both samples read for it (2021-12 → 2024-08): six names bought, six sold, held 7 days, 5,054 positions. Per 10,000 USDT a week: 39 earned before costs, 21 paid, **17 left** — positive in both samples, 8 with the estimated spread and impact doubled, and the same trades with the direction left to a coin do as well one time in forty, which by the rule written beforehand makes the book a CANDIDATE. **Not certified:** the 17 is about as large as its noise (range −17 to +51), the second half of the early sample lost, and all of the money comes from the names sold (names in a frenzy). It is the first book outside the twelve that did not lose. Nothing is licensed to trade; F3+F4 are untouched. Work VM stopped. Details: PLAN P7, P8, §8 R17–R24; parked data ideas (ETF flows, US indices, events): PLAN §9. | **fluxtrader2 needs from Vadim: one decision — whether to spend F3+F4 on the confirmation of R24's book** (PLAN P8 "What next"). Yes (*recommended*): R25, the same book on the outside names of 2024-09 → 2026-01, which nobody has read; downloads and one to two days; about even odds to pass even if the effect is real; F5 stays in reserve. Yes with F5 as well: better odds, nothing unread left. No: the book stays a candidate on record, P7 runs on alone. Optional, unchanged: a little BNB in the futures wallet turns the fee discount on. Nothing of this project runs on fluxtrader1's VM — it is a data source only. |

### Handoff — where the next session starts (written 2026-09-29; rewritten, not appended to, at each handoff)

Everything up to here is committed. Nothing is running on the work VM (`fluxtrader2-work`, stopped); the serve host
(`fluxtrader2-serve`) runs P7 by itself (health 2026-09-28 23:05 UTC: green — 948 decisions, 21 taken, 7 open, 0 late,
0 missing bars, 0 mismatches).

**One question is open, and it is Vadim's:** whether to spend F3+F4 (and F5?) on the confirmation of R24's book (PLAN P8
"What next"). R24 read CANDIDATE on 2026-09-29 (§8 R24 Result).

In this order:

1. **When Vadim answers.** On "yes": ask the one design question P8 names (the book as it is, or the short side alone
   against the market), then write the registration as §8 R25 *before* the members of F3+F4 are chosen and before any
   file of them is fetched (R23's block is the model for the universe and the downloads, R24's for the book, the costs
   and the gate; `universe.screen_select(("F3", "F4"))` picks the members), commit, then the universe, the downloads,
   `costwide`, the build, the tests (`./fluxtrader2/scripts/ft2.sh --test`, 94 pass today), the run with
   `--registration R25`, the read; one commit per step. On "no": nothing to do but steps 2 and 3.
2. **Claude, on or after 2026-09-30 00:00 UTC — P7's first refit.** `./fluxtrader2/scripts/vm.sh serve-status` (the model's
   name moves on from `model_2026-08-31`, `err None`), then
   `./fluxtrader2/scripts/vm.sh serve-ssh 'journalctl -u ft2-decide --since "2026-09-29 23:00" --no-pager | tail -30'` —
   no `Killed`, no out-of-memory line. A problem → `docs/SERVE.md`.
3. **Claude, on or after 2026-10-01 01:30 UTC — P7's first causal check.** `vm.sh serve-status`: the line's `check` field is
   no longer `None` and reports no mismatch. After that, `serve-status` once a month.
4. **Housekeeping, any time the work VM is up:** `data/*_before_r23.parquet` (2.5 GB, the three archive slices as they were
   before R23's ingest) and `data/cost_daily_wide_before_r24.parquet` did their job — both checks PASS — and can be deleted.

Three things learned the hard way: a check that merges two whole slices does not fit the work VM's 16 GB (compare name by name, as `scripts/r23_check_inputs.py` does); `vm.sh bg …` piped into `grep` does not return until the job ends (the job itself is
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
