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
| 2026-09-24 | **fluxtrader2: P0–P4 done, P5 steps 1–9 read; VM stopped; nothing running — PLAN P5 has the plain-language result.** Not shown to trade profitably yet. **R14 read today:** the candle-feature ridge scored on names it was never fitted on (the twelve held out in groups of three) keeps its signal — **IC 0.033 (t 2.1), the same as in pair** — on WLD, SOL, PEPE and AVAX, and has none on the seven older names. The book on it: 1,896 trades, **+34 net a trade [+6, +62], hedged +27 [+6, +48], hedged net +13 [−8, +34]**, both folds positive, flip null p 0.01; but the shuffle null (a ridge on day-shuffled labels, traded the same way) is beaten only at p 0.085 against a bar of 0.05 — **gate (iii) failed, the other four passed → parked by its own gate** (PLAN §8 R14 has the power note: the null's 95th percentile is +41, so a +33 effect could not have passed it on this sample). Plain reading: the *direction* of the forecast carries real information and transfers between names of a kind (young, violent ones), which is the shape the goal asks for; the *money per trade* is not yet told apart from what a random forecast earns on those names. | **fluxtrader2 needs from Vadim: ONE decision — which of A / B / C for the twelve-name candle book.** Plain version: it looks profitable on the two *exploration* folds (May 2023 → Aug 2024), which we may look at as often as we like, so a good number there can be luck from looking. The only way to know is one read on *confirmation* data (F3 = Sep 2024 → Apr 2025, F4 = May → Dec 2025); each such fold is read once per question and is then spent for it. F3 alone (~730 trades) detects ~65 bps; F3+F4 pooled (~1,900 trades) detects ~40 against an effect of ~33 — even pooled, roughly a 60 % chance of a clear verdict. **(A)** read F3+F4 pooled now for R14's held-out book (spends two of the three confirmation folds on this question). **(B) — recommended:** first build the same ridge with the book and flow features added (PLAN §7 book row, (c); R7's screen read them at IC 0.067 against the candles' 0.048, and they exist from 2023-01, so F1–F4 are covered), read it on F1+F2 under its own registration (a day or two of work, no fold spent), then give the single pooled F3+F4 read to whichever arm a registration names *before* that read. The last row's rule said "(A) if the signal transfers"; it does, but the gate then failed on the money, and a one-shot resource should go to the stronger candidate. **(C)** paper trading (P7): costs no fold, needs a serving path, ~16 months to the same power. Optional, unchanged: a little BNB in the futures wallet turns the fee discount on. |

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
