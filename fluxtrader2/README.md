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
| 2026-09-25 | **fluxtrader2: P0–P4 done, P5 steps 1–10 read; step 10 (R15) read 2026-09-25 and FAILED its gate; R16, the confirmation read, is fixed to ONE arm (R14) and is NOT launched — it waits for Vadim's word. VM stopped.** Not shown to trade profitably yet. R15 (the held-out ridge on the P2 screen's full 26 columns, with R14's candle model inside it as a paired reference — reproduced exactly, run valid) says the twelve book, flow and positioning columns add nothing that transfers: held-out IC 0.031 (t 3.0) against 0.029 for the candles on the same cells, paired gain +0.001 (t 0.1), and the little gain there is moved the signal off the four young names that carry the money onto the old ones. The wider model forecasts bigger moves for the same information, so twice the cells clear 15 bps and the book takes 4,033 trades at +14.5 gross instead of 1,896 at +48: net +2.7 [−13.8, +19.2], hedged net −4.3, shuffle p 0.085, flip p 0.03 — worse than R14 on every money row (PLAN P5 step 10, §8 R15). R14 stays the candidate: +34 net [+6, +62], hedged net +13, held-out IC 0.033 on WLD, SOL, PEPE, AVAX. **Next (Claude, on Vadim's go): `vm.sh start`; launch R16 arm A (command in PLAN P5 step 10 / §8 R16); pull; fill R16's Result; apply its gate (one arm → p ≤ 0.05); `vm.sh stop`. Pass → P7 paper trading for R14; fail → the candle book on the twelve is CLOSED, F5 kept.** | **fluxtrader2 needs from Vadim: one word — launch R16 now (spends F3+F4 on R14, the only remaining candidate; (B)'s strengthening step is exhausted), or hold the folds.** Launching with `--registration` logs the read; it is spent at launch. Optional, unchanged: a little BNB in the futures wallet turns the fee discount on. |

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
