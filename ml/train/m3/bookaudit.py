"""B1 — the economic information check. BOOK_ERA_PLAN.md §B1, gated by §4.1.

## What this replaces, and why it is not "re-run the audit"

The 2026-08-04 microstructure audit came back **ESCALATE** on 31 stable hits with a strongest
`|Spearman|` of 0.177, the training run it triggered was inconclusive, and §1.4 of the plan
names the three defects that made the escalation unreliable:

  1. **no holdout** — sign and bucketing were chosen on the same rows they were scored on;
  2. **264 per-pair tests** — a scan wide enough that its best hit is what a scan returns;
  3. **rho as the unit** — a correlation cannot be compared against a fee, and the fee is
     what decides whether any of this is tradeable.

So this harness fixes all three rather than re-running the same design on more data:

  1. the book era is split in half chronologically; **every feature's direction and its
     percentile map come from half 1, and every reported number comes from half 2**;
  2. pairs are a **nuisance dimension**, not a scan — each feature is mapped onto its own
     within-pair percentile (the map fitted on half 1) and then pooled, so there is one test
     per (feature, horizon) instead of one per (feature, pair, horizon);
  3. everything is reported in **basis points per trade**, with the 5 bps maker and 14 bps
     taker round trips printed in the same table so the comparison cannot be avoided.

## The DIRECTIONAL / VOL-PROXY split, which is the useful part

§0.4 predicts the most likely outcome is not a second model but a **regime observable**, and
that depends on telling apart a feature that knows *which way* the next move goes from one
that knows *how big* it is. Measured directly, on half 2:

  * `dir_rho` — Spearman of the feature against **sign(fwd_ret)**: direction only.
  * `vol_rho` — Spearman of the feature against **|fwd_ret|**: magnitude only.

A feature with vol_rho and no dir_rho is a VOL-PROXY: useless to M2, which emits direction,
and potentially valuable to M3, whose largest measured effect is a volatility regime switch.
That hand-off is what B2 then tests.

## The gate

§4.1, pre-registered: B3 happens iff some feature, on half 2, at a horizon **≤ 60m**, has a
**top-5% mean signed return above +5 bps** with **n ≥ 2,000**, and its sign agrees between
half 1 and half 2. 🔴 Do not negotiate that number downward after seeing the result.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

BOOK_DIR = os.environ.get("M3_EXPORT_DIR", "output/m3_4")

# The nine scalars B0 built, grouped by the staleness flag that says whether a row's value
# is real. A row with has_book == 0 carries a ZERO, not a missing value (that is how
# features.py zero-fills), so scoring without the mask would rank real spreads against
# fabricated ones.
BOOK_FEATURES = ["spread_bps", "imbalance", "micro_mid", "bid_ask_vol_ratio", "depth_near_imb"]
TRADE_FEATURES = ["trade_count", "buy_sell_imb", "trade_vol"]
FUNDING_FEATURES = ["funding_rate"]
MASK_OF = ({f: "has_book" for f in BOOK_FEATURES}
           | {f: "has_trades" for f in TRADE_FEATURES}
           | {f: "has_funding" for f in FUNDING_FEATURES})
FEATURES = BOOK_FEATURES + TRADE_FEATURES + FUNDING_FEATURES

HORIZONS = [5, 15, 60, 240]        # 240 is the NEGATIVE CONTROL — see §B1
COVERAGES = [0.01, 0.02, 0.05, 0.10]
MAKER_BPS, TAKER_BPS = 5.0, 14.0
BPS = 1e4

# §4.1
GATE_MIN_BPS, GATE_MIN_N, GATE_MAX_HORIZON, GATE_COVERAGE = 5.0, 2000, 60, 0.05


def _clustered_se(x: np.ndarray, day: np.ndarray) -> tuple[float, int]:
    """Cluster-robust SE of a mean, clustered on the calendar day.

    🔴 The naive sd/sqrt(n) is badly wrong here and always in the optimistic direction. A
    60-minute forward return sampled on a 5-minute grid **overlaps its twelve neighbours**,
    and the same move is being counted once per pair across twelve correlated perpetuals.
    The 2026-08-04 audit's over-reading is what this whole step exists to avoid, so it uses
    the same estimator `metrics.clustered_mean_bps` uses on trades, for the same reason.
    """
    if x.size == 0:
        return float("nan"), 0
    resid = x - x.mean()
    sums = pd.Series(resid).groupby(pd.Series(day)).sum().to_numpy()
    g = sums.size
    if g < 2:
        return float("nan"), g
    var = (sums ** 2).sum() / (x.size ** 2) * (g / (g - 1.0))
    return float(np.sqrt(var)), int(g)


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    """Rank correlation without scipy — Pearson on average-tied ranks."""
    if a.size < 3:
        return float("nan")
    ra = pd.Series(a).rank().to_numpy()
    rb = pd.Series(b).rank().to_numpy()
    ra -= ra.mean()
    rb -= rb.mean()
    d = np.sqrt((ra * ra).sum() * (rb * rb).sum())
    return float((ra * rb).sum() / d) if d > 0 else float("nan")


def percentile_map(fit: np.ndarray, apply_to: np.ndarray, bins: int = 100) -> np.ndarray:
    """Map values onto [0,1] using an empirical CDF fitted on `fit` only.

    This is §B1's "decile mapping determined on half 1", at percentile rather than decile
    resolution. Fitting it on half 1 is what makes the pooling honest: the pooled column is
    on a common scale that half 2 never got to define, so a pair whose spread widened in
    half 2 shows up as a high percentile rather than silently re-centering the scale.
    """
    edges = np.quantile(fit, np.linspace(0.0, 1.0, bins + 1)[1:-1])
    return np.searchsorted(edges, apply_to, side="right") / bins


def build(interval: str = "5m") -> pd.DataFrame:
    path = os.path.join(BOOK_DIR, f"book_era_{interval}.parquet")
    if not os.path.exists(path):
        raise SystemExit(f"{path} missing — run `./scripts/m3.sh -m m3 bookera` (B0) first")
    return pd.read_parquet(path).sort_values(["pair", "ts"], kind="mergesort")


def halves(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Chronological split at the median timestamp — the same cut for every pair, so the two
    halves are the same two calendar periods rather than eight different ones."""
    cut = int(np.median(df["ts"].unique()))
    return df[df["ts"] < cut].copy(), df[df["ts"] >= cut].copy(), cut


def score(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The §B1 table: one pooled row per (feature, horizon, coverage), half-2 only."""
    h1, h2, cut = halves(df)
    rows, diag = [], []

    for feat in FEATURES:
        mask = MASK_OF[feat]
        a = h1[h1[mask] == 1]
        b = h2[h2[mask] == 1]
        if len(a) < 1000 or len(b) < 1000:
            continue

        # --- the percentile map, fitted per pair on half 1 -----------------------------
        u1 = np.full(len(a), np.nan)
        u2 = np.full(len(b), np.nan)
        for pair, idx in a.groupby("pair", observed=True).indices.items():
            fit = a[feat].to_numpy()[idx]
            u1[idx] = percentile_map(fit, fit)
            jdx = np.flatnonzero(b["pair"].to_numpy() == pair)
            if jdx.size:
                u2[jdx] = percentile_map(fit, b[feat].to_numpy()[jdx])
        ok1, ok2 = np.isfinite(u1), np.isfinite(u2)

        for h in HORIZONS:
            col = f"fwd_ret_{h}"
            r1 = a[col].to_numpy(np.float64)
            r2 = b[col].to_numpy(np.float64)
            m1 = ok1 & np.isfinite(r1)
            m2 = ok2 & np.isfinite(r2)
            if m1.sum() < 1000 or m2.sum() < 1000:
                continue

            # --- direction, fixed on half 1 -------------------------------------------
            rho1 = _spearman(u1[m1], r1[m1])
            s = 1.0 if (rho1 >= 0 or np.isnan(rho1)) else -1.0
            rho2 = _spearman(u2[m2], r2[m2])

            score1 = s * u1[m1]
            score2 = s * u2[m2]
            ret1, ret2 = r1[m1], r2[m2]
            day2 = (b["ts"].to_numpy()[m2] // (86_400 * 1_000_000_000))

            diag.append({
                "feature": feat, "h": h, "n_h2": int(m2.sum()),
                "rho_h1": rho1, "rho_h2": rho2,
                "sign_agrees": bool(np.sign(rho1) == np.sign(rho2)) if np.isfinite(rho1 * rho2) else False,
                # direction vs magnitude, measured apart. This is the classification §0.4 needs.
                "dir_rho": _spearman(score2, np.sign(ret2)),
                "vol_rho": _spearman(u2[m2], np.abs(ret2)),
            })

            # 🔴 THE DRIFT BASELINE, without which none of the bps below can be read.
            # The book era is three weeks of one market. If it drifted up, EVERY long-biased
            # slice earns that drift and a +25 bps number at 240m is the calendar, not the
            # feature. The plan's own negative control at 240m only works against this line.
            base_bps = float(ret2.mean() * BPS)
            for c in COVERAGES:
                k = max(int(round(len(score2) * c)), 1)
                sel = np.argpartition(score2, len(score2) - k)[len(score2) - k:]
                x = ret2[sel] * BPS
                cse, ncl = _clustered_se(x, day2[sel])
                cse_ex, _ = _clustered_se(x - base_bps, day2[sel])
                k1 = max(int(round(len(score1) * c)), 1)
                sel1 = np.argpartition(score1, len(score1) - k1)[len(score1) - k1:]
                rows.append({
                    "feature": feat, "h": h, "cov": c, "n": int(k),
                    "bps_h2": float(x.mean()), "sd_bps": float(x.std(ddof=1)),
                    "sem_bps": float(x.std(ddof=1) / np.sqrt(k)),
                    "bps_h1": float(ret1[sel1].mean() * BPS),
                    "absbps_h2": float(np.abs(x).mean()),
                    "all_bps": base_bps,
                    "excess_bps": float(x.mean()) - base_bps,
                    "clustered_se_bps": cse, "clusters": ncl,
                    "excess_lo95": float(x.mean()) - base_bps - 1.96 * cse_ex,
                    "excess_hi95": float(x.mean()) - base_bps + 1.96 * cse_ex,
                })

    return pd.DataFrame(rows), pd.DataFrame(diag), cut


def sd_by_horizon(df5: pd.DataFrame, df1: pd.DataFrame) -> pd.DataFrame:
    """§B1 point 4: the REAL per-horizon sd, replacing §1.2's sqrt(t) estimates.

    `fwd_ret_1` is not exported by B0, so the 1m row is derived here from the 1m grid's own
    closes — the same definition, computed rather than assumed, and labelled as derived.
    """
    rows = []
    d1 = df1.sort_values(["pair", "ts"], kind="mergesort").copy()
    d1["fwd_ret_1"] = d1.groupby("pair", observed=True)["close"].transform(
        lambda s: s.shift(-1) / s - 1.0)
    r = d1["fwd_ret_1"].dropna().to_numpy() * BPS
    rows.append({"h": 1, "source": "derived (1m closes)", "n": r.size,
                 "sd_bps": float(r.std(ddof=1)), "mean_abs_bps": float(np.abs(r).mean())})
    for h in HORIZONS:
        r = df5[f"fwd_ret_{h}"].dropna().to_numpy() * BPS
        rows.append({"h": h, "source": "book_era_5m", "n": r.size,
                     "sd_bps": float(r.std(ddof=1)), "mean_abs_bps": float(np.abs(r).mean())})
    out = pd.DataFrame(rows)
    # sqrt(t) from the 5m row, which is what §1.2 extrapolated from.
    base = out.loc[out["h"] == 5, "sd_bps"].iloc[0]
    out["sqrt_t_est"] = base * np.sqrt(out["h"] / 5.0)
    out["ratio"] = out["sd_bps"] / out["sqrt_t_est"]
    return out


def classify(d: pd.DataFrame) -> pd.DataFrame:
    """DIRECTIONAL / VOL-PROXY, from the two rhos measured apart on half 2."""
    out = d.copy()
    z = 1.96 / np.sqrt(out["n_h2"].clip(lower=4) - 3)      # Fisher-z SE for rho ~ 0
    directional = out["dir_rho"].abs() > z
    volproxy = out["vol_rho"].abs() > z
    out["class"] = np.select(
        [directional & volproxy, directional, volproxy],
        ["BOTH", "DIRECTIONAL", "VOL-PROXY"], default="NEITHER")
    out["rho_se"] = z
    return out


def gate(tbl: pd.DataFrame, diag: pd.DataFrame) -> dict:
    """§4.1, evaluated exactly as written — including whether it CAN be evaluated.

    🔴 The distinction this returns matters more than the verdict. §4.1 requires n >= 2,000
    in a top-5% slice, which needs >= 40,000 usable half-2 rows per (feature, horizon). The
    book era supplies ~39,700. So the gate as pre-registered is **unreachable by about 2%**,
    and reporting that as a FAIL would close B3 on a sample-size technicality rather than on
    evidence — the exact move `negative-results-need-the-same-scrutiny` forbids. A criterion
    has to be shown to have the power to decide before it is allowed to decide.
    """
    d = diag.set_index(["feature", "h"])
    elig = tbl[(tbl["cov"] == GATE_COVERAGE) & (tbl["h"] <= GATE_MAX_HORIZON)].copy()
    if elig.empty:
        return {"status": "NOT EVALUABLE", "pass": False,
                "why": "no (feature, horizon <= 60m) slice exists at all"}
    elig["sign_agrees"] = [bool(d.loc[(r.feature, r.h), "sign_agrees"]) for r in elig.itertuples()]
    reachable = elig[elig["n"] >= GATE_MIN_N]
    agreeing = elig[elig["sign_agrees"]]

    # The best slice that satisfies everything EXCEPT the unreachable n floor, so the reader
    # sees what the evidence actually looks like rather than only that the gate did not run.
    best = agreeing.loc[agreeing["bps_h2"].idxmax()] if len(agreeing) else None
    shown = (f"best sign-agreeing slice is {best['feature']} @ {int(best['h'])}m: "
             f"{best['bps_h2']:+.2f} bps raw / {best['excess_bps']:+.2f} bps in excess of the "
             f"period's own drift, on n={int(best['n']):,}" if best is not None
             else "no slice had its sign agree between the halves")

    if reachable.empty:
        return {
            "status": "NOT EVALUABLE", "pass": False, "best": best,
            "why": (f"§4.1 needs n >= {GATE_MIN_N:,} in a top-{GATE_COVERAGE:.0%} slice, which "
                    f"takes >= {int(GATE_MIN_N / GATE_COVERAGE):,} usable half-2 rows; the book "
                    f"era supplies {int(elig['n'].max() / GATE_COVERAGE):,}. The gate is short by "
                    f"~{1 - elig['n'].max() / GATE_MIN_N:.0%} and cannot be run as written."),
            "shown": shown,
        }
    cand = reachable[reachable["sign_agrees"]]
    if cand.empty:
        return {"status": "EVALUATED", "pass": False, "best": best,
                "why": "no eligible slice had its sign agree between the halves", "shown": shown}
    b = cand.loc[cand["bps_h2"].idxmax()]
    return {"status": "EVALUATED", "pass": bool(b["bps_h2"] > GATE_MIN_BPS), "best": b,
            "why": (f"best eligible slice is {b['feature']} @ {int(b['h'])}m: "
                    f"{b['bps_h2']:+.2f} bps on n={int(b['n']):,} "
                    f"(needs > +{GATE_MIN_BPS:.0f})"),
            "shown": shown}
