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
| 2026-09-23 | **fluxtrader2: P0–P4 done, P5 steps 1–8 read; step 9 (R14) REGISTERED and RUNNING on the work VM (left running so the job can finish; stop it after the pull) — PLAN P5 has the plain-language result.** Not shown to trade profitably yet. Today, three reads of the plan's own deliverable (a ridge on candle features forecasting a pair's next-day move against its peers, traded when it clears 15 bps): (1) R12, fitted on 30 of the 40 pairs and scored on the 10 it never saw — **no signal (IC 0.0075)**; (2) R13, the same fitted in pair — still nothing on the forty (0.009), but **on the twelve collector names IC 0.034 (t 2.2), and the book on it earned +33 net a trade [+0.5, +65] on 1,915 trades, hedged +27 [+5, +49] — an in-pair walk-forward on exploration folds, so a hypothesis, carried by WLD, SOL, PEPE, AVAX**; the candle ridge is closed on the wide universe. (3) R14, running: the twelve held out in groups of three — does the signal transfer between the names that have it? **Next session (Claude), in order: `vm.sh pull`; read `output/backtest/r14_ridgebook_1d_ho12/report.md` and `forecast.md`; fill R14's Result and apply its gate (PLAN §8 R14); `vm.sh stop`; then put the decision below to Vadim with R14's numbers in it.** | **fluxtrader2 needs from Vadim: ONE decision, after R14 is read (not before). Plain version:** the twelve-name candle book looks profitable on the two *exploration* folds (May 2023 → Aug 2024), which we may look at as often as we like, so a good number there can be luck from looking. The only way to find out is to read it once on *confirmation* data (F3 = Sep 2024 → Apr 2025, F4 = May → Dec 2025), and each such fold can be read once per question and is then spent for it. F3 alone (8 months, ~700 trades) can only detect an effect of ~70 bps a trade; the effect we are chasing is ~33, so F3 alone would most likely say "cannot tell" and be wasted. Options: **(A)** read F3+F4 pooled, once (~1,400 trades, detects ~50; a fair chance of a verdict either way; spends two of the three confirmation folds on this question); **(B)** do not spend them on a candle-only book — keep exploring on F1+F2 (book features on the twelve, PLAN §7) and save F3–F5 for something with a bigger margin; **(C)** trade it on paper instead (P7): costs no fold, but takes months to reach the same power. Recommendation: (B) unless R14 shows the signal transferring between names (gate (v) passed) — then (A). Optional, unchanged: a little BNB in the futures wallet turns the fee discount on. |

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
