"""Scoring a set of trades.

Two rules run through everything here, both from M3_PLAN:

  * **Never one fee number.** Maker (5bps) and taker (14bps) round trips are reported side
    by side, because at cov05 the same slice is +3.91 at maker and -5.09 at taker — the two
    numbers disagree about whether the strategy exists (§3.3). `net = gross - cost` exactly,
    per trade, so changing the fee assumption never needs a re-run.
  * **Never pooled-only.** Every table breaks out the four calendar windows and the worst
    one is called out, because §1.8's regime rule is +35bps pooled and -10bps in the window
    holding 47% of its trades (§M3-1).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MAKER_COST_BPS, TAKER_COST_BPS = 5.0, 14.0
BPS = 1e4


def wilson_lower_bound(hits: int, n: int, z: float = 1.96) -> float:
    """Mirror of gate.wilson_lower_bound (kept identical so tables stay comparable)."""
    if n == 0:
        return 0.0
    p = hits / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / denom


def max_drawdown(equity: np.ndarray) -> float:
    """Peak-to-trough of an additive equity curve, in return units (negative)."""
    if equity.size == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    return float((equity - peak).min())


def daily_sharpe(trades: pd.DataFrame, ann: float = 365.0) -> float:
    """Sharpe of daily summed trade P&L, annualised. Booked on the EXIT day: the P&L is
    not knowable until the position closes, and booking it on entry would make a 4h hold
    look like it earned its return before it did."""
    if trades.empty:
        return 0.0
    day = pd.to_datetime(trades["exit_ts"], unit="ns", utc=True).dt.floor("D")
    daily = trades.groupby(day)["net_ret"].sum()
    if daily.std(ddof=1) == 0 or len(daily) < 2:
        return 0.0
    return float(daily.mean() / daily.std(ddof=1) * np.sqrt(ann))


def summarise(trades: pd.DataFrame, cost_bps: float, span_days: float | None = None,
              n_seeds: int = 1) -> dict:
    """One row of results for a trade set, at one fee assumption.

    `net_ret` is written back onto a copy so drawdown and Sharpe are computed net of fees —
    a gross equity curve understates drawdown, and the fee is what makes several of these
    strategies marginal in the first place.
    """
    t = trades.copy()
    t["net_ret"] = t["signed_ret"] - cost_bps / BPS * t.get("size", 1.0)
    n = len(t)
    if n == 0:
        return {"trades": 0, "gross_bps": 0.0, "net_bps": 0.0, "win": 0.0,
                "maxdd": 0.0, "sharpe": 0.0, "trades_per_day": 0.0}
    t = t.sort_values("exit_ts", kind="mergesort")
    out = {
        "trades": n,
        "gross_bps": float(t["signed_ret"].mean() * BPS),
        "net_bps": float(t["net_ret"].mean() * BPS),
        "win": float((t["signed_ret"] > 0).mean()),
        "maxdd": max_drawdown(t["net_ret"].cumsum().to_numpy()),
        "sharpe": daily_sharpe(t),
    }
    if span_days:
        # Per-seed rate: pooling three seeds triples the trade count but is still one
        # strategy, so the tradeable rate is the pooled count divided by the seeds.
        out["trades_per_day"] = n / n_seeds / span_days
    return out


def span_days(trades: pd.DataFrame) -> float:
    if trades.empty:
        return 0.0
    t = pd.to_datetime(trades["entry_ts"], unit="ns", utc=True)
    return max((t.max() - t.min()).total_seconds() / 86400.0, 1.0)


def fmt_table(rows: list[dict], cols: list[tuple[str, str, str]]) -> str:
    """rows -> aligned text table. cols is [(key, header, format)]."""
    head = "  ".join(f"{h:>{max(len(h), 8)}}" for _, h, _ in cols)
    lines = [head]
    for r in rows:
        cells = []
        for key, h, fmt in cols:
            v = r.get(key, "")
            s = format(v, fmt) if isinstance(v, (int, float, np.floating)) and fmt else str(v)
            cells.append(f"{s:>{max(len(h), 8)}}")
        lines.append("  ".join(cells))
    return "\n".join(lines)


def by_window(trades: pd.DataFrame, cost_bps: float) -> pd.DataFrame:
    """Per-calendar-window scoring. The row that matters is the worst one."""
    from .dumps import add_window
    t = add_window(trades, ts_col="entry_ts")
    rows = []
    for name in ["w1", "w2", "w3", "w4"]:
        sub = t[t["window"] == name]
        rows.append({"window": name, **summarise(sub, cost_bps, span_days(sub))})
    return pd.DataFrame(rows)


def side_split(trades: pd.DataFrame, cost_bps: float) -> pd.DataFrame:
    """§1.3: side balance is not seed-stable, so long and short are always reported apart."""
    rows = []
    for label, sel in (("long", trades["side"] > 0), ("short", trades["side"] < 0)):
        sub = trades[sel]
        rows.append({"side": label, **summarise(sub, cost_bps, span_days(sub))})
    return pd.DataFrame(rows)
