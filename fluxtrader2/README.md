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
| 2026-09-25 | **fluxtrader2: P0–P4 done, P5 steps 1–9 read; step 10 (R15) REGISTERED and RUNNING on the work VM (left running so the job can finish; stop it after the pull); R16, the confirmation read, REGISTERED — PLAN P5 has the plain-language result.** Not shown to trade profitably yet. Vadim chose **(B)** on 2026-09-25: strengthen the candidate before spending confirmation data. R15 = R14's held-out ridge on the twelve with the P2 screen's full 26-column feature set (tape flow and spread, open-interest change, long/short positioning, taker ratio, depth imbalance and level, funding, range position, dollar volume, on top of the ten candle features), carrying R14's candle-only model inside it as a paired reference. R16 = one pooled read of F3+F4, arms fixed mechanically by R15's gate (R14 always; R15 joins if the features add to a signal that transfers and the book earns; two arms → p ≤ 0.025 each). Background, R14 (read 2026-09-24): held-out IC 0.033 (t 2.1) on WLD, SOL, PEPE, AVAX from models that never saw them, none on the seven older names; +34 net [+6, +62], hedged net +13 [−8, +34], flip p 0.01, shuffle p 0.085 → parked by its own gate (PLAN §8 R14). **Next session (Claude), in order: `vm.sh pull`; read `output/backtest/r15_ridgebook_1d_ho12_all/forecast.md` (the reference line must reproduce R14's 0.0328 — else void) and `report.md`; fill R15's Result and apply its gate (PLAN §8 R15); fix R16's arm list from it; launch R16's arm(s) (commands in PLAN §8 R16); pull, fill R16's Result, apply its gate; `vm.sh stop`.** | **fluxtrader2 needs from Vadim: nothing.** (B) covers launching R16 once R15 is read; say so before the next session if you want to see R15's numbers first. Optional, unchanged: a little BNB in the futures wallet turns the fee discount on. |

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
