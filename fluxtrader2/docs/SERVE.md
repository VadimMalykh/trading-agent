# SERVE — P7 paper trading of R14 on the always-on host (runbook)

**What runs:** R14 exactly (`ridgebook`, candle features, hold 288, grid 12, min_bps 15, cap 2, groups 4, min_pairs 5,
holdout on, the twelve `PAIRS`), refitted every 30 days by the harness's block rule, scored every hour, its decisions and
fills written to an append-only ledger. Code: `ft2/serve.py` (the header is the specification); tests:
`tests/test_p7_serve.py`; registration of the read: PLAN §8 R17. Nothing here tunes the model; a change to what is
served is a new registration.

**Where:** `fluxtrader2-serve` — e2-small (2 shared vCPU, 2 GB), 20 GB pd-balanced, Debian 12, `me-central1-b`,
≈ 13–15 USD a month, timezone UTC. A fluxtrader2 host: nothing of this project runs on fluxtrader1's collector VM. Same
venv as the work VM (`~/ft2-venv`, installed by `scripts/vm_setup.sh`), no Docker (the cloud exception of PLAN §6). Every
`vm.sh serve-*` verb addresses it regardless of `FT2_VM`.

**Needed from Vadim: nothing.** Claude operates it; the monthly check and R17's read are Claude's.

## The clock

| when (UTC) | unit | does |
|---|---|---|
| HH:00:15 | `ft2-decide` | fetch every closed 5m bar since the last stored one; refit if a block starts at HH:00; forecast the grid bar HH:00 from the tail of the market; write one row per pair to `decisions.csv` |
| HH:05:15 | `ft2-mark` | fetch bars; record best bid/ask of all twelve (`quotes.csv`); write the entry mark (close of the bar ending HH:05) for HH:00's taken decisions and the exit mark (close of the bar ending HH:05 tomorrow-relative: t + 5 min + 24 h) for those due; append settled funding events |
| 1st of month 01:30 | `ft2-check` | identity check 2: the harness re-run over the ledger's whole life on the appended candle file, diffed against `decisions.csv`; `bt.causal_check` on the current block; `checks/check_<date>.md`, `health.json.last_check` |

A decision is **taken** only if written before its entry bar closed (`decided_at` < t + 5 min); one written later (the
host was down) is recorded with its forecast and `skip = late`, never traded. A pair whose bar is missing at decision time
gets `skip = no_bar`. The book rule is the harness's: a taken decision blocks its pair until t + 288 bars.

**The refit schedule** is the harness's: `bt.blocks` for F3, F4, F5 (fold start + 2-day embargo, then every 30 days), then
every 30 days after F5's last block start (2026-08-31 → 2026-09-30 → 2026-10-30 → …). A refit fits on the market strictly
before the block start and on labels that ended before it, even when done late. Models: `output/serve/models/model_<block
start>.json` (μ, σ, coefficients per group, σ_ref, data_end). The scorer loads the JSON and never fits.

## Files on the host (`~/fluxtrader2/`)

| file | what |
|---|---|
| `data/serve/candles_seed.parquet` | the collector's 5m candles of the twelve from F0's start (`ft2 serve seed` on the work VM, 2022-08-18 → 2026-09-14 23:55, 4.68 M rows); never rewritten |
| `data/serve/candles_live.parquet` | closed bars appended from Binance futures REST `/fapi/v1/klines` (public, no key); a stored bar is never overwritten — a fetched bar that disagrees with a stored one is counted in `health.overlap_mismatch` |
| `output/serve/state.json` | `ledger_start` (written by `ft2 serve start`), params, pairs |
| `output/serve/decisions.csv` | one row per grid bar × pair: `id, t, symbol, group, f_bps, sigma_h, side, size, skip, model_id, decided_at` |
| `output/serve/marks.csv` | one row per taken decision × leg: `id, t, symbol, side, size, leg, mark_t, close, bid, ask, quote_at, funding_bps, marked_at` |
| `output/serve/quotes.csv` | `mark_t, symbol, bid, ask, quote_at` for all twelve at every mark time — the live spread |
| `output/serve/funding.csv` | `symbol, ts, rate` settled funding events |
| `output/serve/health.json`, `runs.log` | what `status` prints; one line per run |
| `output/serve/checks/check_<date>.md` | the monthly identity check 2 |
| `output/serve/replay/` | identity check 1 (run on the work VM, then copied): `replay.md`, `ledger.parquet`, `models/` |

No money number is computed on the host before R17's read (PLAN P7): `ft2 serve ledger` joins decisions and marks, it
does not price them. The read (R17, ≥ 600 priced trades and ≥ 6 months) prices `serve-pull`'s ledger with the harness's
`price()` and the live spread — code written at read time, not before.

## Install / reinstall (everything installed on the host, in order)

```sh
./fluxtrader2/scripts/vm.sh create-serve          # 1. the VM (e2-small, 20 GB) + venv; or on an existing host: FT2_VM=fluxtrader2-serve vm.sh setup
./fluxtrader2/scripts/vm.sh run serve seed --dst output/serve_seed/candles_seed.parquet   # 2. on the work VM: the seed from data/candles_5m.parquet
./fluxtrader2/scripts/vm.sh serve-seed            # 3. copy it VM-to-VM into the host's data/serve/
./fluxtrader2/scripts/vm.sh serve-run fetch       # 4. backfill from the seed's end to now; expect overlap mismatch 0 on every pair
./fluxtrader2/scripts/vm.sh bg p7_replay serve replay   # 5. identity check 1, on the WORK VM (needs output/backtest/r16_…/): pass required
./fluxtrader2/scripts/vm.sh serve-run start       # 6. go live: ledger_start = the next grid bar (refuses unless candles are caught up)
./fluxtrader2/scripts/vm.sh serve-install         # 7. push code + systemd timers (scripts/serve_install.sh; idempotent, re-run after any code change)
./fluxtrader2/scripts/vm.sh serve-status          # 8. next day: one line of health + the timers
```

After a code change: `vm.sh serve-install` (pushes and reloads the units; a running unit finishes first). After a
reinstall on a new host: steps 1, 3 (the seed is still on the work VM), 4, 7 — and copy `output/serve/` back from the
last `serve-pull` before step 7, or the ledger starts over (a restart is a new ledger; say so in PLAN).

## Operating

- **Health:** `vm.sh serve-status` — `updated / decide / mark / last bar / missing24h / decisions taken late open / marks
  entries/exits / model (age) / check / err`. Expect: decide and mark within the last hour, missing24h 0, late 0, err None,
  model age < 30 d, `check` True after the first month.
- **Logs:** `vm.sh serve-ssh 'tail -20 ~/fluxtrader2/output/serve/runs.log'`; `journalctl -u ft2-decide -n 50`.
- **Pull the ledger:** `vm.sh serve-pull` → local `output/serve/`.
- **Manual run:** `vm.sh serve-run decide|mark|check|status|ledger`.
- **A failed run** leaves `health.last_error`; the next run clears it if it succeeds. Marks catch up by themselves
  (idempotent); missed decide hours are recorded as `late` at the next run and never traded.
- **A failed monthly check** (`last_check.pass` false with unexplained differences) is a serving bug: the ledger is void
  back to the last clean month once the cause is fixed (R17: void and re-run, never salvage). Late/no_bar differences are
  explained, not failures.
- **Memory (measured on the host 2026-09-25):** the hourly decide loads only a 2,031-bar tail of the market; a refit is
  the expensive run — 935 MB peak, 13 s (the host has ≈ 1.6 GB available). Three things keep it there, all in
  `ft2/serve.py`, none in the model: `load_market` scatters streamed parquet row groups straight into the four wide
  arrays (a long frame of every row with Python-string symbols was 1.5 GB and OOM-killed the very first decide run at
  16:00:15); `last_bars` streams too; `ensure_chunked` copies the rows `RidgeBook._ensure` caches, which are otherwise
  views that keep every chunk's full 5-minute feature array alive (≈ 600 MB). The refit's coefficients are bit-identical
  to the one-shot fit. If a refit is ever OOM-killed again (`journalctl -u ft2-decide`), the model file is simply missing
  and the decisions of that block are recorded `late` until it exists: fit it on the work VM (`vm.sh run serve …` is not
  wired for that; `sv.fit`/`sv.save_model` by hand) and copy the JSON into `output/serve/models/`, or move the refit there
  monthly (PLAN P7).
- **Stop:** `vm.sh serve-ssh 'sudo systemctl disable --now ft2-decide.timer ft2-mark.timer ft2-check.timer'`; the VM stays
  on for the ledger files until pulled.

## Identity checks (the build is not done until these pass)

1. **Replay (before go-live):** `ft2 serve replay` on the work VM runs the live path — refit at the harness's block
   starts, JSON model saved and reloaded, one grid bar at a time on the tail of the market, the ledger's book rule —
   over F3+F4 and diffs it against R16's `forecast.parquet` (every `f_bps` and `sigma_h` cell within 1e-6, NaN with NaN)
   and `decisions.parquet` (the same accepted set: t, symbol, side, size). Result in `output/serve/replay/replay.md`
   and PLAN P7. **Run 2026-09-25 on the work VM: PASS** — 11,592 grid bars, 139,104 cells, max |Δ f_bps| 1.5e-10,
   max |Δ σ_h| 1.2e-10, 1,753 taken in both and identical, 7.5 minutes. On synthetic data the same identity is a unit test (`test_replay_reproduces_the_harness_forecasts_and_decisions_exactly`).
2. **Monthly check (live):** above; `taken_differ` and `cells_differ` must be 0 after explanation.
