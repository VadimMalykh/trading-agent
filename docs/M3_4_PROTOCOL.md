# M3-4 — the pre-registered protocol for the execution-cost study

**Status:** ✅ **COMMITTED 2026-08-28, before any fill number was computed.**
**Applies to:** M3-4 only. [M3_PROTOCOL.md](./M3_PROTOCOL.md) stays frozen and unamended; this file sits *under* it, as [M3_3_PROTOCOL.md](./M3_3_PROTOCOL.md) does.
**Related:** [M3_PLAN.md](./M3_PLAN.md) §2 M3-4, §3.3, §4 risk #2 · [M3_2_RESULTS.md](./M3_2_RESULTS.md) (the grid this re-scores) · [M3_3_PROTOCOL.md](./M3_3_PROTOCOL.md) §0 (the no-editing rule this inherits)

**Reproduce every count quoted below, in a clean session:**

```sh
./scripts/gcp_m3_export.sh                 # pulls the book/tape/price slice off fluxtrader-1
./scripts/m3.sh -m m3 bookprep             # every number in §1 — no fill number, by design
```

The export defaults to **20 ladder levels a side**. §1's audit needs only the touch, but §2.5
walks the ladder to price slippage and five levels cannot hold a $10k order on the thin pairs —
1000PEPE keeps about $823 at the touch. Depth is nearly free (the server cost is detoasting the
100-level jsonb regardless), so the deep export is taken once rather than twice.

---

## §0 — Why a third protocol exists, and the rule it inherits

M3_PROTOCOL §4.4 fixes what a *policy* must achieve. It says nothing about how execution is
measured, because when it was written execution was a constant: `MAKER_COST_BPS,
TAKER_COST_BPS = 5.0, 14.0` in `ml/train/m3/metrics.py`, two numbers assumed and never tested.

M3_PLAN §4 ranks that assumption as risk #2 and explains why it outranks every remaining
modelling knob: **it can invalidate results already published, in both directions.** The cov05
slice is −5.09 net at taker and +3.91 at maker. The M3-2 winner is +15.0 at taker and +27.1 at
maker. Nothing else open can move a published number by 12 bps.

**The rule, identical to M3_3_PROTOCOL §0: this file is not edited once the first fill number
exists.** An observation that a different fill window, queue model or horizon would have been
better is a proposal for a future pre-registration, never a re-scoring of this run.

### 0.1 The honest caveat about this document's status

Like M3-3's, this protocol is not written in ignorance. Three things were measured **before**
it was drafted, and all three are reported in §1:

1. the ladder's true sampling interval, because M3_PLAN's stated 5s was wrong;
2. the tape's censoring rate, because it was not known to exist at all;
3. the touch spread, because the per-pair sample floor and the resting price are defined in
   terms of it.

**None of them is a fill rate, a queue drain, an adverse-selection number or an effective
cost.** That split is the whole point: §1 is *what the data can support*, §2–§5 are *the
study*, and `m3 bookprep` computes only the former. The response to knowing §1 is to **fix**
§2's choices against it by citation, not to leave them free to be tuned once fills are seen.

### 0.2 🔴 The one design principle everything below serves

**Every defect in §1 must be made to bias the answer AGAINST maker execution.** The data is
worse than M3_PLAN believed, and a study built on it can be honest in exactly one way: by
arranging its approximations so that the errors all point the same direction, and then saying
what that direction is worth.

The consequence, stated once and relied on throughout:

> **A maker verdict is safe; a taker verdict is not.** If maker execution wins on these
> measurements, it wins on a lower bound and the real edge is larger. If maker execution
> loses, the study has *not* shown that maker execution is unobtainable — only that this data
> cannot show it, and §5.3's power clause governs what may be concluded.

This is [M3_PLAN §4's retraction lesson](./M3_PLAN.md) applied in advance: a pre-registered
criterion protects against shopping for a favourable result, it does not make an underpowered
test informative.

---

## §1 — What the data actually is

Three of M3_PLAN §2 M3-4's descriptions of the source are wrong, and each one changes what a
fill number means. They are recorded here so the study's assumptions are stated rather than
inherited.

### 1.1 The ladder is not sampled every 5 seconds

`collector.ex` sets `@book_interval_ms 5_000`, and M3_PLAN read that as a 5s series. It is not.
`handle_info(:poll_book, …)` walks **every pair serially** with a synchronous REST call and
only *then* schedules the next poll 5s later, so the true period is

    5s  +  (time to fetch and insert the whole universe)

which means it is a function of how many pairs are collected. Measured on the VM:

| era | pairs | median gap | mean gap | p95 | max |
|---|---:|---:|---:|---:|---:|
| 2026-08-05 .. 08-13 | 8 | **7.6 s** | 9.0 s | 16.2 s | 83 s |
| 2026-08-14 .. 08-27 | 12 | **9.0 s** | 12.2 s | 23.4 s | 294 s |

The step lands exactly on 2026-08-14, the day ADA/AVAX/LINK/XRP were added, and its size
(≈1.4 s for 4 pairs, ≈0.35 s/pair) matches the per-pair fetch latency visible in the
staggered write timestamps within a single loop. **Nothing is being dropped and no write is
conditional** — this is scheduler drift, and M3-4a's open question in M3_PLAN §2 is closed by
it. (`ts` is a microsecond wall clock, so the `on_conflict: :nothing` on `(symbol, ts)` never
fires; it is not deduplicating anything.)

**What this protocol assumes:** the ladder is an **irregular ~9s series with a heavy right
tail**, not a 5s grid. Consequences are enforced in §2.4 (staleness cap) and §2.2 (why the
fill window may not be shorter than 30s).

### 1.2 🔴 The tape is right-censored, and nobody knew

`collect_trades/2` calls `agg_trades` with `limit: 200`. Binance returns the **most recent**
200 aggregate trades, so when a pair prints more than 200 in one poll interval, the *oldest*
ones are silently discarded — and `high`, `low`, `volume`, `buy_volume`, `sell_volume` are all
computed from what survived.

Measured over the 12-pair era, share of windows at the cap:

| BTC | ZEC | ETH | HYPE | PEPE | XRP | SOL | DOGE | LINK | WLD | AVAX | ADA |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **30.6%** | 29.2% | 28.0% | 15.2% | 10.8% | 4.9% | 1.4% | 0.75% | 0.62% | 0.36% | 0.25% | 0.12% |

This is the single most important fact in the document. Censoring is **concentrated in busy
windows** — the windows in which a resting order actually fills — so a naive fill rate computed
from `low`/`high` is biased **downward, and not at random**. Per §0.2 that direction is
acceptable and the study leans on it deliberately, but the censoring flag must be carried
through every table: **`trade_count == 200` is a censoring indicator, not a count**, and §6
requires the fill rate to be reported separately on censored and uncensored windows so the
size of the bias is visible rather than assumed small.

### 1.3 `window_start` is a label, not a window

`aggregate_trades/2` sets `window_start = floor_to_5s(ts of the LAST trade in the batch)`,
while the batch itself covers everything since the previous poll — about 10 s. So consecutive
`window_start` values are typically **two** 5s buckets apart (median gap 10.0 s, p95 25.0 s;
only ~15% of consecutive rows are adjacent 5s buckets, and ~17% are ≥20 s apart).

The distinction that matters, and it is not the obvious one:

* the tape's **volume coverage is complete** modulo §1.2's censoring — every trade since the
  last poll is in some row, because the batch is filtered by `last_id` and not by time;
* the tape's **time attribution is coarse** — a row tells you a trade happened in the ~10 s
  before its label, not in the 5 s after it.

**What this protocol assumes:** a tape row covers the half-open interval *(previous row's
`window_start`, this row's `window_start` + 5s]*, and its aggregates are attributed to that
whole span. This is the reading that preserves volume; the "5 s beginning at `window_start`"
reading would discard roughly half the tape and is rejected. The ±10 s attribution error it
leaves is why §2.2 forbids a fill window shorter than 30 s.

### 1.4 Book staleness and the ladder's own clock

`orderbook_levels` carries `event_time` and `transaction_time` (Binance's clocks) next to `ts`
(ours). `ts − event_time` is one-way latency plus insert time, and it bounds the resolution any
fill claim can carry. `m3 bookprep` §B reports it per pair; §2.4's staleness cap is set from it.

### 1.5 Extent, and the two depths of evidence

| | pairs | ladder from | days |
|---|---|---|---:|
| served universe | BTC, ETH, SOL, DOGE, 1000PEPE, WLD, HYPE, ZEC | 2026-08-05 03:41 | **22** |
| added later | ADA, AVAX, LINK, XRP | 2026-08-14 03:12 | 13 |

**The primary result is pre-registered on the 8 served pairs only.** The four short-window
pairs are reported in a separate table and are never pooled with the eight (M3_PLAN §2 M3-4).
The 8-vs-12 universe question is closed (§0.6) and nothing here reopens it.

The whole 22-day window sits **inside** the era every M3 number is scored on, which is what
makes the measured cost substitutable into M3-2's grid without a period mismatch.

### 1.6 🔴 The touch spread is near zero on the majors, and that reshapes the question

`m3 bookprep` §E, median touch spread in bps of mid, and §F, median notional resting at the
touch (one representative day; the full-window version is what the results cite):

| | BTC | ETH | ZEC | HYPE | PEPE | XRP | LINK | SOL | DOGE | AVAX | WLD | ADA |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| spread (bps) | **0.01** | 0.04 | 0.13 | 0.12 | 0.26 | 0.70 | 0.85 | 0.96 | 1.13 | 1.34 | 2.45 | 4.69 |
| touch ($k) | 402 | 238 | 3.0 | 4.2 | 0.8 | 23 | 2.7 | 65 | 14 | 4.2 | 2.9 | 28 |

Two consequences follow arithmetically, before any fill is measured, and they change what
this study is even asking.

**(a) On the majors the maker question is a FEE question, not a spread question.** A resting
order's gross advantage per side is `(taker_fee − maker_fee) + 2 × half_spread`, so the
round-trip ceiling is

    Δ_max  =  4 bps  +  4 × half_spread

which is **4.02 bps on BTC** and 4.08 on ETH — essentially all of it the 2 bps/side fee
differential — against 13.4 bps on ADA. **The 9 bps that `metrics.py`'s 14-vs-5 implies is
therefore unobtainable on six of the eight served pairs no matter how good the fills are.**
That is not a result of the study; it is a bound on what the study could possibly find, and
pre-registering it stops a small measured Δ from being read as a surprise later.

**(b) The 14 bps taker assumption is now the more suspicious of the two.** It decomposes as
2 × (4 bps fee + 3 bps slippage). At a 0.01 bps spread and $400k resting at the touch, a
$10k order on BTC crosses for **0.005 bps**, not 3 — the assumed slippage is off by nearly
three orders of magnitude, and it is off in the direction that makes every published M3
number **too pessimistic**. This is why §5.1 pre-registers **C_taker against 14** as a
decision quantity in its own right and not merely as the baseline of a difference: on this
evidence the taker assumption may move the grid further than the maker one does.

Because of (b), §2.6 **measures** slippage by walking the ladder for the order size rather
than assuming a number, and §5.4's ban on editing `metrics.py`'s constants applies to the
taker constant exactly as it does to the maker one.

---

## §2 — The measurement design

### 2.1 What is being compared — two execution policies, one trade population

The study does **not** compare "trades that filled at maker" against "trades that filled at
taker". Conditioning on a fill selects on the outcome, and it is the standard way a maker study
flatters itself: the decisions where a passive order fills are disproportionately the ones
where price came to you, which is also where the alpha was worse.

Instead, two complete execution policies are priced over the **identical** set of decisions:

* **TAKER** — at decision time *T*, cross. Buy at the best ask, sell at the best bid.
* **MAKER→TAKER** — at *T*, rest at the touch on our own side (buy → best bid, sell → best ask).
  If filled within *W*, we are done. **If not filled within *W*, cross at the prevailing touch
  at *T+W*.** Never abandon the decision.

The fallback branch is what makes the comparison honest. Every decision produces a trade in
both arms, so the re-score in §5.2 runs on M3-2's trade population unchanged, and the cost of
waiting — including the case where the price ran away while we sat — is priced inside the arm
that chose to wait, where it belongs.

### 2.2 The fill window *W*

**Primary: *W* = 60 s.** Reported alongside: *W* ∈ {30 s, 300 s}. The primary decides; the
other two are sensitivity and cannot be promoted after the fact.

Why 60 s and why nothing shorter than 30 s:

* the policy's signal horizon is 240 min, so 60 s of patience spends **0.4%** of the hold —
  the alpha decay over the wait is negligible and the study need not model it;
* at a ~9 s ladder cadence (§1.1) a 60 s window contains ~7 book samples, so the fill is not
  being decided by a single possibly-stale row;
* the tape's time attribution is coarse to ±10 s (§1.3). At *W* = 5 s the attribution error
  exceeds the window and the measurement would be noise. **30 s is the floor**, and it is a
  floor imposed by the data, not a preference.

### 2.3 The fill definition, and the queue model

Take a buy resting at price *P* = best bid at *T*, of size *S* — pre-registered in §2.5 as a
notional and converted to base units at the decision mid *M_T*, so that `Q₀`, `sell_volume` and
*S* are all in the same units — with *Q₀* = the displayed size at that level at *T* (`b0q`).
Let the tape rows attributed to (*T*, *T+W*] per §1.3 be the relevant set.

1. **Certain fill** — some row has `low < P`. A trade printed strictly below our bid, which
   requires every resting bid at and above that price to have been consumed, ours included.
   Queue position is irrelevant here and this branch carries no modelling assumption.
2. **Queue-conditional fill** — no row has `low < P`, but some row has `low == P`. Trades
   printed *at* our price. We fill iff the cumulative aggressor-sell volume over those rows
   satisfies **Σ `sell_volume` ≥ Q₀ + S**.
3. **No fill** — otherwise. The MAKER→TAKER arm crosses at *T+W*.

Symmetrically for sells, with `high > P`, `high == P`, and `buy_volume`.

🔴 **The queue model is crude, and here is exactly how.** This is declared, not defended
afterwards (M3_PLAN §2 M3-4):

* It attributes a row's **whole** same-side aggressor volume to our price level, though some of
  it traded at better prices. This **overstates** drain and therefore *helps* maker — the one
  approximation that runs against §0.2. It is bounded by the fact that branch 2 only applies to
  rows whose extreme *is* our price, so the volume that traded away from *P* is at most the
  part of the row that traded between *P* and the touch, a sub-tick-to-one-tick span.
* It ignores **cancellations**, which in practice evaporate much of the queue ahead. Ignoring
  them **understates** fills and hurts maker.
* It assumes FIFO price-time priority and that we join the **back** of the queue at *T*, with no
  requeueing if the level is rebuilt.
* It ignores our own market impact, which at the sizes in §2.5 is why a size ladder exists.
* Under §1.2's censoring, Σ `sell_volume` is **undercounted** in exactly the busy windows where
  the drain is real. Understates fills; hurts maker.
* *Q₀* is **displayed** size. Hidden and iceberg liquidity ahead of us is invisible in the L2
  ladder, so the true queue is at least this long and never shorter. Overstates fills; helps
  maker. On the majors, where §1.6 shows $400k already displayed at a one-tick touch, this is
  a small correction to an already large queue.

Net: three of the six push against maker, two for, one neutral — and the two that help are both
bounded arguments about a queue that §1.6 shows is enormous on the pairs that matter, while
the censoring one is measured at 30.6% on BTC. §6 therefore requires the censored and
uncensored fill rates side by side, so the size of the dominant bias is visible rather than
taken on this paragraph's word.

### 2.4 Sampling — where the decisions come from

Per-pair cost needs thousands of observations. The M3-2 winner takes ~6.5 trades/day across the
whole universe, so the 22-day ladder window holds only ~140 of its trades — **~18 per pair.**
That cannot carry a per-pair number, and a study that tried would be quoting noise.

So the cost is estimated **unconditionally** and then applied to the policy's trades. Three
layers, with one declared primary:

| layer | decision times | ~n per pair | role |
|---|---|---:|---|
| **L1** | every **5-minute** UTC grid point | ~6,300 | 🔴 **PRIMARY** — the per-pair effective costs |
| **L2** | every **4-hour** UTC grid point | ~132 | the policy's actual decision clock, *unconditioned on its signal* — a check that L1 is not distorted by times the policy never trades |
| **L3** | the M3-2 winner's actual entries and exits inside the window | ~18 | reported with its interval; **explicitly not powered to decide anything** |

Each decision time is anchored to the **last ladder row at or before it**, and is **dropped if
that row is more than 30 s old** — otherwise the p99 tail of §1.1 would let a 300 s-stale book
define a touch price. The drop rate is reported per pair (§6); if it exceeds 5% on any pair,
that pair's numbers are flagged rather than quietly used.

L1 ≈ L2 is a falsifiable prediction of this design. If they disagree beyond their intervals,
**L2 governs** and the disagreement is reported as a finding — the policy's decision clock is
the one that matters, and a 5m grid that misrepresents it is a worse instrument.

### 2.5 Size, and why slippage is walked rather than assumed

Effective cost is a function of order size against resting depth, so size is pre-registered
rather than left implicit: **primary *S* = $10,000 notional**, with $1,000 and $50,000 as the
reported ladder. The primary decides; the ladder is sensitivity.

§1.6's depth table makes the choice consequential in a way M3_PLAN did not anticipate. $10k is
a rounding error against BTC's $402k touch and **twelve times** 1000PEPE's $823. The same
number is therefore two completely different orders depending on the pair, and the study must
handle that explicitly rather than average over it:

* **The taker arm walks the ladder.** Slippage is computed by consuming `a0..a19` (or
  `b0..b19`) until *S* is filled, and the volume-weighted fill price is what §2.6 prices. The
  exported 20-level ladder is what makes this possible, and it replaces the assumed 3 bps/side
  outright — per §1.6(b) that assumption is the study's most likely large error.
* **Ladder exhaustion is a flag, not a silent truncation.** If *S* exceeds the exported
  levels, the observation's slippage is a **lower bound**; those (pair, size) cells are
  reported with their exhaustion rate and **excluded from the primary**. This is why the
  export defaults to **20** levels a side rather than the 5 that §1's audit needs: at $10k
  against 1000PEPE's $823 touch, five levels would be exhausted on most observations and the
  thin pairs would drop out of the primary entirely. Exhaustion is still possible at $50k and
  is reported per (pair, size).
* **The maker arm's depth flag is separate and narrower.** Any pair whose **p05 touch notional
  is below *S*** is flagged, because there the order is not resting *at* the touch, it **is**
  the touch: it moves the quote, and neither §2.3's back-of-queue assumption nor the
  no-impact assumption survives. Flagged pairs are reported; they are not silently pooled into
  the §5.1 aggregate.

**On the fee constants.** §2.6 uses taker 4.0 / maker 2.0 bps per side, which is what
`metrics.py`'s 14 and 5 decompose to and therefore what keeps this study commensurable with
every published M3 number. That is *not* independently verified against the account's actual
Binance USDⓈ-M VIP tier, and it should be: a wrong fee tier shifts every cost in this document
by a constant. Confirming it is a one-line check and a precondition of M3-5, not of M3-4.

### 2.6 The cost arithmetic

All costs are in bps of the **decision mid** *M_T* = ½(`b0p` + `a0p`) at the anchor row, signed
so that **positive is a cost**. Fees are **taker 4.0 bps, maker 2.0 bps per side**, which is the
decomposition `metrics.py`'s 14 rests on: 14 = 2 × (4 bps fee + 3 bps assumed slippage). The 5
does *not* decompose as cleanly — 2 × 2 bps of maker fee is 4, and the remaining 1 bps is an
unattributed allowance. This study replaces the *slippage* half of both with a measurement and
leaves the fee half as a constant; the 1 bps allowance disappears, which is itself a small
reason the measured maker cost will not equal 5 even if fills are perfect.

Write `walk_ask(T, S)` for the volume-weighted price of consuming the ask ladder at time *T*
until *S* notional is filled (§2.5), and `walk_bid` for its mirror. For a buy:

* TAKER: `c = 1e4·(walk_ask(T, S) − M_T)/M_T + 4.0` — the **measured** half-spread and
  slippage, plus the taker fee. At *S* small against the touch this collapses to the
  half-spread, which §1.6 shows is near zero on the majors.
* MAKER→TAKER, filled: `c = 1e4·(b0p − M_T)/M_T + 2.0` — a **negative** half-spread (a credit)
  plus the maker fee. No walk: a resting order fills at its own price or not at all.
* MAKER→TAKER, unfilled: `c = 1e4·(walk_ask(T+W, S) − M_T)/M_T + 4.0` — crossed at the *later*
  book, against the *original* decision mid. This is where the chase is priced.

Sells mirror it. The **effective round-trip cost** is the entry cost plus the exit cost; entries
and exits are sampled independently under L1/L2 and paired under L3.

Note what the third line does: it is the only place the study can lose badly, and it is
supposed to be. If passive orders fill only when price is running away from the fill, the
unfilled branch carries a large positive cost and the maker arm loses on its own merits.

---

## §3 — Adverse selection

A fill is not a good fill because it was cheap. Pre-registered, on the filled subset only —
this is the one place where conditioning on a fill is the correct thing to do, because the
question *is* what the fills we got were worth:

**Mid drift after the fill**, signed by trade direction (positive = the market moved our way),
at horizons **30 s, 60 s, 300 s, 1800 s**. **Primary horizon: 60 s**, matching *W*.

The number that matters is `half_spread_earned − adverse_drift_60s`. If that is negative, the
maker fill is a fill into a moving market and the half-spread credit in §2.6 is being handed
straight back. It is reported per pair, and it is a **required** panel in M3_4_RESULTS — a
maker verdict may not be published without it.

Adverse selection is **not** subtracted from the §2.6 cost. Doing so would double-count: the
post-entry drift is already inside the trade's realised return in M3-2's dumps, which is what
the §5.2 re-score scores. §3 is reported as diagnosis, not folded into the estimate.

---

## §4 — Estimator, clustering and power

**Clusters are UTC days**, as everywhere else in M3 (`metrics.clustered_mean_bps`). L1's ~6,300
observations per pair are heavily autocorrelated and their nominal standard error is fiction;
the day is the unit that repeats.

🔴 **There are 22 of them, and that is few.** M3-2 scored 253 days holding ~220 independent
ones; this study has **22 day-clusters on the 8 served pairs and 13 on the other four.** The
cluster-robust normal approximation is not trustworthy at G = 22, so:

* intervals use the **t distribution with G−1 df**, not the normal;
* every headline interval is **cross-checked with a wild cluster bootstrap** (Rademacher
  weights, 2,000 draws) over days, and both are printed;
* where the two disagree materially, **the bootstrap governs**.

**The minimum detectable effect is computed and published before §5's criterion is applied to
anything.** M3_PLAN §4's retraction lesson is explicit that a pre-registered criterion does not
make an underpowered test informative, and §5.3 below is the clause that enforces it.

---

## §5 — The decision rule, written down before it is measured

### 5.1 Two quantities, both pre-registered

Everything below is at *W* = 60 s, size $10k, layer **L1**, pooled over the **8 served pairs**,
with UTC days as clusters.

> **Q1 — C_taker**, the realized effective **round-trip** cost of the TAKER arm, against the
> **14 bps** `metrics.py` assumes.
>
> **Q2 — Δ = C_taker − C_maker**, the round-trip cost saving of MAKER→TAKER over TAKER,
> against **0** (maker buys nothing) and against **Δ_max** (§1.6a, per-pair, ≈4 bps on the
> majors).

**Q1 is listed first deliberately.** M3_PLAN framed M3-4 as a maker study, and §1.6(b) is the
reason that framing is too narrow: at a 0.01 bps spread and $400k at the touch, the assumed
3 bps/side taker slippage is the larger error, and it runs in the direction that makes every
published M3 number *too pessimistic*. Both are measured; both can re-score the grid.

The Δ = 9 bps hypothesis that a naive reading of 14-vs-5 suggests is **not** on trial, because
§1.6(a) shows it to be arithmetically unreachable on six of the eight served pairs. Testing it
would be testing a straw man. Δ_max is the honest upper hypothesis and it is per-pair.

### 5.2 The verdict

**On Q1 — the taker assumption is declared MIS-STATED** iff C_taker's 95% CI (t, G−1 df,
cross-checked per §4) **excludes 14 bps**. The published cost is then wrong by a measured
amount, in a measured direction, and the grid re-score in Q2's clause 2 below becomes
mandatory rather than conditional on the maker verdict. Note this verdict can fire *whichever way* C_taker lands, and §1.6(b) predicts it
fires downward — which would make M3-2's economics better than published, not worse.

**On Q2 — maker economics are declared REAL** iff **both** hold:

1. **Δ > 0 with a 95% CI excluding zero** — resting at the touch is cheaper than crossing, on
   this data, by a margin the data can see; **and**
2. the M3-2 winner, **re-scored at the measured per-pair round-trip cost**, still clears
   M3_PROTOCOL §4.4's promotion bar of **+0.25 bps worst-window net**.

Clause 2 is the one that matters and it is why the deliverable is a re-score and not a fill
rate. A fill rate is a fact about the order book; the bar is a fact about the strategy.

**Maker economics are declared NOT WORTH THE COMPLEXITY** iff Δ's CI **excludes Δ_max/2** —
that is, the data positively rules out capturing even half the arithmetic ceiling. Given that
Δ_max is ~4 bps on the majors, this is the finding that resting orders cost more in missed
fills and chase than the 2 bps/side fee rebate is worth, and it is the outcome that lets M3-5
build a simple crossing executor and stop there. Reaching it is a *useful* result, not a
failure, and §7's first bullet is why it can be reached without ever placing an order.

**Every other outcome is INCONCLUSIVE**, and §5.3 governs what may then be written down.

### 5.3 🔴 The power clause — no criterion closes a direction it cannot see

Before either verdict in §5.2 may be published, **the MDE must be reported and compared to the
effect being decided**, and the criterion's failure rate must be bootstrapped **on both arms**
(M3_PLAN §4; the T5/T6 lesson, where a Tier-1 clause that "rejected" 12 pairs turned out to
reject the incumbent 8 just as often).

Concretely:

* if Δ's 95% CI is wide enough to contain **both 0 and Δ_max**, the study has not
  distinguished its two hypotheses and **the result is INCONCLUSIVE regardless of where the
  point estimate falls.** The point estimate is reported; no verdict is. Since Δ_max is only
  ~4 bps on the majors, this is a real risk and the MDE in §4 is what says whether 22 days of
  ladder can see a 4 bps effect at all — **compute it first, and if it exceeds Δ_max, the
  study cannot decide Q2 and must say so instead of reporting a point estimate as a finding.**
* the same clause applies to Q1 with 14 bps in place of Δ_max.
* an INCONCLUSIVE outcome **does not close the maker direction.** Per §0.2 the defects bias
  against maker, so a null here is the weakest possible evidence. The recorded conclusion in
  that case is *"22 days of ladder cannot resolve this"*, and the remedy is calendar time —
  the ladder grows ~1 day per day at no cost — **not** a bigger model, a wider grid, or a
  re-run with different knobs.
* the 4 short-window pairs never contribute to a verdict. 13 days is a texture table.

### 5.4 What is NOT allowed to happen after the numbers land

* No re-choosing *W*, the size, the queue model, the horizon, or the layer. The primaries are
  fixed above; everything else is sensitivity and is labelled as such in the results.
* No dropping a pair because its number is inconvenient. §2.4's staleness rule and §2.5's
  depth flag are the only exclusions, both defined before measurement, both count-based.
* No re-running the M3-2 grid search at the measured cost. §5.2 clause 2 **re-scores the
  existing 40 configurations**; re-searching a grid at a new cost assumption is the overfit
  M3_PROTOCOL §0 forbids and M3_PLAN §4 ranks as risk #1. If the measured cost changes which
  configuration wins, that is a **finding to report**, and it is a pre-registration for a
  future wave — not a promotion.
* `metrics.MAKER_COST_BPS` / `TAKER_COST_BPS` are **not** edited by this study. M3-4 publishes
  the measured cost; changing the constants that every prior published number was computed with
  would silently invalidate the archive. A per-pair cost table is added alongside them.

---

## §6 — What `docs/M3_4_RESULTS.md` must contain

Fixed here so the write-up cannot be shaped to the outcome:

1. **The per-pair effective round-trip cost** for BOTH arms, L1, next to the assumed 5 and 14 —
   the headline deliverable named in M3_PLAN §2 M3-4.
2. **Q1 (C_taker vs 14) and Q2 (Δ vs 0 and Δ_max), each with its interval** — both the t-based
   and the wild-bootstrap version — **plus the MDE for each**, per §5.3.
3. **The ladder-exhaustion rate per (pair, size)** (§2.5), so it is visible which cells the
   exported depth could not price and which were excluded from the primary.
4. **Fill rate per pair, split into censored and uncensored windows** (§1.2), and split by the
   certain-fill and queue-conditional branches (§2.3), so the load-bearing approximation is
   visible.
5. **The adverse-selection panel** (§3) — `half_spread_earned − drift_60s` per pair.
6. **L1 vs L2 vs L3** side by side, with L3's interval shown wide and labelled undecisive.
7. **The re-score of the M3-2 grid** at the measured cost, against the +0.25 bps bar.
8. **The exclusion counts** — rows dropped for staleness, pairs flagged for thin touch depth.
9. **The verdict, in plain sentences**, per M3_PLAN's standing requirement that the
   plain-language layer answer the bottom-line question explicitly. Two answers are needed, not
   one: *what does it actually cost us to trade*, and *would resting orders make that cheaper* —
   with the units defined at the point of use, and with an explicit "or we cannot tell yet, and
   here is what would settle it" where §5.3 applies.

## §7 — Two things this study will not fix, and should not pretend to

* **It cannot measure our own queue position.** No order was ever placed; there is no private
  fill history. §2.3 is a model of the queue, and every number downstream inherits its
  crudeness. The remedy is placing real passive orders in the paper stack, which is M3-5's
  territory and depends on an executor that can express a limit order at all (M3_PLAN §0.5.4).
* **It cannot fix the collector's 200-trade cap retroactively.** §1.2's censoring is in the
  stored data for good. Raising `limit` (or moving the tape to the WebSocket stream, which has
  no cap) fixes it **going forward** and is worth doing regardless of this study's verdict —
  but it is a collector change, not an M3-4 deliverable, and no number here may be re-derived
  after such a change and compared to one from before it.
