"""Rebuilding the Q1 regime observables — NEXT_TRAINING_PLAN §1.8's harness, which was
never committed (M3_PLAN §1.4 flags this as risk #6).

THE TRICK THAT MAKES THIS FREE. The dumps carry no price series, only `fwd_ret` — the
return realised by a trade opened at that bar and held the full horizon. But `fwd_ret` at
horizon h, *shifted back h minutes*, is the trailing return over the last h minutes, and it
is lookahead-free by construction: the value attached to bar t was fully realised by t.
Q1 built every observable it tested this way, with no DB round-trip, and the three horizons
compound to 3.2e-7, which `check_compounding()` here re-verifies.

WHAT IS VERIFIED AND WHAT IS NOT. Only `btc_absret_1d` is pinned by an acceptance test
(validate.py reproduces §1.8's quintile ladder from it). It is also the only observable
§1.8 recommends: the others were either U-shaped, seed-unstable or flat. The rest are
rebuilt here so the AUC table can be re-derived as a cross-check, but a policy should not
condition on them without first re-running that check — see M3_PLAN §1.3.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .dumps import NS

MIN_NS = 60 * NS


def trailing_return(df: pd.DataFrame, horizon: int, pairs: list[str] | None = None) -> pd.DataFrame:
    """Per-pair trailing return over the last `horizon` minutes, as a (pair, ts) frame.

    `fwd_ret` on bar (t - horizon) is the return from t-horizon to t, i.e. exactly the
    trailing return at t. So the construction is a shift of the ts index forward by the
    horizon; no price series is needed and nothing from the future is used.
    """
    h = df[df["horizon"] == horizon]
    if pairs is not None:
        h = h[h["pair"].isin(pairs)]
    out = h[["pair", "ts", "fwd_ret"]].copy()
    out["ts"] = out["ts"] + horizon * MIN_NS      # the bar the return is trailing AT
    out = out.rename(columns={"fwd_ret": f"trail_{horizon}m"})
    return out.reset_index(drop=True)


def check_compounding(df: pd.DataFrame, pair: str = "BTCUSDT") -> float:
    """Re-verify §1.8's claim that the horizons compound (it reported max abs diff 3.2e-7).

    Four consecutive 60m forward returns starting at t must compound to the 240m forward
    return at t. If this fails the dump is not what §1.2 says it is and nothing downstream
    is trustworthy.
    """
    p = df[df["pair"] == pair]
    r60 = p[p["horizon"] == 60].set_index("ts")["fwd_ret"].astype("float64")
    r240 = p[p["horizon"] == 240].set_index("ts")["fwd_ret"].astype("float64")
    compounded = None
    for k in range(4):
        leg = r60.copy()
        leg.index = leg.index - k * 60 * MIN_NS   # the 60m return k hours into the trade
        compounded = (1.0 + leg) if compounded is None else compounded * (1.0 + leg)
    compounded = compounded - 1.0
    joined = pd.concat([compounded.rename("c"), r240.rename("r")], axis=1).dropna()
    return float((joined["c"] - joined["r"]).abs().max())


def build(df: pd.DataFrame, btc: str = "BTCUSDT") -> pd.DataFrame:
    """Return a (pair, ts) frame of regime observables aligned to the 240m bars.

    Market-wide observables (the `btc_*` family) are computed once and broadcast to every
    pair; per-pair ones are computed per pair. Bars whose lookback is not fully available
    carry NaN and are excluded by the consumers rather than silently zero-filled.
    """
    grid = df[df["horizon"] == 240][["pair", "ts"]].copy().reset_index(drop=True)

    # --- market-wide: BTC trailing moves -------------------------------------------
    btc_1d = trailing_return(df, 1440, pairs=[btc]).drop(columns="pair")
    btc_1d = btc_1d.rename(columns={"trail_1440m": "btc_ret_1d"})
    btc_1d["btc_absret_1d"] = btc_1d["btc_ret_1d"].abs()
    btc_1d["btc_sign_1d"] = np.sign(btc_1d["btc_ret_1d"])

    # 7d as the compound of seven daily legs, so it uses the same lookahead-free values.
    legs = btc_1d.set_index("ts")["btc_ret_1d"].astype("float64")
    compounded = None
    for k in range(7):
        leg = legs.copy()
        leg.index = leg.index + k * 1440 * MIN_NS
        compounded = (1.0 + leg) if compounded is None else compounded * (1.0 + leg)
    btc_7d = (compounded - 1.0).rename("btc_ret_7d").reset_index()

    market = btc_1d.merge(btc_7d, on="ts", how="left")
    out = grid.merge(market, on="ts", how="left")

    # --- per-pair: realised vol over trailing 1h returns ----------------------------
    # rv_Nd = sd of the pair's trailing-60m returns over the last N days, annualised-free
    # (kept in raw return units — only its *ordering* is ever used).
    r1h = trailing_return(df, 60).rename(columns={"trail_60m": "r1h"})
    r1h = r1h.sort_values(["pair", "ts"], kind="mergesort")
    for days, name in ((1, "rv_1d"), (7, "rv_7d"), (30, "rv_30d")):
        bars = days * 24 * 12          # 5m bars in N days
        r1h[name] = (
            r1h.groupby("pair", observed=True)["r1h"]
            .transform(lambda s, b=bars: s.rolling(b, min_periods=max(12, b // 4)).std())
        )
    out = out.merge(r1h.drop(columns="r1h"), on=["pair", "ts"], how="left")

    # --- cross-sectional dispersion of 4h moves -------------------------------------
    r4h = trailing_return(df, 240)
    disp = r4h.groupby("ts", observed=True)["trail_240m"].std().rename("xs_disp_4h").reset_index()
    out = out.merge(disp, on="ts", how="left")
    # The per-pair value is carried through too: it is the momentum-side control of
    # M3_PROTOCOL §3.2 ("side from sign(trailing 240m return)"), which needs a per-pair
    # trailing move rather than a cross-sectional summary of one.
    out = out.merge(r4h, on=["pair", "ts"], how="left")

    # --- the model's own trailing confidence ----------------------------------------
    # §1.8 found this ANTI-predictive in all three seeds (AUC 0.480/0.471/0.499). It is
    # rebuilt only so that finding can be re-checked; do not build a policy term on it.
    conf = df[df["horizon"] == 240][["pair", "ts", "conf"]].sort_values(
        ["pair", "ts"], kind="mergesort"
    )
    conf["mean_conf_1d"] = (
        conf.groupby("pair", observed=True)["conf"]
        .transform(lambda s: s.rolling(288, min_periods=72).mean())
    )
    out = out.merge(conf.drop(columns="conf"), on=["pair", "ts"], how="left")

    return out


OBSERVABLES = [
    "btc_absret_1d", "btc_ret_1d", "btc_sign_1d", "btc_ret_7d",
    "rv_1d", "rv_7d", "rv_30d", "xs_disp_4h", "trail_240m", "mean_conf_1d",
]

# §1.8's rule, stated as a number so drift is visible: BTC trailing-24h |return| >= 4.31%,
# which was 5.2% of validation bars. Never hard-code it into a policy — M3_PLAN §M3-2 says
# the threshold must be re-derived per split — but do check the rebuild lands near it.
PUBLISHED_REGIME_THRESHOLD = 0.0431
PUBLISHED_REGIME_BAR_FRACTION = 0.052
