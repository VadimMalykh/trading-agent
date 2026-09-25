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
| 2026-09-25 | **fluxtrader2: P0–P4 done, P5 steps 1–11 read; step 11 (R16, the F3+F4 confirmation read of R14) read 2026-09-25: FAILED on the shuffle null only — CLOSED by the gate as written; F3+F4 spent, F5 kept. VM stopped.** Not shown to trade profitably yet, and this is the closest it has come. Plain words: R14's exploration numbers came back on data nobody had looked at — net +33 a trade (was +34), hedged net +25 (was +13), held-out IC 0.043 (was 0.033), flip null p 0.005 — on 1,750 trades, 3.6 a day, +120 USDT a day on 120,000 deployed. Four of five criteria passed. The fifth, the shuffle null at p ≤ 0.05, read p 0.18 and could not have been passed: on these folds a ridge fitted on shuffled labels earns anything in ±109 bps a trade, so its 95th percentile is +104 against our +33. The registration said before the read that this counts as a FAIL. Thin parts, honestly: the money is in F4 (+73) not F3 (+1.5), in the top forecast decile only, long side only, and in different names than before (ZEC, PEPE, DOGE, WLD; SOL and AVAX flat). Earlier the same day R15 (the 26-column ridge) showed the book, flow and positioning columns add nothing held out (paired gain +0.001) and was parked. Numbers: PLAN §8 R15, R16; plain version P5 steps 10–11. | **fluxtrader2 needs from Vadim: one decision, recorded in PLAN §8 R16 when made — (1) override the gate on Principle 5 grounds and fund P7 paper trading of R14 as is (no fold spent, serving path to build; Claude recommends this); (2) spend F5, the last fold, on a new registration of the same question with a null that has power; (3) accept closure, R14 parked, next registration brings a new target or new observations.** Optional, unchanged: a little BNB in the futures wallet turns the fee discount on. |

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
