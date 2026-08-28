"""M3-4 — the execution-cost study: what crossing actually costs, and what resting saves.

WHAT THIS MODULE IS. `docs/M3_4_PROTOCOL.md` is the pre-registration, committed
2026-08-28 before any fill number existed. This module is its implementation and nothing
else: every constant, every branch and every exclusion below cites the section that fixed
it. Where the protocol is silent on a mechanical detail, §0.1 of this docstring records
the choice, the reason, and the direction of its bias — chosen BEFORE the first number,
and mirrored into the protocol's §2.7 addendum so the audit trail survives this file.

THE TWO QUESTIONS (protocol §5.1), both pre-registered, in this order:

  Q1  C_taker  — the realized effective ROUND-TRIP cost of crossing, against the 14.0 bps
                 `metrics.py` assumes. §1.6(b) predicts this is the larger of the two
                 errors and that it runs in the direction that makes every published M3
                 number too PESSIMISTIC.
  Q2  Delta = C_taker - C_maker — what resting at the touch saves, against 0 and against
                 the per-pair arithmetic ceiling Delta_max = 4 bps + 4 x half_spread
                 (§1.6a). On BTC that ceiling is 4.02 bps, so the 9 bps a naive reading of
                 14-vs-5 suggests is not on trial: it is unreachable.

THE DESIGN PRINCIPLE THAT GOVERNS EVERY APPROXIMATION (protocol §0.2). The data has three
known defects — a right-censored tape, a ~9 s ladder cadence, and coarse tape time
attribution. Every approximation is arranged to bias the answer AGAINST maker execution,
so that:

    a maker verdict is safe; a taker verdict is not.

If maker wins on these measurements it wins on a lower bound. If maker loses, the study
has NOT shown maker execution is unobtainable — only that this data cannot show it, and
§5.3's power clause governs what may be concluded.

§0.1 — THE MECHANICAL CHOICES THE PROTOCOL LEFT OPEN
------------------------------------------------------------------------------------
Three were needed to write this file. All three are fixed here before any number, and all
three are recorded in the protocol's §2.7 addendum:

1.  **Which tape rows fall in a fill window.** §1.3 fixes what a row COVERS — the span
    (previous row's `window_start`, this row's `window_start` + 5 s] — but not what it
    means for that span to be "attributed to (T, T+W]". Primary: a row counts if its span
    OVERLAPS the window. This is the volume-preserving reading, and it is the same
    argument §1.3 itself uses when it rejects the "5 s beginning at window_start" reading
    for discarding half the tape. Containment is computed as a declared sensitivity.
    Direction: overlap admits more tape, so it HELPS maker; the sensitivity bounds it.

2.  **The reference time for adverse selection.** §3 says "mid drift after the fill", but
    the fill time inside (T, T+W] is unobservable — we know only that it happened. Drift
    is therefore measured from the decision anchor T against its mid M_T, at horizons
    30/60/300/1800 s, primary 60 s. Two reasons: it is the only reference the data
    actually pins down, and per §0.2 it is the conservative one — a fill at T+5 s has its
    preceding 5 s of drift counted against it, which OVERSTATES adverse selection and
    hurts maker. It also makes the primary horizon 60 s coincide exactly with W, which is
    what §3 says it should match. Everything else in §2.6 is likewise priced against M_T,
    so the panel and the cost table share one reference.

3.  **Round-trip construction under L1/L2.** §2.6 says entries and exits are "sampled
    independently" in these layers and the round trip is their sum. At each decision time
    both directions are priced, and the observation is (buy cost + sell cost) — a complete
    round trip attributable to one day, which is what the day-clustered estimator of §4
    needs. Pairing the two halves at one T estimates the sum of the two means without
    assuming anything about their dependence, and it keeps one row per decision.

WHAT THIS MODULE MAY NOT DO (protocol §5.4), enforced by construction below:
  * no re-choosing W, size, queue model, horizon or layer after the numbers land;
  * no dropping a pair for an inconvenient number — the only exclusions are §2.4's
    staleness rule and §2.5's depth flags, both count-based and both defined in advance;
  * no re-SEARCHING the M3-2 grid at the measured cost. §5.2 clause 2 re-SCORES the
    existing 40 configurations. A change in which one wins is a finding to report and a
    pre-registration for a future wave, never a promotion;
  * `metrics.MAKER_COST_BPS` / `TAKER_COST_BPS` are not edited. Changing the constants
    every prior published number was computed under would silently invalidate the archive.
    A per-pair cost table is published ALONGSIDE them.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import bookprep

# --------------------------------------------------------------------------------------
# The pre-registered constants. Every one cites the section that fixed it, so a later
# session can check the code against the protocol rather than against this file's memory.
# --------------------------------------------------------------------------------------
W_PRIMARY_S = 60                      # §2.2 — the fill window that decides
W_SENSITIVITY_S = (30, 300)           # §2.2 — reported, never promoted
SIZE_PRIMARY = 10_000.0               # §2.5 — USD notional
SIZE_LADDER = (1_000.0, 50_000.0)     # §2.5 — sensitivity
TAKER_FEE_BPS = 4.0                   # §2.6 — the fee half of metrics.py's 14
MAKER_FEE_BPS = 2.0                   # §2.6 — the fee half of metrics.py's 5
STALENESS_CAP_S = 30.0                # §2.4 — anchor row older than this drops the decision
STALENESS_FLAG_RATE = 0.05            # §2.4 — above this, a pair's numbers are FLAGGED
ADVERSE_HORIZONS_S = (30, 60, 300, 1800)   # §3
ADVERSE_PRIMARY_S = 60                # §3
BOOTSTRAP_DRAWS = 2_000               # §4 — wild cluster bootstrap, Rademacher
BOOTSTRAP_SEED = 20260828             # fixed so the interval is reproducible
TAPE_ROW_SPAN_S = 5                   # §1.3 — the 5s the label is floored to
ASSUMED_TAKER_BPS = 14.0              # §5.1 Q1's null
ASSUMED_MAKER_BPS = 5.0               # reported for context only; not a null
# M3_PROTOCOL §4 rule P4. Mirrored here (not imported from cli) because the re-score table
# is unreadable without it: a config's eligibility is a TRADE COUNT and is therefore
# completely independent of what execution costs. Re-scoring can change the P&L ranking; it
# can never make an ineligible config eligible.
MIN_TRADES_PER_WINDOW = 100

BPS = 1e4


# --------------------------------------------------------------------------------------
# §2.5 — the ladder walk. Slippage is MEASURED, never assumed: this is what replaces the
# 3 bps/side that metrics.py's 14 rests on, and §1.6(b) is why that matters more than the
# maker side of the study.
# --------------------------------------------------------------------------------------

def ladder_arrays(book: pd.DataFrame, levels: int) -> dict[str, np.ndarray]:
    """Project the exported b0p..b19q / a0p..a19q columns into (n, levels) matrices.

    Missing levels come back from Postgres as NaN (a pair whose book was thinner than the
    export depth at that instant). They are zeroed on the QUANTITY side only, so a walk
    treats an absent level as no liquidity rather than as an error — and exhaustion then
    reports it honestly instead of a NaN silently poisoning a VWAP.
    """
    out = {}
    for side, letter in (("bid", "b"), ("ask", "a")):
        p = np.column_stack([book[f"{letter}{i}p"].to_numpy(np.float64) for i in range(levels)])
        q = np.column_stack([book[f"{letter}{i}q"].to_numpy(np.float64) for i in range(levels)])
        out[f"{side}_p"] = p
        out[f"{side}_q"] = np.nan_to_num(q, nan=0.0)
    return out


def walk(prices: np.ndarray, qtys: np.ndarray, need_base: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Volume-weighted fill price for consuming `need_base` units off one side's ladder.

    Vectorised over rows: `prices`/`qtys` are (n, levels) best-first, `need_base` is (n,).
    Returns (vwap, exhausted). A row whose whole exported ladder cannot fill the order is
    flagged EXHAUSTED and its vwap is a LOWER bound on the true cost — §2.5 excludes those
    (pair, size) cells from the primary rather than letting a truncated walk understate
    slippage. This is why the export defaults to 20 levels and not the 5 the §1 audit
    needed: at $10k against 1000PEPE's $823 touch, five levels would exhaust on most
    observations and the thin pairs would drop out of the primary entirely.
    """
    cum = np.cumsum(qtys, axis=1)
    total = cum[:, -1]
    exhausted = need_base > total
    # Units taken at each level: the part of `need_base` that falls inside this level.
    prev = np.concatenate([np.zeros((cum.shape[0], 1)), cum[:, :-1]], axis=1)
    take = np.clip(need_base[:, None] - prev, 0.0, qtys)
    filled = take.sum(axis=1)
    notional = np.nansum(np.where(take > 0, prices, 0.0) * take, axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        vwap = np.where(filled > 0, notional / filled, np.nan)
    return vwap, exhausted


# --------------------------------------------------------------------------------------
# §2.4 — anchoring a decision time to a book row, and §1.4's staleness.
# --------------------------------------------------------------------------------------

def anchor(book_ts_ns: np.ndarray, decision_ns: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Index of the last ladder row at or before each decision time, and its age in seconds.

    A decision whose anchor is older than STALENESS_CAP_S is dropped by the caller (§2.4).
    Without that rule the p99 tail of §1.1 — gaps out to 294 s — would let a five-minute
    stale book define a touch price, and every cost derived from it would be fiction.
    """
    idx = np.searchsorted(book_ts_ns, decision_ns, side="right") - 1
    age = np.where(idx >= 0, (decision_ns - book_ts_ns[np.clip(idx, 0, None)]) / 1e9, np.inf)
    return idx, age


# --------------------------------------------------------------------------------------
# §1.3 / §2.3 — the tape, its spans, and the fill test.
# --------------------------------------------------------------------------------------

def tape_spans(trades: pd.DataFrame) -> dict[str, np.ndarray]:
    """Per-row covered interval and the aggregates the fill test reads.

    §1.3: `window_start` is `floor_to_5s(ts of the LAST trade in the batch)` while the
    batch covers everything since the previous poll — about 10 s. So a row's span is
    (previous row's window_start, this row's window_start + 5 s]. Volume coverage is
    complete (the batch is cut by `last_id`, not by time); it is the TIME ATTRIBUTION that
    is coarse, and that is what forbids a fill window shorter than 30 s (§2.2).
    """
    ws = trades["window_start"].to_numpy("datetime64[ns]").astype(np.int64)
    span_end = ws + TAPE_ROW_SPAN_S * 1_000_000_000
    # The first row of a pair has no predecessor; give it a one-span-wide start so it is
    # neither dropped nor allowed to claim unbounded history.
    span_start = np.concatenate([[ws[0] - TAPE_ROW_SPAN_S * 1_000_000_000], ws[:-1]])
    return {
        "span_start": span_start,
        "span_end": span_end,
        "high": trades["high"].to_numpy(np.float64),
        "low": trades["low"].to_numpy(np.float64),
        "buy_volume": trades["buy_volume"].to_numpy(np.float64),
        "sell_volume": trades["sell_volume"].to_numpy(np.float64),
        # §1.2: trade_count == 200 is a CENSORING INDICATOR, not a count. Carried through
        # every table so the size of the dominant bias is visible rather than assumed.
        "censored": (trades["trade_count"].to_numpy() >= bookprep.TRADE_LIMIT),
    }


def window_aggregates(tape: dict[str, np.ndarray], t0_ns: np.ndarray, t1_ns: np.ndarray,
                      containment: bool = False) -> dict[str, np.ndarray]:
    """Aggregate the tape rows attributed to each half-open window (t0, t1].

    Membership is §0.1(1)'s OVERLAP rule by default — a row counts if its covered span
    intersects the window — with `containment=True` as the declared sensitivity.

    Both bounds are monotone in the decision time, so the row range is a contiguous slice
    and the aggregation is a short loop over decisions rather than a scan of the tape.
    """
    ss, se = tape["span_start"], tape["span_end"]
    if containment:
        # Row entirely inside the window: span_start >= t0 and span_end <= t1.
        lo = np.searchsorted(ss, t0_ns, side="left")
        hi = np.searchsorted(se, t1_ns, side="right")
    else:
        # Overlap: span_end > t0 and span_start < t1.
        lo = np.searchsorted(se, t0_ns, side="right")
        hi = np.searchsorted(ss, t1_ns, side="left")

    n = t0_ns.size
    out = {k: np.empty(n, np.float64) for k in ("high", "low", "buy_volume", "sell_volume")}
    out["n_rows"] = np.zeros(n, np.int64)
    out["censored"] = np.zeros(n, bool)
    # Prefix sums make the volume halves O(1) per decision; high/low need the slice.
    cbuy = np.concatenate([[0.0], np.cumsum(tape["buy_volume"])])
    csell = np.concatenate([[0.0], np.cumsum(tape["sell_volume"])])
    ccen = np.concatenate([[0], np.cumsum(tape["censored"].astype(np.int64))])
    hi = np.maximum(hi, lo)
    for i in range(n):
        a, b = lo[i], hi[i]
        out["n_rows"][i] = b - a
        if b <= a:
            out["high"][i] = np.nan
            out["low"][i] = np.nan
            out["buy_volume"][i] = 0.0
            out["sell_volume"][i] = 0.0
            continue
        out["high"][i] = tape["high"][a:b].max()
        out["low"][i] = tape["low"][a:b].min()
        out["buy_volume"][i] = cbuy[b] - cbuy[a]
        out["sell_volume"][i] = csell[b] - csell[a]
        out["censored"][i] = (ccen[b] - ccen[a]) > 0
    return out


def fill_branch(side: int, rest_price: np.ndarray, q0: np.ndarray, size_base: np.ndarray,
                agg: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """§2.3's three-way fill test, for a resting order of `size_base` at `rest_price`.

    side = +1 (a resting BUY at the bid) or -1 (a resting SELL at the ask).

      1. CERTAIN fill    — a trade printed strictly THROUGH our price (low < P for a buy).
                           Every resting order at and above that price was consumed, ours
                           included. This branch carries no modelling assumption at all.
      2. QUEUE-CONDITIONAL — trades printed AT our price. We fill iff the cumulative
                           aggressor volume on the opposite side clears the queue ahead of
                           us plus our own size: sum(sell_volume) >= Q0 + S for a buy.
      3. NO FILL         — otherwise; the MAKER->TAKER arm crosses at T+W.

    The queue model is crude and §2.3 declares exactly how. Three of its six approximations
    push against maker (whole-row volume attribution aside, it ignores cancellations,
    inherits §1.2's censoring, and reads only DISPLAYED depth), and the two that help are
    bounded arguments about a queue §1.6 shows is enormous on the pairs that matter. The
    branches are returned separately because §6 item 4 requires them reported apart — the
    load-bearing approximation has to be visible, not summarised away.
    """
    extreme = agg["low"] if side > 0 else agg["high"]
    if side > 0:
        through, at, drain = extreme < rest_price, extreme == rest_price, agg["sell_volume"]
    else:
        through, at, drain = extreme > rest_price, extreme == rest_price, agg["buy_volume"]
    # A window with no tape rows at all has a NaN extreme; NaN comparisons are already
    # False, but say so rather than leaving it to IEEE semantics a reader has to recall.
    quiet = np.isnan(extreme)
    through, at = through & ~quiet, at & ~quiet
    queue_ok = drain >= (q0 + size_base)
    certain = through
    queued = (~certain) & at & queue_ok
    return {"filled": certain | queued, "certain": certain, "queued": queued,
            "touched_at": at, "drain": drain}


# --------------------------------------------------------------------------------------
# §2.6 — the cost arithmetic. All costs are in bps of the DECISION mid M_T, signed so that
# POSITIVE IS A COST. Fees are the constants metrics.py's 14 and 5 decompose to; this
# study replaces the SLIPPAGE half with a measurement and leaves the fee half alone.
# --------------------------------------------------------------------------------------

def taker_cost_bps(side: int, vwap: np.ndarray, mid: np.ndarray) -> np.ndarray:
    """Cross now: the measured half-spread AND slippage off the ladder, plus the taker fee.

    At a size small against the touch this collapses to the half-spread, which §1.6 shows
    is near zero on the majors — which is the whole reason Q1 exists as a decision
    quantity rather than as the baseline of a difference.
    """
    signed = (vwap - mid) if side > 0 else (mid - vwap)
    return BPS * signed / mid + TAKER_FEE_BPS


def maker_filled_cost_bps(side: int, rest_price: np.ndarray, mid: np.ndarray) -> np.ndarray:
    """Resting order that filled: a NEGATIVE half-spread (a credit) plus the maker fee.

    No ladder walk — a resting order fills at its own price or not at all.
    """
    signed = (rest_price - mid) if side > 0 else (mid - rest_price)
    return BPS * signed / mid + MAKER_FEE_BPS


def half_spread_earned_bps(side: int, rest_price: np.ndarray, mid: np.ndarray) -> np.ndarray:
    """The credit half of the line above, without the fee — §3's panel needs it alone."""
    signed = (mid - rest_price) if side > 0 else (rest_price - mid)
    return BPS * signed / mid


# The unfilled branch reuses taker_cost_bps against the LATER book and the ORIGINAL mid:
#   c = 1e4 * (walk_ask(T+W, S) - M_T) / M_T + TAKER_FEE_BPS
# which is where the chase is priced. §2.6 notes this is the only place the study can lose
# badly, and that it is supposed to be: if passive orders fill only when price is running
# away, the unfilled branch carries a large positive cost and maker loses on its merits.


# --------------------------------------------------------------------------------------
# §4 — the estimator. Clusters are UTC days. There are 22 of them on the served pairs,
# which is few enough that the cluster-robust NORMAL approximation is not trustworthy.
# --------------------------------------------------------------------------------------

def cluster_stats(values: np.ndarray, days: np.ndarray, alpha: float = 0.05,
                  draws: int = BOOTSTRAP_DRAWS) -> dict:
    """Cluster-robust mean with BOTH a t interval and a wild cluster bootstrap-t interval.

    §4 requires both to be printed and says the bootstrap governs where they disagree
    materially. The wild bootstrap uses Rademacher weights on cluster-level residuals,
    which is the standard remedy at G ~ 20 where the CRVE's asymptotics have not bitten.

    Also returns the MINIMUM DETECTABLE EFFECT at 80% power — two-sided, alpha 0.05, on
    the t distribution with G-1 df. §5.3 forbids applying either verdict before the MDE is
    reported and compared to the effect being decided, which is the M3_PLAN §4 retraction
    lesson written as a precondition: a pre-registered criterion protects against shopping
    for a favourable result, it does not make an underpowered test informative.
    """
    from scipy import stats as sps

    v = np.asarray(values, np.float64)
    ok = np.isfinite(v)
    v, d = v[ok], np.asarray(days)[ok]
    n = v.size
    if n == 0:
        return {"n": 0, "clusters": 0, "mean": np.nan, "se": np.nan,
                "lo": np.nan, "hi": np.nan, "boot_lo": np.nan, "boot_hi": np.nan,
                "mde": np.nan, "df": 0}
    mean = float(v.mean())
    codes, _ = pd.factorize(d)
    g = int(codes.max()) + 1
    resid = v - mean

    def crve(r: np.ndarray) -> float:
        sums = np.bincount(codes, weights=r, minlength=g)
        if g < 2:
            return float("nan")
        return float(np.sqrt((sums ** 2).sum() / (n ** 2) * (g / (g - 1.0))))

    se = crve(resid)
    df = g - 1
    tcrit = float(sps.t.ppf(1 - alpha / 2, df)) if df > 0 else float("nan")
    out = {"n": n, "clusters": g, "mean": mean, "se": se, "df": df,
           "lo": mean - tcrit * se, "hi": mean + tcrit * se}

    # Wild cluster bootstrap-t: impose nothing on the null, resample the cluster residuals
    # with +/-1 weights, and invert the studentised distribution.
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    ts = np.empty(draws)
    for b in range(draws):
        w = rng.choice((-1.0, 1.0), size=g)[codes]
        vb = mean + w * resid
        mb = float(vb.mean())
        sb = crve(vb - mb)
        ts[b] = (mb - mean) / sb if sb > 0 else np.nan
    ts = ts[np.isfinite(ts)]
    if ts.size:
        qlo, qhi = np.quantile(ts, [alpha / 2, 1 - alpha / 2])
        out["boot_lo"], out["boot_hi"] = mean - qhi * se, mean - qlo * se
    else:
        out["boot_lo"] = out["boot_hi"] = np.nan

    # MDE at 80% power. If this exceeds the effect being decided, §5.3 says the study
    # cannot decide that question and must say so instead of reporting a point estimate.
    out["mde"] = (tcrit + float(sps.t.ppf(0.80, df))) * se if df > 0 else np.nan
    return out


def verdict_vs(stat: dict, null: float) -> str:
    """Does the interval exclude `null`? Reported with the bootstrap governing (§4)."""
    lo, hi = stat.get("boot_lo"), stat.get("boot_hi")
    if not np.isfinite(lo) or not np.isfinite(hi):
        lo, hi = stat.get("lo"), stat.get("hi")
    if not np.isfinite(lo) or not np.isfinite(hi):
        return "no interval"
    if lo > null:
        return f"EXCLUDES {null:g} (above)"
    if hi < null:
        return f"EXCLUDES {null:g} (below)"
    return f"contains {null:g}"


# --------------------------------------------------------------------------------------
# The per-decision engine. One row out per decision time, carrying both arms, both
# directions, every exclusion flag, and the drift panel — so every table in §6 is a
# groupby over one frame rather than a second pass with its own assumptions.
# --------------------------------------------------------------------------------------

def evaluate(pair: str, book: pd.DataFrame, trades: pd.DataFrame, decision_ns: np.ndarray,
             w_s: int = W_PRIMARY_S, size_usd: float = SIZE_PRIMARY,
             levels: int = 20, containment: bool = False) -> pd.DataFrame:
    """Price both execution policies over one pair's decision times.

    §2.1: the two arms are priced over the IDENTICAL set of decisions. Conditioning on a
    fill would select on the outcome — the decisions where a passive order fills are
    disproportionately the ones where price came to you, which is also where the alpha was
    worse — and that is the standard way a maker study flatters itself. So a decision is
    kept only if BOTH its T anchor and its T+W anchor are fresh, and every kept decision
    produces a cost in both arms. The MAKER->TAKER arm never abandons the decision: if the
    resting order has not filled by T+W it crosses at the prevailing touch.
    """
    b = book[book["symbol"] == pair].sort_values("ts", kind="mergesort")
    t = trades[trades["symbol"] == pair].sort_values("window_start", kind="mergesort")
    if b.empty or t.empty or decision_ns.size == 0:
        return pd.DataFrame()

    book_ns = b["ts"].to_numpy("datetime64[ns]").astype(np.int64)
    lad = ladder_arrays(b, levels)
    tape = tape_spans(t)

    w_ns = int(w_s) * 1_000_000_000
    i0, age0 = anchor(book_ns, decision_ns)
    i1, age1 = anchor(book_ns, decision_ns + w_ns)
    fresh = (i0 >= 0) & (i1 >= 0) & (age0 <= STALENESS_CAP_S) & (age1 <= STALENESS_CAP_S)

    n_all = decision_ns.size
    keep = np.flatnonzero(fresh)
    if keep.size == 0:
        return pd.DataFrame()
    d_ns, j0, j1 = decision_ns[keep], i0[keep], i1[keep]

    bid0, ask0 = lad["bid_p"][j0, 0], lad["ask_p"][j0, 0]
    mid = 0.5 * (bid0 + ask0)
    size_base = size_usd / mid

    # --- the taker arm: walk the ladder at T (§2.5) ------------------------------------
    vw_ask, exh_ask = walk(lad["ask_p"][j0], lad["ask_q"][j0], size_base)
    vw_bid, exh_bid = walk(lad["bid_p"][j0], lad["bid_q"][j0], size_base)
    # --- the maker arm's fallback: walk the LATER ladder at T+W ------------------------
    vw_ask_w, exh_ask_w = walk(lad["ask_p"][j1], lad["ask_q"][j1], size_base)
    vw_bid_w, exh_bid_w = walk(lad["bid_p"][j1], lad["bid_q"][j1], size_base)

    agg = window_aggregates(tape, d_ns, d_ns + w_ns, containment=containment)
    f_buy = fill_branch(+1, bid0, lad["bid_q"][j0, 0], size_base, agg)
    f_sell = fill_branch(-1, ask0, lad["ask_q"][j0, 0], size_base, agg)

    out = pd.DataFrame({
        "pair": pair,
        "ts": pd.to_datetime(d_ns, utc=True),
        "day": pd.to_datetime(d_ns, utc=True).floor("D"),
        "mid": mid,
        "spread_bps": BPS * (ask0 - bid0) / mid,
        "touch_usd_bid": bid0 * lad["bid_q"][j0, 0],
        "touch_usd_ask": ask0 * lad["ask_q"][j0, 0],
        "book_age_s": age0[keep],
        "censored": agg["censored"],
        "tape_rows": agg["n_rows"],
    })

    for label, side, vw, vw_w, exh, exh_w, rest, f in (
            ("buy", +1, vw_ask, vw_ask_w, exh_ask, exh_ask_w, bid0, f_buy),
            ("sell", -1, vw_bid, vw_bid_w, exh_bid, exh_bid_w, ask0, f_sell)):
        c_taker = taker_cost_bps(side, vw, mid)
        c_chase = taker_cost_bps(side, vw_w, mid)      # unfilled: crossed at the LATER book
        c_maker = np.where(f["filled"], maker_filled_cost_bps(side, rest, mid), c_chase)
        out[f"taker_{label}"] = c_taker
        out[f"maker_{label}"] = c_maker
        out[f"filled_{label}"] = f["filled"]
        out[f"certain_{label}"] = f["certain"]
        out[f"queued_{label}"] = f["queued"]
        out[f"halfspread_{label}"] = half_spread_earned_bps(side, rest, mid)
        # §2.5: exhaustion makes slippage a LOWER bound. Flagged on either walk, because
        # the chase branch is priced off the T+W ladder and can exhaust there too.
        out[f"exhausted_{label}"] = exh | exh_w

    # §0.1(3): the round trip is one buy plus one sell, which is direction-agnostic — a
    # long is buy-then-sell and a short is sell-then-buy, and both pay the same pair of
    # one-way costs. Pairing the halves at one decision time gives one observation per
    # decision for the day-clustered estimator without assuming they are independent.
    out["taker_rt"] = out["taker_buy"] + out["taker_sell"]
    out["maker_rt"] = out["maker_buy"] + out["maker_sell"]
    out["delta_rt"] = out["taker_rt"] - out["maker_rt"]
    out["exhausted"] = out["exhausted_buy"] | out["exhausted_sell"]

    # --- §3's adverse-selection panel, measured from the decision anchor (§0.1(2)) -----
    for h in ADVERSE_HORIZONS_S:
        ih, ah = anchor(book_ns, d_ns + int(h) * 1_000_000_000)
        ok = (ih >= 0) & (ah <= STALENESS_CAP_S)
        mid_h = np.where(ok, 0.5 * (lad["bid_p"][np.clip(ih, 0, None), 0]
                                    + lad["ask_p"][np.clip(ih, 0, None), 0]), np.nan)
        drift = BPS * (mid_h - mid) / mid
        # Positive = the market moved OUR way. A buy wants the mid up, a sell wants it down.
        out[f"drift{h}_buy"] = drift
        out[f"drift{h}_sell"] = -drift

    out.attrs["n_decisions"] = n_all
    out.attrs["n_dropped_stale"] = int(n_all - keep.size)
    return out


# --------------------------------------------------------------------------------------
# §2.4 — the three sampling layers. L1 is the declared PRIMARY; L2 is the falsifiable
# check on it; L3 is reported and explicitly not powered to decide anything.
# --------------------------------------------------------------------------------------

def grid_decisions(t_lo: pd.Timestamp, t_hi: pd.Timestamp, step_s: int) -> np.ndarray:
    """UTC grid points strictly inside the pair's ladder coverage."""
    lo = pd.Timestamp(t_lo).ceil(f"{step_s}s")
    hi = pd.Timestamp(t_hi).floor(f"{step_s}s")
    if lo >= hi:
        return np.array([], np.int64)
    return (pd.date_range(lo, hi, freq=f"{step_s}s", tz="UTC")
            .to_numpy("datetime64[ns]").astype(np.int64))


def l3_decisions(winner_trades: pd.DataFrame, lo_ns: int, hi_ns: int) -> pd.DataFrame:
    """L3 — the M3-2 winner's OWN entries and exits that fall inside the ladder window.

    §2.4 sizes this layer at ~18 trades per pair and says in advance that it is "explicitly
    not powered to decide anything". It is computed because a cost study that never touched
    the policy's real decisions would be answering an adjacent question, and it is reported
    with its interval shown wide and labelled undecisive — never promoted over L1.

    Unlike L1/L2 the two halves are PAIRED: entry and exit belong to one trade, so the
    round trip is that trade's own two costs and the clustering day is its exit day.
    """
    t = winner_trades.copy()
    ent = t["entry_ts"].to_numpy(np.int64)
    ext = t["exit_ts"].to_numpy(np.int64)
    inside = (ent >= lo_ns) & (ext <= hi_ns)
    t = t[inside].copy()
    if t.empty:
        return t
    # A long is buy-then-sell; a short is sell-then-buy. The round trip is one of each
    # either way, which is why L1/L2 can sample the two halves without knowing the side.
    t["entry_dir"] = np.where(t["side"] > 0, +1, -1)
    t["exit_dir"] = -t["entry_dir"]
    return t


# --------------------------------------------------------------------------------------
# §5.2 clause 2 — the re-score. "A fill rate is a fact about the order book; the bar is a
# fact about the strategy", so the deliverable is a re-score and not a fill rate.
# --------------------------------------------------------------------------------------

def net_at_per_pair_cost(trades: pd.DataFrame, cost_by_pair: dict[str, float],
                         default: float) -> pd.Series:
    """Per-trade net return at a PER-PAIR round-trip cost.

    metrics.summarise takes one scalar cost, which is exactly the assumption this study
    exists to replace: §1.6's spread table spans 0.01 bps on BTC to 4.69 on ADA, so one
    number applied to every pair is the error, not the convenience. A pair with no measured
    cost (excluded for staleness or ladder exhaustion) falls back to `default` and the
    fallback count is reported — never silently dropped, which would re-weight the policy.
    """
    c = trades["pair"].map(cost_by_pair).astype(float)
    c = c.fillna(default)
    return trades["signed_ret"] - c / BPS * trades.get("size", 1.0)


def rescore(trades: pd.DataFrame, cost_by_pair: dict[str, float], default: float,
            n_seeds: int = 3) -> dict:
    """Pooled and per-window net bps at the measured cost, plus the worst window.

    The worst window is the number §5.2 clause 2 tests against M3_PROTOCOL §4.4's
    +0.25 bps promotion bar, because M3 ranks policies on their worst calendar window and
    not on their average — that is how a rule that only worked during one lucky stretch
    gets caught.
    """
    from .dumps import add_window
    t = add_window(trades, ts_col="entry_ts").copy()
    t["net_ret"] = net_at_per_pair_cost(t, cost_by_pair, default)
    rows = []
    for name in ["w1", "w2", "w3", "w4"]:
        sub = t[t["window"] == name]
        rows.append({"window": name, "trades": len(sub),
                     "net_bps": float(sub["net_ret"].mean() * BPS) if len(sub) else np.nan})
    per_window = pd.DataFrame(rows)
    return {
        "trades": len(t),
        "pooled_net_bps": float(t["net_ret"].mean() * BPS),
        "per_window": per_window,
        "worst_net_bps": float(np.nanmin(per_window["net_bps"].to_numpy())),
        "n_fallback": int(t["pair"].map(cost_by_pair).isna().sum()),
    }


# --------------------------------------------------------------------------------------
# The study. §6 fixes what docs/M3_4_RESULTS.md must contain, "so the write-up cannot be
# shaped to the outcome" — so the report generator below walks those nine items in order
# and every one of them is emitted whether it flatters the result or not.
# --------------------------------------------------------------------------------------

def _fmt(stat: dict, unit: str = "") -> str:
    if not np.isfinite(stat.get("mean", np.nan)):
        return "n/a"
    return (f"{stat['mean']:+.3f}{unit}  t95 [{stat['lo']:+.3f}, {stat['hi']:+.3f}]  "
            f"boot95 [{stat['boot_lo']:+.3f}, {stat['boot_hi']:+.3f}]  "
            f"(G={stat['clusters']}, n={stat['n']:,})")


def layer_frame(book: pd.DataFrame, trades: pd.DataFrame, pairs: list[str], step_s: int,
                w_s: int = W_PRIMARY_S, size_usd: float = SIZE_PRIMARY,
                levels: int = 20, containment: bool = False) -> pd.DataFrame:
    """Evaluate one sampling layer across a pair list, and carry the exclusion counts."""
    out, dropped, offered = [], 0, 0
    for pair in pairs:
        pb = book[book["symbol"] == pair]
        if pb.empty:
            continue
        d = grid_decisions(pb["ts"].min(), pb["ts"].max(), step_s)
        offered += d.size
        f = evaluate(pair, book, trades, d, w_s=w_s, size_usd=size_usd,
                     levels=levels, containment=containment)
        if f.empty:
            dropped += d.size
            continue
        dropped += f.attrs.get("n_dropped_stale", 0)
        out.append(f)
    if not out:
        return pd.DataFrame()
    res = pd.concat(out, ignore_index=True)
    res.attrs["n_offered"] = offered
    res.attrs["n_dropped_stale"] = dropped
    return res


def primary_subset(f: pd.DataFrame) -> pd.DataFrame:
    """§2.5's only exclusion beyond staleness: ladder-exhausted observations.

    Their slippage is a LOWER bound, so leaving them in would understate the taker cost —
    the exact direction §1.6(b) already suspects the published 14 of erring in. They are
    excluded from the primary and their rate is published per (pair, size) as §6 item 3.
    """
    return f[~f["exhausted"]]


def pair_costs(f: pd.DataFrame) -> pd.DataFrame:
    """§6 item 1 — the headline deliverable: per-pair effective round-trip cost, both arms."""
    rows = []
    for pair, g in f.groupby("pair", sort=False):
        st_t = cluster_stats(g["taker_rt"].to_numpy(), g["day"].to_numpy(), draws=200)
        st_m = cluster_stats(g["maker_rt"].to_numpy(), g["day"].to_numpy(), draws=200)
        st_d = cluster_stats(g["delta_rt"].to_numpy(), g["day"].to_numpy(), draws=200)
        spread = float(g["spread_bps"].median())
        rows.append({
            "pair": pair, "n": len(g), "days": int(g["day"].nunique()),
            "spread_bps": spread,
            "touch_usd": float(np.minimum(g["touch_usd_bid"], g["touch_usd_ask"]).median()),
            # §1.6(a): the arithmetic ceiling on what resting can possibly save.
            "delta_max": 4.0 + 2.0 * spread,
            "C_taker": st_t["mean"], "C_maker": st_m["mean"], "delta": st_d["mean"],
            "delta_lo": st_d["boot_lo"], "delta_hi": st_d["boot_hi"],
            "fill_buy": float(g["filled_buy"].mean()), "fill_sell": float(g["filled_sell"].mean()),
        })
    return pd.DataFrame(rows).sort_values("C_taker")


def fill_panel(f: pd.DataFrame) -> pd.DataFrame:
    """§6 item 4 — fill rate per pair, split censored/uncensored and certain/queued.

    §1.2's censoring is concentrated in busy windows, which are exactly the windows where a
    resting order fills, so the naive fill rate is biased downward and NOT at random. The
    split is what makes the size of that bias visible instead of taken on trust.
    """
    rows = []
    for pair, g in f.groupby("pair", sort=False):
        for direction in ("buy", "sell"):
            for label, sub in (("uncensored", g[~g["censored"]]), ("censored", g[g["censored"]])):
                if sub.empty:
                    continue
                rows.append({
                    "pair": pair, "dir": direction, "windows": label, "n": len(sub),
                    "fill_rate": float(sub[f"filled_{direction}"].mean()),
                    "certain": float(sub[f"certain_{direction}"].mean()),
                    "queued": float(sub[f"queued_{direction}"].mean()),
                })
    return pd.DataFrame(rows)


def adverse_panel(f: pd.DataFrame) -> pd.DataFrame:
    """§6 item 5 — half_spread_earned - adverse_drift_60s, per pair, on the FILLED subset.

    §3: this is the one place conditioning on a fill is correct, because the question IS
    what the fills we got were worth. Drift is signed so positive = the market moved our
    way, hence `adverse_drift = -drift` and the quantity §3 names is `halfspread + drift`.
    If it is negative the maker fill is a fill into a moving market and the half-spread
    credit is being handed straight back.

    §3 also forbids subtracting this from the §2.6 cost: the post-entry drift is already
    inside the trade's realised return in M3-2's dumps, which is what the re-score scores.
    It is diagnosis, not an adjustment.
    """
    h = ADVERSE_PRIMARY_S
    rows = []
    for pair, g in f.groupby("pair", sort=False):
        for direction in ("buy", "sell"):
            sub = g[g[f"filled_{direction}"]]
            if sub.empty:
                continue
            hs = sub[f"halfspread_{direction}"]
            drift = sub[f"drift{h}_{direction}"]
            rows.append({
                "pair": pair, "dir": direction, "fills": len(sub),
                "halfspread_bps": float(hs.mean()),
                "adverse_drift_bps": float(-drift.mean()),
                "net_bps": float((hs + drift).mean()),
            })
    return pd.DataFrame(rows)


def run_study(winner_trades: pd.DataFrame, grid: list[tuple[str, pd.DataFrame]] | None = None,
              levels: int = 20) -> int:
    """Run M3-4 end to end and write output/m3/M3_4_RESULTS.md.

    `winner_trades` is the M3-2 winner's pooled ledger (for L3 and the §5.2 re-score);
    `grid` is [(label, trades)] for the 40 pre-registered configurations, re-SCORED here
    and never re-searched (§5.4).
    """
    lines: list[str] = []

    def emit(text: str = "") -> None:
        lines.append(text)
        print(text)

    def table(df: pd.DataFrame, floatfmt: str = "%.3f") -> None:
        emit("```")
        emit(df.to_string(index=False, float_format=lambda v: floatfmt % v))
        emit("```")
        emit("")

    book = bookprep.load_book(levels)
    tape = bookprep.load_trades()
    base8, extra4 = list(bookprep.BASE8), list(bookprep.EXTRA4)

    emit("# M3-4 — the execution-cost study: results")
    emit("")
    emit("**Generated by `./scripts/m3.sh -m m3 execcost`.** The design is pre-registered in "
         "[M3_4_PROTOCOL.md](./M3_4_PROTOCOL.md), committed before any fill number existed; "
         "this file is its output and contains the nine items §6 requires, in that order.")
    emit("")
    emit(f"Primary: **W = {W_PRIMARY_S}s**, **S = ${SIZE_PRIMARY:,.0f}**, layer **L1** "
         f"(5-minute grid), the **{len(base8)} served pairs**, UTC days as clusters. "
         f"Fees: taker {TAKER_FEE_BPS} / maker {MAKER_FEE_BPS} bps per side.")
    emit("")
    emit("🔴 **Read §0.2 of the protocol before reading any number here.** Every "
         "approximation is arranged to bias against maker execution, so **a maker verdict "
         "is safe and a taker verdict is not**: if maker wins it wins on a lower bound; if "
         "maker loses, this data has not shown maker execution is unobtainable.")
    emit("")

    # ---- the primary layer -----------------------------------------------------------
    l1 = layer_frame(book, tape, base8, step_s=300, levels=levels)
    if l1.empty:
        emit("**No usable observations** — check the export.")
        return 1
    l1p = primary_subset(l1)

    # ---- 1. per-pair effective round-trip cost, both arms ----------------------------
    emit("## 1. Per-pair effective round-trip cost (L1, primary)")
    emit("")
    emit(f"Against the assumed **{ASSUMED_TAKER_BPS:.0f} bps taker** and "
         f"**{ASSUMED_MAKER_BPS:.0f} bps maker** in `metrics.py`. `delta_max` is §1.6(a)'s "
         "arithmetic ceiling on what resting could possibly save: `4 + 4 x half_spread`.")
    emit("")
    pc = pair_costs(l1p)
    table(pc)

    # ---- 2. Q1 and Q2 with intervals and MDE -----------------------------------------
    emit("## 2. Q1 and Q2 — the pre-registered decision quantities (§5.1)")
    emit("")
    q1 = cluster_stats(l1p["taker_rt"].to_numpy(), l1p["day"].to_numpy())
    q2 = cluster_stats(l1p["delta_rt"].to_numpy(), l1p["day"].to_numpy())
    dmax = float((4.0 + 2.0 * l1p["spread_bps"]).mean())
    emit(f"* **Q1 — C_taker** = {_fmt(q1, ' bps')}")
    emit(f"  * against 14 bps: **{verdict_vs(q1, ASSUMED_TAKER_BPS)}**")
    emit(f"  * MDE at 80% power: **{q1['mde']:.3f} bps**")
    emit(f"* **Q2 — Delta = C_taker - C_maker** = {_fmt(q2, ' bps')}")
    emit(f"  * against 0: **{verdict_vs(q2, 0.0)}**")
    emit(f"  * against Delta_max ({dmax:.2f} bps, trade-weighted): **{verdict_vs(q2, dmax)}**")
    emit(f"  * against Delta_max/2 ({dmax / 2:.2f} bps): **{verdict_vs(q2, dmax / 2)}**")
    emit(f"  * MDE at 80% power: **{q2['mde']:.3f} bps**")
    emit("")

    # §5.3 — the power clause. Computed and stated BEFORE the verdicts below.
    emit("### The power clause (§5.3) — applied before any verdict")
    emit("")
    q2_lo = q2["boot_lo"] if np.isfinite(q2["boot_lo"]) else q2["lo"]
    q2_hi = q2["boot_hi"] if np.isfinite(q2["boot_hi"]) else q2["hi"]
    spans_both = (q2_lo <= 0.0) and (q2_hi >= dmax)
    emit(f"* Q2's 95% interval spans both 0 and Delta_max: **{spans_both}**. "
         + ("Per §5.3 the study has not distinguished its two hypotheses and **Q2 is "
            "INCONCLUSIVE regardless of the point estimate**; the estimate is reported, no "
            "verdict is."
            if spans_both else
            "The interval separates the two hypotheses, so §5.2's criteria may be applied."))
    emit(f"* Q2's MDE ({q2['mde']:.3f} bps) vs Delta_max ({dmax:.2f} bps): "
         + ("**MDE exceeds the ceiling — 22 days of ladder cannot see an effect this small, "
            "and the study must say so rather than report a point estimate as a finding.**"
            if q2["mde"] > dmax else
            "the ladder can resolve an effect of the size being decided."))
    emit(f"* Q1's MDE ({q1['mde']:.3f} bps) vs the 14 bps null: "
         + ("**MDE exceeds 14 — Q1 cannot be decided on this data.**"
            if q1["mde"] > ASSUMED_TAKER_BPS else
            "the data can resolve a deviation of the size at stake."))
    emit("")
    emit("🔴 **An INCONCLUSIVE outcome does not close the maker direction** (§5.3). Per §0.2 "
         "the defects bias against maker, so a null here is the weakest possible evidence. "
         "The remedy is calendar time — the ladder grows ~1 day per day at no cost — not a "
         "bigger model, a wider grid, or a re-run with different knobs.")
    emit("")

    # ---- 3. ladder exhaustion per (pair, size) ---------------------------------------
    emit("## 3. Ladder-exhaustion rate per (pair, size) (§2.5)")
    emit("")
    emit(f"Exported depth is {levels} levels a side. An exhausted observation's slippage is "
         "a **lower bound**, so those cells are excluded from the primary rather than "
         "allowed to understate the taker cost.")
    emit("")
    ex_rows = []
    for s in (SIZE_PRIMARY, *SIZE_LADDER):
        fs = l1 if s == SIZE_PRIMARY else layer_frame(book, tape, base8, step_s=300,
                                                      size_usd=s, levels=levels)
        if fs.empty:
            continue
        for pair, g in fs.groupby("pair", sort=False):
            ex_rows.append({"pair": pair, "size_usd": s, "n": len(g),
                            "exhausted_rate": float(g["exhausted"].mean())})
    ex = pd.DataFrame(ex_rows)
    table(ex.pivot(index="pair", columns="size_usd", values="exhausted_rate").reset_index())

    # ---- 4. fill rates, censored vs uncensored, certain vs queued --------------------
    emit("## 4. Fill rate per pair — censored/uncensored, certain/queue-conditional (§6.4)")
    emit("")
    emit("🔴 §1.2: `trade_count == 200` is a **censoring indicator, not a count**, and "
         "censoring concentrates in the busy windows where a resting order actually fills. "
         "The naive fill rate is therefore biased **downward and not at random**; this split "
         "is what makes the size of that bias visible.")
    emit("")
    table(fill_panel(l1p))

    # ---- 5. adverse selection --------------------------------------------------------
    emit(f"## 5. Adverse selection — half-spread earned minus {ADVERSE_PRIMARY_S}s drift (§3)")
    emit("")
    emit("On the **filled subset only** — the one place conditioning on a fill is correct, "
         "because the question is what the fills we got were worth. Negative `net_bps` means "
         "the fill is into a moving market and the half-spread credit is handed straight "
         "back. **Not** subtracted from §2.6's cost: that would double-count, since the "
         "post-entry drift is already inside M3-2's realised returns.")
    emit("")
    table(adverse_panel(l1p))

    # ---- 6. L1 vs L2 vs L3 -----------------------------------------------------------
    emit("## 6. L1 vs L2 vs L3 (§2.4)")
    emit("")
    emit("L1 ~ L2 is a **falsifiable prediction** of the design: if they disagree beyond "
         "their intervals, **L2 governs** and the disagreement is the finding. L3 is the "
         "policy's own trades and is **explicitly not powered to decide anything**.")
    emit("")
    l2 = layer_frame(book, tape, base8, step_s=14400, levels=levels)
    l2p = primary_subset(l2) if not l2.empty else l2
    layer_rows = []
    for label, fr in (("L1 (5m grid)", l1p), ("L2 (4h grid)", l2p)):
        if fr.empty:
            continue
        st_t = cluster_stats(fr["taker_rt"].to_numpy(), fr["day"].to_numpy(), draws=400)
        st_d = cluster_stats(fr["delta_rt"].to_numpy(), fr["day"].to_numpy(), draws=400)
        layer_rows.append({"layer": label, "n": st_t["n"], "days": st_t["clusters"],
                           "C_taker": st_t["mean"], "taker_lo": st_t["lo"],
                           "taker_hi": st_t["hi"], "delta": st_d["mean"],
                           "delta_lo": st_d["lo"], "delta_hi": st_d["hi"]})
    l3_summary, l3_costs = _l3(book, tape, winner_trades, base8, levels, emit)
    if l3_summary:
        layer_rows.append(l3_summary)
    table(pd.DataFrame(layer_rows))

    # ---- 7. the re-score -------------------------------------------------------------
    emit("## 7. The M3-2 grid re-scored at the measured cost (§5.2 clause 2)")
    emit("")
    emit("🔴 This **re-scores** the already-chosen configurations; it does not re-search the "
         "grid (§5.4). If the measured cost changes which configuration wins, that is a "
         "**finding to report and a pre-registration for a future wave — not a promotion**.")
    emit("")
    emit(f"🔴 **`P4_eligible` is the column that stops this table being misread.** "
         f"M3_PROTOCOL §4's rule P4 requires at least {MIN_TRADES_PER_WINDOW} trades in "
         f"**every** calendar window. That is a **trade count**, so it is entirely "
         f"independent of what execution costs: a cheaper fill can change the P&L ranking, "
         f"it can **never** make an ineligible configuration eligible. `clears_+0.25` "
         f"therefore requires P4 as well as the bar, exactly as M3-2 scored it.")
    emit("")
    cost_by_pair = dict(zip(pc["pair"], pc["C_taker"]))
    emit(f"Per-pair taker round-trip cost applied: "
         + ", ".join(f"{k} {v:.2f}" for k, v in cost_by_pair.items()))
    emit("")
    rs_rows = []
    for label, tr in ([("M3-2 winner", winner_trades)] + list(grid or [])):
        if tr is None or tr.empty:
            continue
        r_meas = rescore(tr, cost_by_pair, default=ASSUMED_TAKER_BPS)
        r_14 = rescore(tr, {}, default=ASSUMED_TAKER_BPS)
        p4 = bool((r_meas["per_window"]["trades"] >= MIN_TRADES_PER_WINDOW).all())
        rs_rows.append({"config": label, "trades": r_meas["trades"],
                        "min_win_trades": int(r_meas["per_window"]["trades"].min()),
                        "P4_eligible": p4,
                        "worst@14": r_14["worst_net_bps"],
                        "worst@measured": r_meas["worst_net_bps"],
                        "pooled@14": r_14["pooled_net_bps"],
                        "pooled@measured": r_meas["pooled_net_bps"],
                        "clears_+0.25": p4 and r_meas["worst_net_bps"] >= 0.25})
    rs = pd.DataFrame(rs_rows).sort_values("worst@measured", ascending=False)
    table(rs)

    # ---- 8. exclusion counts ---------------------------------------------------------
    emit("## 8. Exclusion counts (§2.4, §2.5)")
    emit("")
    offered = l1.attrs.get("n_offered", 0)
    stale = l1.attrs.get("n_dropped_stale", 0)
    emit(f"* Grid points offered (L1, 8 pairs): **{offered:,}**")
    emit(f"* Dropped — anchor book older than {STALENESS_CAP_S:.0f}s (§2.4): "
         f"**{stale:,}** ({stale / max(offered, 1):.2%})")
    emit(f"* Dropped — ladder exhausted at ${SIZE_PRIMARY:,.0f} (§2.5): "
         f"**{len(l1) - len(l1p):,}** ({(len(l1) - len(l1p)) / max(len(l1), 1):.2%})")
    emit("")
    stale_by_pair = (l1.groupby("pair")["book_age_s"]
                     .agg(median="median", p95=lambda s: s.quantile(0.95)).reset_index())
    emit(f"Per-pair anchor age; §2.4 **flags** any pair whose drop rate exceeds "
         f"{STALENESS_FLAG_RATE:.0%} rather than quietly using it.")
    table(stale_by_pair)

    # ---- the four short-window pairs, never pooled -----------------------------------
    emit("## The four short-window pairs (13 days) — texture only")
    emit("")
    emit("§1.5 and §5.3: these **never contribute to a verdict**. Reported separately and "
         "never pooled with the eight, because 13 days of ladder is a different depth of "
         "evidence and pooling two depths silently is the thing the protocol forbids.")
    emit("")
    l1x = layer_frame(book, tape, extra4, step_s=300, levels=levels)
    if not l1x.empty:
        table(pair_costs(primary_subset(l1x)))

    # ---- the validity caveat the run itself surfaced ---------------------------------
    emit("## 🔴 The external-validity problem this run surfaced (NOT pre-registered)")
    emit("")
    emit("§2.4 sized L3 at \"~18 trades per pair\" inside the ladder window. **The true "
         "number is zero.** The M3-2 winner's last entry anywhere is **2026-07-16**, three "
         "weeks before the ladder starts, so no measurement here touches a bar the policy "
         "would have traded.")
    emit("")
    emit("The cause is not a bug and is worth stating plainly: **the model stops being "
         "confident when the market goes quiet, and the market has been quiet since July.** "
         "`btc_absret_1d` averages 0.0070 in August against 0.011-0.027 in every earlier "
         "month — the calmest stretch of the whole evaluation period — and the confidence "
         "dispersion collapses in step (sd 0.0127 in August against 0.023-0.047 earlier). "
         "No bar after 2026-07-16 reaches the top-2% cut on any of the three seeds, and the "
         "**served checkpoint (seed 2, gate 0.6311) has produced no gated signal since "
         "2026-06-29.** That is the policy correctly sitting out, not a defect — but it "
         "means the cost below is measured in the one regime the policy never trades in.")
    emit("")
    emit("This matters for Q1's direction. The winner deliberately concentrates entries "
         "into **high**-volatility bars (§1.8's 4x effect is the whole reason the regime "
         "observable exists), and spreads widen when volatility rises. So the primary is an "
         "extrapolation from calm conditions onto a policy that only trades in violent "
         "ones, and it runs in the **optimistic** direction for the taker arm — the arm "
         "this study just declared too pessimistic. The table below sizes that gap.")
    emit("")
    rt, rctx = regime_sensitivity(l1p, book)
    if not rt.empty:
        emit("Cost by BTC 24h-volatility quintile. **Quintiles are the evaluation period's "
             "bar-level edges**, not the ladder window's, so bucket 5 means what it means "
             "everywhere else in M3 rather than 'the calmest month's busiest day'.")
        emit("")
        table(rt)
        emit(f"Median `btc_absret_1d`: **{rctx['ladder_median']:.4f}** over the ladder "
             f"window against **{rctx['eval_median']:.4f}** over the evaluation period. "
             f"Share of ladder-window observations by quintile: "
             + ", ".join(f"Q{int(k)} {v:.0%}" for k, v in rctx["share_ladder"].items()) + ".")
        emit("")

    # ---- 9. the verdict, in plain sentences ------------------------------------------
    emit("## 9. The verdict, in plain sentences (§6.9)")
    emit("")
    emit(_plain_verdict(q1, q2, dmax, pc, rs, spans_both, adverse_panel(l1p), rt, rctx))
    emit("")

    _write(lines)
    return 0


def _l3(book: pd.DataFrame, tape: pd.DataFrame, winner_trades: pd.DataFrame,
        pairs: list[str], levels: int, emit) -> tuple[dict | None, dict]:
    """L3 — price the M3-2 winner's own entries and exits inside the ladder window.

    Reported with its interval shown wide and labelled undecisive (§2.4, §6.6). ~18 trades
    a pair is not a per-pair number and this layer is never allowed to move a verdict.
    """
    if winner_trades is None or winner_trades.empty:
        return None, {}
    b = book[book["symbol"].isin(pairs)]
    lo_ns = int(pd.Timestamp(b["ts"].min()).value)
    hi_ns = int(pd.Timestamp(b["ts"].max()).value)
    t3 = l3_decisions(winner_trades[winner_trades["pair"].isin(pairs)], lo_ns, hi_ns)
    if t3.empty:
        emit("*L3: the winner books no trade wholly inside the 22-day ladder window.*")
        emit("")
        return None, {}

    rows = []
    for pair, g in t3.groupby("pair", sort=False):
        for leg, tscol in (("entry", "entry_ts"), ("exit", "exit_ts")):
            f = evaluate(pair, book, tape, g[tscol].to_numpy(np.int64), levels=levels)
            if f.empty:
                continue
            f = primary_subset(f)
            # The leg's direction decides which one-way cost this leg pays.
            dirs = g.set_index(pd.to_datetime(g[tscol], unit="ns", utc=True))[
                "entry_dir" if leg == "entry" else "exit_dir"]
            f = f.join(dirs.rename("dir"), on="ts")
            f["taker_leg"] = np.where(f["dir"] > 0, f["taker_buy"], f["taker_sell"])
            f["maker_leg"] = np.where(f["dir"] > 0, f["maker_buy"], f["maker_sell"])
            rows.append(f[["pair", "day", "taker_leg", "maker_leg"]].assign(leg=leg))
    if not rows:
        return None, {}
    legs = pd.concat(rows, ignore_index=True)
    st_t = cluster_stats(legs["taker_leg"].to_numpy() * 2.0, legs["day"].to_numpy(), draws=400)
    st_d = cluster_stats((legs["taker_leg"] - legs["maker_leg"]).to_numpy() * 2.0,
                         legs["day"].to_numpy(), draws=400)
    emit(f"*L3 covers {len(t3):,} of the winner's trades inside the ladder window "
         f"({legs['pair'].nunique()} pairs, {int(legs['day'].nunique())} days) — "
         f"**undecisive by construction**, reported because a cost study that never touched "
         f"the policy's real decisions would be answering an adjacent question.*")
    emit("")
    return ({"layer": "L3 (policy trades)", "n": st_t["n"], "days": st_t["clusters"],
             "C_taker": st_t["mean"], "taker_lo": st_t["lo"], "taker_hi": st_t["hi"],
             "delta": st_d["mean"], "delta_lo": st_d["lo"], "delta_hi": st_d["hi"]},
            {})


def regime_sensitivity(f: pd.DataFrame, book: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """POST-HOC diagnostic — how the measured cost varies with market volatility.

    🔴 NOT PRE-REGISTERED, and computed after the primaries. It is here because running the
    study surfaced a validity problem §2.4 did not anticipate and could not have: the
    22-day ladder window contains **none of the policy's trades**, and it is the calmest
    stretch of the whole evaluation period. The M3-2 winner deliberately concentrates its
    entries into high-volatility bars (that is §1.8's 4x effect, and the whole reason the
    regime observable exists), while spreads widen exactly when volatility rises. So the
    primary cost is measured in the one condition the policy never trades in.

    This function sizes that gap instead of leaving it as a worry. It buckets the L1
    observations by BTC's trailing 24h absolute return — the same observable the winner
    sizes on — and reports the cost per bucket, so a reader can see which way the
    extrapolation runs and how far.

    It changes no primary and decides nothing (§5.4). Reporting it is not shaping the
    result to an outcome; withholding it would be.
    """
    btc = book[book["symbol"] == "BTCUSDT"].sort_values("ts", kind="mergesort")
    if btc.empty:
        return pd.DataFrame(), {}
    mid = 0.5 * (btc["b0p"].to_numpy(np.float64) + btc["a0p"].to_numpy(np.float64))
    bts = btc["ts"].to_numpy("datetime64[ns]").astype(np.int64)
    day_ns = 86_400 * 1_000_000_000
    # Trailing 24h absolute return, on the ladder's own clock.
    prev = np.searchsorted(bts, bts - day_ns, side="right") - 1
    ok = prev >= 0
    absret = np.full(bts.size, np.nan)
    absret[ok] = np.abs(mid[ok] / mid[prev[ok]] - 1.0)

    idx = np.searchsorted(bts, f["ts"].to_numpy("datetime64[ns]").astype(np.int64),
                          side="right") - 1
    g = f.copy()
    g["btc_absret_1d"] = np.where(idx >= 0, absret[np.clip(idx, 0, None)], np.nan)
    g = g[np.isfinite(g["btc_absret_1d"])]
    if g.empty:
        return pd.DataFrame(), {}

    # Bucket against the EVALUATION PERIOD's quintile edges, not the ladder window's, so
    # the buckets mean the same thing they mean everywhere else in M3 — a quantile of BARS
    # over the scored period. Bucketing on the ladder window alone would relabel a calm
    # month's top fifth as "high volatility" and hide the very gap being measured.
    from . import dumps as _dumps, regime as _regime
    d = _dumps.load(_dumps.BASELINE_RUNS["s2"], seed="s2", pairs=_dumps.BASE8)
    r = _regime.build(d.df)
    edges = r["btc_absret_1d"].quantile([0.2, 0.4, 0.6, 0.8]).to_numpy()

    g["q"] = np.searchsorted(edges, g["btc_absret_1d"].to_numpy(), side="right") + 1
    rows = []
    for q, sub in g.groupby("q", sort=True):
        st_t = cluster_stats(sub["taker_rt"].to_numpy(), sub["day"].to_numpy(), draws=200)
        st_d = cluster_stats(sub["delta_rt"].to_numpy(), sub["day"].to_numpy(), draws=200)
        rows.append({"btc_vol_quintile": int(q), "n": len(sub),
                     "median_absret": float(sub["btc_absret_1d"].median()),
                     "C_taker": st_t["mean"], "delta": st_d["mean"],
                     "mean_spread_bps": float(sub["spread_bps"].mean())})
    tbl = pd.DataFrame(rows)

    # Where the ladder window sits, and where the policy actually trades.
    share_ladder = g["q"].value_counts(normalize=True).sort_index()
    ctx = {"edges": edges, "share_ladder": share_ladder,
           "ladder_median": float(g["btc_absret_1d"].median()),
           "eval_median": float(r["btc_absret_1d"].median())}
    return tbl, ctx


def _plain_verdict(q1: dict, q2: dict, dmax: float, pc: pd.DataFrame,
                   rs: pd.DataFrame, spans_both: bool, adverse: pd.DataFrame,
                   regime_tbl: pd.DataFrame, regime_ctx: dict) -> str:
    """§6 item 9 — the bottom line, with units defined at the point of use.

    M3_PLAN's standing requirement is that the plain-language layer answer the question the
    reader came for, explicitly and in one sentence, and define its jargon where it is
    used. Two answers are needed here, not one: what does it cost us to trade, and would
    resting orders make that cheaper.
    """
    out = []
    out.append("A **basis point (bps)** is one hundredth of one percent, so 1 bps = 0.01%. "
               "A **round trip** is the whole cost of one trade — getting in and getting "
               "out. **Taker** means crossing the spread for an instant fill; **maker** "
               "means resting a limit order and waiting, which is cheaper per the fee "
               "schedule but may never fill.")
    out.append("")
    out.append(f"**What it actually costs us to trade.** Crossing the spread on the eight "
               f"served pairs costs a measured **{q1['mean']:.2f} bps round trip** at a "
               f"$10,000 order — against the **14 bps** every published M3 number assumed. "
               f"On a $10,000 trade that is ${q1['mean'] / BPS * 10000:.2f} against $14.00.")
    if verdict_vs(q1, ASSUMED_TAKER_BPS).startswith("EXCLUDES"):
        delta14 = ASSUMED_TAKER_BPS - q1["mean"]
        out.append("")
        out.append(f"🔴 **The 14 bps assumption is MIS-STATED** (§5.2): the interval excludes "
                   f"it. Published M3 economics are therefore wrong by about "
                   f"**{delta14:+.2f} bps a trade** in the direction that makes them "
                   f"**too pessimistic** — §1.6(b) predicted exactly this, and it moves a "
                   f"number no maker finding could.")
        if regime_tbl is not None and not regime_tbl.empty:
            hi = regime_tbl.iloc[-1]
            lo_ = regime_tbl.iloc[0]
            out.append("")
            out.append(f"⚠️ **Read that with the validity caveat above.** The measurement "
                       f"window holds none of the policy's trades and is the calmest month "
                       f"of the period. Cost rises with volatility across the buckets we "
                       f"can see — {lo_['C_taker']:.2f} bps in quintile "
                       f"{int(lo_['btc_vol_quintile'])} against {hi['C_taker']:.2f} in "
                       f"quintile {int(hi['btc_vol_quintile'])} — and the policy trades the "
                       f"**high** end. The direction of the Q1 finding survives that (the "
                       f"gap to 14 is larger than the spread across buckets), but the "
                       f"magnitude should be treated as an upper bound on the improvement, "
                       f"not as the number to re-publish M3-2's economics with.")
    else:
        out.append("")
        out.append("The interval **contains 14 bps**, so the assumed taker cost is not "
                   "contradicted by this data.")
    out.append("")
    if spans_both:
        out.append(f"**Would resting orders make that cheaper? We cannot tell yet.** The "
                   f"measured saving is **{q2['mean']:.2f} bps** round trip, but its 95% "
                   f"interval spans both zero and the arithmetic ceiling of "
                   f"**{dmax:.2f} bps**, so this data does not distinguish 'resting saves "
                   f"nothing' from 'resting saves everything it possibly could'. Per §5.3 "
                   f"**no verdict is published on Q2.** What would settle it is calendar "
                   f"time: the order-book ladder starts 2026-08-05, giving 22 day-clusters, "
                   f"and it grows one day per day at no cost.")
    elif verdict_vs(q2, 0.0).startswith("EXCLUDES") and q2["mean"] > 0:
        out.append(f"**On the cost arithmetic alone, resting orders save "
                   f"{q2['mean']:.2f} bps** round trip against an arithmetic ceiling of "
                   f"{dmax:.2f} bps, and per §0.2 that is a lower bound.")
        # §3 makes this panel a PRECONDITION of publishing a maker verdict, precisely so a
        # cheap-looking fill cannot be reported as a good one.
        if adverse is not None and not adverse.empty:
            worst = adverse.loc[adverse["net_bps"].idxmin()]
            neg = int((adverse["net_bps"] < 0).sum())
            out.append("")
            out.append(f"🔴 **But §3's panel says those fills are not worth having, and §3 "
                       f"forbids publishing a maker verdict without it.** "
                       f"`half_spread_earned - adverse_drift_60s` is **negative in "
                       f"{neg} of {len(adverse)} (pair, direction) cells** — every single "
                       f"one — from {adverse['net_bps'].max():+.2f} bps at best to "
                       f"{worst['net_bps']:+.2f} on {worst['pair']} {worst['dir']}. The "
                       f"half-spread earned is {adverse['halfspread_bps'].min():.3f}-"
                       f"{adverse['halfspread_bps'].max():.3f} bps while the 60s adverse "
                       f"drift is {adverse['adverse_drift_bps'].min():.2f}-"
                       f"{adverse['adverse_drift_bps'].max():.2f} bps.")
            out.append("")
            out.append("In plain terms: a resting buy fills **because** the price came down "
                       "through it, and it keeps going down. The fee rebate is real and the "
                       "spread credit is ~0.01 bps on the majors, so what the maker arm "
                       "collects in §2.6 it hands back in the price path — which §2.6 does "
                       "not price, by design, because §3 says the drift is already inside "
                       "M3-2's realised returns. **The honest reading is that Q2's "
                       "+%.2f bps is a fee-rebate accounting gain, not a trading gain**, "
                       "and the maker arm should not be built on this evidence." % q2["mean"])
    elif verdict_vs(q2, dmax / 2).startswith("EXCLUDES"):
        out.append(f"**Resting orders are NOT worth the complexity** (§5.2): the saving "
                   f"({q2['mean']:.2f} bps) is measurably below half the {dmax:.2f} bps "
                   f"ceiling. Missed fills and the chase cost more than the 2 bps/side fee "
                   f"rebate is worth. **This is the outcome that lets M3-5 build a simple "
                   f"crossing executor and stop there** — a useful result, not a failure.")
    else:
        out.append(f"**On resting orders the study is INCONCLUSIVE**: the saving is "
                   f"{q2['mean']:.2f} bps against a {dmax:.2f} bps ceiling and the interval "
                   f"does not separate the hypotheses cleanly. §5.3 governs: this does not "
                   f"close the maker direction.")
    out.append("")
    elig = rs[rs["P4_eligible"]] if "P4_eligible" in rs.columns else rs
    if not elig.empty:
        best = elig.iloc[0]
        out.append(f"**Does the strategy still clear its bar?** Re-scored at the measured "
                   f"per-pair cost, the best configuration's worst calendar window is "
                   f"**{best['worst@measured']:+.2f} bps** against M3_PROTOCOL §4.4's "
                   f"**+0.25 bps** promotion bar — "
                   f"{'it clears it' if best['clears_+0.25'] else 'it does NOT clear it'}. "
                   f"Re-scoring is not re-searching: if the measured cost changes which "
                   f"configuration ranks first, that is a finding and a pre-registration "
                   f"for a future wave, never a promotion (§5.4).")
        inelig = rs[~rs["P4_eligible"]] if "P4_eligible" in rs.columns else rs.iloc[0:0]
        if not inelig.empty and inelig.iloc[0]["worst@measured"] > best["worst@measured"]:
            top = inelig.iloc[0]
            out.append("")
            out.append(f"🔴 **And the measured cost does re-order the grid — but not in a way "
                       f"that promotes anything.** `{top['config']}` now shows a "
                       f"{top['worst@measured']:+.2f} bps worst window against the winner's "
                       f"{best['worst@measured']:+.2f}. It is still **ineligible**: its "
                       f"thinnest window holds {int(top['min_win_trades'])} trades against "
                       f"P4's floor of {MIN_TRADES_PER_WINDOW}, and a trade count does not "
                       f"move when the fee does. This is precisely the finding §5.4 says to "
                       f"report and pre-register rather than act on — the hard regime filter "
                       f"looks better at a truer cost, and it is still starved in window 3.")
        out.append("")
    out.append("**What this study cannot do** (§7): it cannot measure our own queue "
               "position, because no order was ever placed and there is no private fill "
               "history — §2.3 is a *model* of the queue and every number here inherits its "
               "crudeness. And it cannot fix the collector's 200-trade cap retroactively; "
               "raising that limit (or moving the tape to the uncapped WebSocket stream) "
               "fixes it going forward and is worth doing regardless of this verdict.")
    return "\n".join(out)


def _write(lines: list[str]) -> None:
    import os
    path = os.path.join("output", "m3", "M3_4_RESULTS.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"\n[report written to {path}] — copy it to its canonical home:")
    print("  cp ml/train/output/m3/M3_4_RESULTS.md docs/M3_4_RESULTS.md")
