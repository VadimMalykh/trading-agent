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
| 2026-09-25 | **fluxtrader2: P0–P5 done (steps 1–11 read); P7 paper trading of R14 FUNDED 2026-09-25 by Vadim's override after R16; step 1 (build the serving path) not started. VM stopped.** Not shown to trade profitably yet, and this is the closest it has come. R16 (R14's candle ridge on the never-seen folds F3+F4): net +33 a trade (exploration: +34), hedged net +25 (+13), held-out IC 0.043 (0.033), flip null p 0.005, on 1,750 trades, 3.6 a day, +120 USDT a day on 120,000 deployed. Four of five criteria passed; the fifth, the shuffle null, read p 0.18 against a null whose 95th percentile is +104 — it could not be passed, and the registration had said that counts as a FAIL. Verdict by the rule: CLOSED for further backtests; verdict by Vadim, after the three options were explained: fund paper trading anyway (new observations, no fold spent), written down as an override on Principle 5 grounds. Thin parts: the money is in F4 not F3, top decile only, long side only, different names than before. R15 (26 columns) the same day: the extra columns add nothing held out; parked. Plan: PLAN P7 (the serving path: what, where, the clock, the ledger, two identity checks) and §8 R17 (the paper read, registered before any live number: ≥ 600 trades and ≥ 6 months, flip null p ≤ 0.05). **Next session (Claude): build `ft2 serve` + the serve host + `docs/SERVE.md` + the replay identity test (P7 step 1), on Vadim's host decision.** | **fluxtrader2 needs from Vadim: the serve host — (a) a new always-on `fluxtrader2-serve` e2-small, ≈ 13–15 USD a month (recommended); (b) keep `fluxtrader2-work` on, resized to e2-small while idle (same money, one host, serving pauses at every resize). Nothing of this project runs on fluxtrader1's VM — it is a data source only.** Optional, unchanged: a little BNB in the futures wallet turns the fee discount on. |

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
