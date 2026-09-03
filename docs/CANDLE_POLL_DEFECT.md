# The candle-poll defect — every stored candle since 2026-07-18 is a partial bar

**Status: 🟡 IN REPAIR, found and fixed 2026-09-03.** The collector no longer stores partial
bars (deployed to `fluxtrader-1`, commit `0b1d743`) and the history repair has been run. The
consequences — re-scoring the served checkpoint, re-deriving the frozen constants, restarting
the forward clock — are §7 steps 5–8 and are in progress. Decisions Q1/Q2/Q3 (§6) are answered.
Indexed in [BACKLOG.md](./BACKLOG.md). Probe scripts: `ml/train/output/probe/candle_cliff.py`,
`candle_vs_binance.py`, `candle_damage_scope.py`, `conf_vs_cliff.py` (gitignored, `EXPLORATORY`).

---

## §0 — In plain language, and the bottom line

**What was found.** Since the collector went live on 2026-07-18, every 5-minute candle it
stores is a snapshot of the bar's **first minute**, not the finished bar. Volume is stored at
about **10%** of the true figure, the high–low range at about **30%**, and the close is the
price roughly 30 seconds after the bar opened. The candles are what the model reads, so since
2026-07-18 the model has been shown a market that looks ten times quieter than it is.

**Why it matters.** The project's standing explanation for the two-month silence is that "the
model is confident when the market moves, and the market has been quiet" — with the puzzle that
Bitcoin moved 8% on 2026-08-20/21 and the model did not react. It did not react because the
candles it was shown for those days carry a tenth of the volume and a third of the range. **The
silence is a data defect, not a regime fact**, and the forward paper test has measured nothing
since it began, because no bar it scored was a real bar.

**Bottom line.** Nothing is lost: candles are fully backfillable from Binance, so the whole
period can be repaired. Until it is, the live policy is inert for a reason that has nothing to
do with the policy, and the "wait for volatility" plan cannot work.

---

## §1 — The mechanism

`apps/fluxtrader/lib/fluxtrader/market_data/collector.ex`:

* `collect_candles/2` polls `/fapi/v1/klines` with `limit: 5` every 60 seconds. The newest
  kline in every response is the **still-forming** bar.
* `insert_candle/4` writes each kline with `on_conflict: :nothing` on
  `(symbol, interval, open_time)`. So a bar is stored the **first time it is seen** — within
  a minute of its open — and never updated when it closes.
* The startup backfill (`backfill_candles/3`, `limit: 500`) uses the same insert, so it cannot
  repair a row that already exists. The only complete post-July bars are those the app was
  *not running* to see form: 2026-07-20 is the one intact day in the export, and it is an
  app-downtime day repaired by the restart backfill.
* `ml/train/backfill_history.py` uses `ON CONFLICT … DO NOTHING` and only fetches ranges its
  gap detection reports as missing. The corrupt range has rows, so it reports "already
  covered". **The existing repair tool cannot repair this.**

Before 2026-07-17 every candle in the DB came from the Python backfill of closed klines and is
exact. The training windows of every checkpoint end 2025-12-10 and are unaffected.

---

## §2 — The evidence

Stored candles were joined to Binance klines at identical `open_time` (fetched from the
`ml_analysis` container). Ratios are *stored / true*.

**BTCUSDT 5m, 2026-08-20, 288 bars:**

| quantity | p5 | p25 | **median** | p75 | p95 |
|---|---:|---:|---:|---:|---:|
| volume ratio | 0.006 | 0.039 | **0.112** | 0.198 | 0.387 |
| high−low ratio | 0.031 | 0.143 | **0.306** | 0.493 | 0.805 |

`open` equal in 288/288 bars; `close` equal in **0/288**; \|close − true close\| median
**7.4 bps**, p99 **47.9 bps**.

**BTCUSDT 1m, same day, 500 bars:** volume ratio median 0.654, close equal in 24%. The 1m
poll catches the forming bar at a random point in its 60 s, so 1m bars are half-filled on
average; 5m bars are caught in their first fifth; 15m and 1h bars are worse still.

**All twelve pairs, 5m, same day:** volume-ratio medians **0.089–0.112**, exact matches
**0/288** for every pair.

**Control, 2026-06-20 (pre-collector):** 288/288 bars exact on volume and close.

**Extent:** of the 43 days from 2026-07-18 in the export (`ml/train/output/m3_0b/`), **42 are
corrupt**; the exception is 2026-07-20. The export was pulled from `fluxtrader-1` on
2026-08-29/30, so this is the VM's data, not an export artefact.

**The weekly picture, BTCUSDT 5m, mean of daily medians:**

| week of | volume | high−low / close |
|---|---:|---:|
| 2026-06-28 | 371 | 0.00153 |
| 2026-07-12 | 297 | 0.00123 |
| 2026-07-19 | 258 | 0.00098 |
| 2026-07-26 | **66** | **0.00035** |
| 2026-08-09 | **22** | **0.00017** |
| 2026-08-16 (the "8% move" week) | **20** | **0.00014** |

### What the model did

Daily 98th-percentile confidence at the 240m head, per seed, mean over days:

| seed | Jun 1 – Jul 17 | Jul 18 – Aug 18 | day-to-day sd of p98, before → after |
|---|---:|---:|---|
| `20260818T185438Z` | 0.602 | 0.554 | 0.037 → **0.005** |
| `20260819T142759Z` (served) | 0.605 | 0.557 | 0.058 → **0.004** |
| `20260820T025723Z` | 0.589 | 0.548 | 0.041 → **0.013** |

The *level* drop could still be read as a calm market. The **collapse of day-to-day
dispersion by 7–14×** cannot: a model that sees a tenth of the volume and a third of the range
on every bar has nothing left to vary on. This is the "confidence dispersion collapses with
volatility" observation in NEXT_TRAINING_PLAN's top block, with the cause corrected.

### Why the earlier checks did not catch it

The 2026-09-01 investigation compared **live confidence to the offline split's confidence**
and found them identical — correctly. Both are computed from the same stored candles. A defect
in the stored inputs is invisible to any check that compares two outputs of the same input.
The check that was missing is *stored candle vs the exchange's own closed kline*, which is what
§4 adds.

---

## §3 — What this invalidates, and what it does not

### Invalidated or must be re-read

1. **"The silence is a regime fact, not a bug."** Stated in BACKLOG ("The arrival-rate
   finding"), REAL_MONEY_TRACK §1, NEXT_TRAINING_PLAN's top block, M3_PLAN §0.8 and
   M3_PROTOCOL §8.0. The three hypotheses those sections killed (serve drift, book features,
   seed-specificity) are still dead; the one they did not test is the one that is true. The
   dry spell from 2026-06-29 to 07-17 (19 days) is a genuine calm stretch inside the split's
   normal range; everything after 07-18 is the defect.
2. **Every live prediction since 2026-07-18**, hence the whole forward paper test: the twelve
   discarded trades *and* the zero-trade stretch since the 2026-08-31 restart. Neither
   measured the policy. `policy_bars` since 08-29 is a record of the model reading corrupt
   input and should be kept, labelled as such, not used.
3. **The last 31 days (2026-07-18 → 08-18) of every eval dump's validation split** — ~12% of
   the split, the tail of calendar window 4. The frozen cut `0.6318973898887634` and the
   regime ladder were derived over a split that includes them; after repair they will move
   (small, direction not obvious: the corrupt days contribute artificially low confidence, so
   some of their bars would enter the top 2% once repaired and the cut would rise). Per
   M3_PROTOCOL §8.3 C4 the constants are re-derived from the checkpoint's own split; **this is
   a data correction on the same checkpoint and the same rule, not a re-pick of a searched
   dimension**, and it must be recorded as such.
4. **Any analysis that read candle `high`/`low`/`volume` in the book era (2026-08-05 → 28).**
   M3-0b's brake pricing uses intra-hold high/low; only ~4% of its trades fall in the era, so
   the +10.5 bps is probably robust but should be re-run. B1/B2 read closes for labels — a
   *consistently* early-sampled close leaves a 4h return nearly intact (both ends shift
   together) — but their `√t` sd measurement at 5m and the "+62 bps drift" were measured on
   these closes and should be re-run after repair before being quoted again.
5. **The live `btc_absret_1d` regime observable** reads DB closes. A 24h return from closes off
   by ~7 bps is off by ~10 bps — negligible against quintile edges of 0.4–2.5%. Not a problem.

### Not affected

* `orderbook_snapshots`, `orderbook_levels`, `market_trades`, `funding_rates`,
  `open_interest`, `long_short_ratios` — point-in-time inserts, no forming object.
* The training windows of every checkpoint (all end 2025-12-10).
* M3-4's execution-cost study (book and tape only).
* M3-2, M3-3, T6 verdicts — measured on the split whose corrupt tail is 12%, in the window
  (w4) that was *not* the binding one (w3 is). Worth re-scoring after repair; unlikely to
  change a verdict.

---

## §4 — The fix, the repair, and the guard

Three parts. None changes the rule.

**1. Fix the collector (`collector.ex`, `insert_candle/4`).** Replace on conflict so the
closed bar overwrites the forming one:

```elixir
Repo.insert(candle_changeset,
  on_conflict: {:replace, [:open, :high, :low, :close, :volume, :close_time]},
  conflict_target: [:symbol, :interval, :open_time])
```

With `limit: 5` and a 60 s poll, every bar is re-seen after it closes (a 5m bar is in the
window for ~25 minutes), so this alone stops the bleeding for new bars. Add a collector test:
insert a kline, insert the same `open_time` with a larger volume, assert the row updated.

**2. Repair the history.** Re-pull 1m / 5m / 15m / 1h for all twelve pairs from
**2026-07-17 00:00 UTC** to now with `ON CONFLICT … DO UPDATE`. `backfill_history.py` needs
a `--repair-from <date>` mode that ignores gap detection and upserts; ~48 days × 12 pairs at
1m is ~830k rows, well within the endpoint's weight budget in minutes. Then re-run
`candle_vs_binance.py` for all twelve pairs on two post-repair days and require 100% exact.

**3. Add the guard that was missing.** ✅ **BUILT 2026-09-03 — see
[CANDLE_GUARD.md](./CANDLE_GUARD.md)** for what it does and how to install it on another
instance. A daily integrity check that compares yesterday's stored closed candles to a fresh
kline pull per pair; it runs on `fluxtrader-1` under the systemd timer `candle-guard.timer`,
is quiet on success and alerts on Telegram on failure. It would have fired on 2026-07-19.
Separately, the served model's feature z-scores against the checkpoint's own `norm_stats`
are a cheap drift monitor — a live column sitting at −2σ for a month is exactly this defect's
signature and is visible without any external call.

**4. A second live/offline mismatch the fix does not remove (separate, smaller).**
`serve.py`'s `build_tensor` takes the last `max_rows` candles including the **currently
forming** bar as the newest timestep. Offline, the newest bar in every training window is
complete. After the fix that bar is updated every minute but is still partial at inference
time. Drop any candle whose `close_time` is in the future before building the window. This
is a serve-path change, not a rule change; it should be pre-registered as a fidelity fix
(the 2026-08-31 pattern) and measured with `m3 fidelity` before and after.

---

## §5 — After the repair, in order

1. **Live inference is correct on the next bar**, and fully clean after 32 hours (the LSTM's
   window). Expect `/api/health`'s confidence statistics to change immediately.
2. **Re-run eval for the served checkpoint** (`20260819T142759Z`, and the other two seeds for
   the family) over the repaired DB, producing new dumps. Then, per C4, re-derive the cut and
   ladder from the repaired split, update `policy.ex` and `config_test.exs`, re-run
   `./scripts/m3.sh -m m3 validate` and `fidelity`. Record it as *data correction, same
   checkpoint, same rule*.
3. **Re-read the arrival question on real data.** Did the cut fire on Aug 20/21 once the
   candles are true? That single number decides whether the forward test is regime-blocked at
   all. Everything the arrival-rate finding says about July 18 onward is void until then.
4. **Restart the forward clock** (backup + `TRUNCATE paper_trades`, which is empty; keep
   `policy_bars`, mark the pre-repair range). The rule is the same; the inputs were not.
5. **Re-run M3-0b and B1/B2** on the repaired export (`scripts/gcp_m3_export.sh` then
   `m3 sidetable`, `bookera`, `bookaudit`, `bookregime`). Combine with the parked B1
   re-export over the 8 main pairs' true span, which is one export anyway.

---

## §6 — The decisions, each as its own question

> **Answered 2026-09-03: Q1 (a), Q2 (a), Q3 (a)** — all three as recommended. Fix and repair
> both applied now; the served checkpoint and its two family seeds are re-scored on repaired
> data and the constants re-derived under C4; the serve-path forming-candle exclusion stays
> **separate**, pre-registered as a fidelity fix and measured, and remains parked in BACKLOG.

**Q1. Apply the collector fix and the history repair now?** — (a) **yes, both, now**
(recommended: the fix changes no rule, the repair loses nothing, and every day un-repaired is
another day of the forward test measuring nothing), (b) fix only, repair later, (c) neither
until discussed. Note (b) leaves the served model's 32-hour window reading corrupt bars
until they age out, and leaves the eval tail wrong.

**Q2. Re-run the served checkpoint's eval on repaired data and re-derive the constants (§5
step 2)?** — (a) yes, it is the same rule on corrected data and C4 requires it, (b) keep the
constants as frozen and fix only the live inputs, accepting that the served cut was derived
on a split with a corrupt tail. **(a) recommended.** It needs a GPU or a long CPU eval run;
it is one `gcp_train.sh`-style job, not a retrain.

**Q3. Bundle the serve-path forming-candle exclusion (§4 item 4) into the same change, or
keep it separate?** — (a) separate, pre-registered as a fidelity fix and measured
(recommended; it is a distinct mismatch with its own effect size), (b) bundle it.

---

## §7 — Implementation checklist, in order

*Written 2026-09-03 for a later session. Every command is real; where it runs is stated.
Nothing here changes the rule. Steps 1–4 are the fix; 5–8 are the consequences.*

**Progress, 2026-09-03.** Steps 1–3 are DONE (commits `0b1d743`, `467b918`). Step 4 is the
verification and now has a committed tool. Steps 5–8 are open. What actually happened, and the
two traps found on the way, is recorded inside each step below.

### Step 1 — Fix the collector (local, then commit)

1. `apps/fluxtrader/lib/fluxtrader/market_data/collector.ex`, `insert_candle/4`: change
   `on_conflict: :nothing` to
   `on_conflict: {:replace, [:open, :high, :low, :close, :volume, :close_time]}`, keeping
   `conflict_target: [:symbol, :interval, :open_time]`. Both the 60 s poll and the startup
   backfill go through this function, so one change covers both.
2. Add `apps/fluxtrader/test/fluxtrader/market_data/collector_candle_test.exs`: insert a
   kline for one `open_time`, insert the same `open_time` with a larger volume and a
   different close, assert the stored row carries the second values. This is the regression
   test for the whole defect.
3. Run the suite locally:
   ```sh
   docker compose run --rm -e MIX_ENV=test -e POSTGRES_HOST=postgres app mix test
   ```

✅ **DONE 2026-09-03 (`0b1d743`).** The write moved into a public `store_candle/1` so the test
drives the real path rather than a copy of it. The test was confirmed to be a real regression
test, not a tautology: with `on_conflict: :nothing` restored it fails, storing volume 12.0 where
the closed bar carries 118.0. Full suite 100 tests, 0 failures.

### Step 2 — Add a repair mode to the backfill (local, then commit)

`ml/train/backfill_history.py`:

1. `upsert_candles/3`: add a parameter `replace: bool = False`; when set, the SQL ends
   `ON CONFLICT (symbol, interval, open_time) DO UPDATE SET open = EXCLUDED.open, high =
   EXCLUDED.high, low = EXCLUDED.low, close = EXCLUDED.close, volume = EXCLUDED.volume,
   close_time = EXCLUDED.close_time`.
2. Add `--repair-from <YYYY-MM-DD>`: when given, skip `coverage_ms` / `gap_ranges_ms` and
   fetch the full range from that date to now, upserting with `replace=True`. Default
   behaviour is unchanged.
3. Add `5m` to the default `--intervals` (it is `1m,15m,1h` today; the served model reads
   5m, and 5m is the worst-hit interval after 15m/1h).
4. ⚠️ Do not stop at the twelve served pairs if the whitelist is wider — repair every symbol
   in `candles` from 2026-07-17. Check with the ad-hoc query pattern in NEXT_TRAINING_PLAN
   §0.1: `SELECT DISTINCT symbol FROM candles`.

✅ **DONE 2026-09-03 (`0b1d743`, `467b918`).** All four points, plus two that were not in the
plan:

* **Both modes now refuse a kline whose `close_time` is in the future.** Without this the
  backfill could itself plant the very partial row it exists to repair — the same defect by
  another route. It reports the count as `unclosed-skipped`, and it is always 0 or 1.
* **`gcp_backfill.sh` grew the same `--repair-from` flag**, so the repair runs through the
  established tmux + `gcp_backfill_status.sh` path rather than an ad-hoc ssh command. ⚠️ The
  launcher's 8-pair `--symbols` default is deliberately NOT applied in repair mode: an empty
  list makes `backfill_history.py` repair every symbol in `candles`. Inheriting the 8-pair
  default there would have quietly left four of the twelve collected pairs corrupt.

The per-row `RETURNING (xmax = 0)` reports `inserted` vs `updated` separately, which is what
distinguishes a genuine gap fill from a repair — see the counts in step 3.

### Step 3 — Deploy and repair (on `fluxtrader-1`)

```sh
# on fluxtrader-1
cd ~/trading_agent
git pull
docker compose up -d --build app                 # picks up the collector fix; collection continues
docker compose --profile ml run --rm ml_trainer \
  python backfill_history.py \
    --symbols BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT,ADAUSDT,AVAXUSDT,LINKUSDT,XRPUSDT \
    --intervals 1m,5m,15m,1h --repair-from 2026-07-17
```

Run it inside `tmux` (see `scripts/gcp_backfill.sh` for the pattern) — 1m over 48 days at
twelve pairs is ~830k rows and takes tens of minutes, not seconds. `ml_inference` needs no
restart: it reads the DB on every prediction.

✅ **DONE 2026-09-03.** The one-liner that was actually run, from the Mac:

```sh
./scripts/gcp_backfill.sh --repair-from 2026-07-17 --intervals 1m,5m,15m,1h
```

It resolved to all twelve symbols on its own. The app was rebuilt first
(`docker compose up -d --build app`) and came back healthy on all twelve pairs.

**Confirmed:** `ml_inference` needs no restart — `serve.py`'s cross-pair market inputs are
cached for `MARKET_CACHE_TTL_S = 30`, so repaired candles are picked up within 30 seconds.

⚠️ **The repair is slower than "tens of minutes."** `upsert_candles` executes one statement per
row, which measured **~90 rows/s** on the always-on e2-small: the first unit (1000PEPEUSDT 1m)
took 12.9 minutes for 69,773 rows, and the whole job is ~1.07M rows, so budget **~3.5 hours**.
It is unattended in tmux and idempotent, so this is a "leave it running" cost, not a risk — but
do not schedule the step-5 eval expecting the DB to be ready in twenty minutes. If this is ever
run again on a larger range, batch the inserts first; the row-by-row loop is the whole cost.

**What the counts mean.** The first unit returned `inserted=0 updated=69773` — every 1m row
from 2026-07-17 onward already existed and was overwritten. That is the expected shape here and
is itself evidence for §1: the range was never *missing* data, which is exactly why the old
gap-detecting backfill reported "already covered" and did nothing.

### Step 4 — Verify the repair

The gitignored probes read the **parquet export**, so they can only verify the repair after a
re-export, and they cannot be used as a standing guard. `ml/train/verify_candles.py` (committed,
`0b1d743`) checks the **database** directly against Binance and is the primary verification:

```sh
# on fluxtrader-1, against the repaired DB itself — the authoritative check
cd ~/trading_agent && docker compose --profile ml run --rm ml_trainer \
  python verify_candles.py --intervals 5m --days 2026-07-21,2026-08-20,2026-09-01
```

It exits non-zero if any (symbol, interval, day) fails, so it doubles as the cron guard of
§4 item 3 via `--since-yesterday`.

**Pass condition:** every pair reports `exact vol=1.000 close=1.000 high=1.000 low=1.000` with
no `MISSING`. Check at least one day *before* the deploy (proves the repair) and one day *after*
(proves the collector fix), so the two are verified separately.

Then re-export and re-run the parquet probes, which is what steps 5–8 consume:

```sh
./scripts/gcp_m3_export.sh                                  # re-pull the price path
./scripts/m3.sh output/probe/candle_vs_binance.py           # BTC 5m/1m, one day
./scripts/m3.sh output/probe/candle_damage_scope.py         # all twelve pairs
```

⚠️ The probes are gitignored; if they are gone, §2 of this document is their specification.

**Verified on a local mirror before the VM run**, which is why the repair was trusted: repairing
BTCUSDT 5m from 2026-07-18 moved 07-21's mean volume from 71 to 482 and every checked day to
288/288 exact on volume, close, high and low, while the same check on a pair not yet repaired
still reported a 0.116 median volume ratio — the §2 signature, reproduced and then removed.

#### ✅ The collector fix is verified on the VM independently of the repair

An hour into the history repair — with only the first of twelve symbols processed — the guard
reported **all twelve 5m checks passing** while eleven of twelve 1m checks failed. The repair
cannot explain that, and the explanation turns out to be a free bonus of the fix:

**the app restart repaired ~42 hours of 5m data by itself.** `backfill_candles/3` requests
`limit: 500` on startup and writes through the same `store_candle/1`, so on the 10:48 UTC restart
it re-fetched the last 500 closed bars per pair per interval and *replaced* them. At 5m, 500 bars
is 41.7 hours. At 1m it is only 8.3 hours, which is why 1m still failed.

The prediction that follows is exact, and it holds:

| BTCUSDT 5m | exact vol | median vol ratio | |
|---|---:|---:|---|
| 2026-09-02 | **1.000** | 1.000 | inside the 500-bar window |
| 2026-09-01 | 0.285 | 0.196 | the boundary day |
| 2026-08-30 | 0.000 | **0.101** | outside it — the untouched defect |

500 bars back from 10:48 UTC lands at 2026-09-01 17:05, which is the last **28.8%** of that day;
the measured exact fraction is **28.5%**. So the collector fix is confirmed working against live
exchange data on the VM, by a mechanism entirely separate from `--repair-from`.

The 08-30 row is also the first reproduction of §2's evidence **against the VM's own database**
rather than the parquet export: median volume ratio 0.101, zero exact closes. The original
finding stands unaltered.

### Step 5 — Re-score the served checkpoint on repaired data (GPU VM, one job)

⚠️ **The eval does not read the VM's live DB — it restores a pg_dump cached in the bucket.**
`ensure_dump` (`gcp_common.sh`) reuses `/var/tmp/fluxtrader_dump_cache.sql.gz` on the always-on
VM whenever it is younger than `DUMP_MAX_AGE_MIN` (30). **A cache written before the repair
finished would silently re-score the corrupt data and look completely normal.** Before the first
eval, delete it and confirm the fresh dump is post-repair:

```sh
gcloud compute ssh fluxtrader-1 --zone me-central1-b \
  --command "rm -f /var/tmp/fluxtrader_dump_cache.sql.gz"
```

This is the same class of error as the defect itself: a check that cannot see the input it is
actually reading. Do not skip it.

```sh
./scripts/gcp_train.sh --eval-only m2_multi_20260819T142759Z_a186182b.pt
./scripts/gcp_status.sh
./scripts/gcp_logs.sh <run_id> > logs/E-repair-s2.log
```

Then the other two family seeds the same way (`20260818T185438Z`, `20260820T025723Z`), one
at a time — `gcp_train.sh` runs are serial. Copy the three new `eval_preds_<run>.parquet`
dumps into `ml/train/output/eval_dumps/` **under new run ids**; do not overwrite the
originals, which are the record of what the corrupt tail looked like.

**Bring back:** the three logs, and for each the `Fixed-coverage P&L` table and the
`SERVED GATE (C13, coverage-targeted)` line. The only expected movement is in the last 31
days of the split (calendar window 4's tail).

### Step 6 — Re-derive the constants and re-validate (local)

```sh
./scripts/m3.sh -m m3 validate                     # must pass FIRST (C3)
./scripts/m3.sh -m m3 fidelity --universe 8        # arm A on the repaired dump → new cut and ladder
```

Copy the new cut and ladder into `policy.ex` (`@frozen_threshold`, the ladder edges) and
`config_test.exs`, and record them in M3_FIDELITY_RESULTS §6 as **"data correction, same
checkpoint, same rule, 2026-09"**. Re-run `m3 search` scoring for the M3-2 winner on the new
dumps and note the movement against M3_2_RESULTS — a reading, not a re-search.

### Step 7 — Restart the forward clock (on `fluxtrader-1`)

Same procedure as M3_FIDELITY_RESULTS §6.4: back up and `TRUNCATE paper_trades` (it holds
nothing under the frozen rule), restart the app, verify `/api/health` shows the **new**
`frozen_threshold`. **Keep `policy_bars`**, and record in BACKLOG the date range
(2026-08-29 → repair date) during which its rows were computed from partial candles.

### Step 8 — Re-run what read book-era candles (local, no GPU)

```sh
./scripts/m3.sh -m m3 sidetable && ./scripts/m3.sh -m m3 bookera
./scripts/m3.sh -m m3 bookaudit && ./scripts/m3.sh -m m3 bookregime
```

Bundle with the parked B1 re-export over the 8 main pairs' full span (BACKLOG, "B1's blocker
may already be gone") — it is the same export. Compare M3-0b §4 (the brake's 10.5 bps) and
B1's per-horizon sd against the published values before quoting either again.
