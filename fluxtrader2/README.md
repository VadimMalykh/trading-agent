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
| 2026-09-22 | **fluxtrader2: P0–P4 done, P5 steps 1–4 read — PLAN P5 has the plain-language result.** Not shown to trade profitably. Today: the book-imbalance lead from 2026-09-21 was registered as a fixed rule (R9: when a pair's order book within ±1 % of the price is lopsided beyond its usual range, bet against the heavy side for a day) and run through the harness on the exploration folds. **It does not make money: −2 bps a trade after costs [−25, +21]** (a bps is 0.01 %, so −2 USDT per 10,000 USDT), 9 trades a day, gross +8 where the screen's statistic promised +20 to +30. Its gate failed on the first condition, so it is **parked** and no untouched fold was read. Reading: the statistic that found it measures a slow, weeks-long lean of a pair's book, not something a daily trade collects. One thing to keep: 79 % of its trades were shorts, and the rare long side (a book heavy on the sell side) earned +32 net on 930 trades [−5, +69] — a new question, not a tweak (PLAN §7). **Next session (Claude): the ~40-pair universe for the "torn-away pair keeps going" hypothesis (H2, bar +5 bps a leg); then, if time, the long-only book question as its own registration** — PLAN P5 "Next session". The work VM is stopped. | **fluxtrader2 needs from Vadim: nothing.** One optional decision, unchanged (PLAN §7, `trendfall4h` row): read the three untouched folds (2024-09 → 2026-09) for the parked market-timing rule? Recommendation (a) no, leave it parked; saying nothing = (a). Optional, unchanged: a little BNB in the futures wallet turns the already-enabled 10 % fee discount on. |

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
