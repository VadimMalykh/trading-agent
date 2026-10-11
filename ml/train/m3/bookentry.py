"""BOOK_WAVE2_PLAN §E1 — book-timed entry: the incumbent's trades, the entry minute moved.

The live rule decides at a 5-minute bar's close and fills taker at once. Every arm here takes
the incumbent's trades exactly — same (seed, pair, entry_ts, side, size) — and changes ONE
thing: the entry may wait up to K minutes for the 1m book state to agree with the trade's
side. The hold stays 240 minutes from the actual entry; the exit moves with it.

  imb<K>     enter at the first minute k ≤ K where sign(imbalance) = side, else at K
  micro<K>   the same on sign(micro_mid)
  both<K>    both signs agree
  fixed<K>   CONTROL — always minute K, no book read (plain waiting)
  coin15     NULL — a per-trade uniform minute in 1..15, seeded
  null0      HARNESS — K = 0, must reproduce the incumbent exactly

Timing (§E1, fixed before any number): decision time T0 = entry_ts + 5 min, the 5m close,
which is the close of the 1m bar opening at entry_ts + 4 min. Minute k's price is the close
of the 1m bar opening at T0 + (k − 1) min, i.e. the price at T0 + k min; the book state read
there is the 1m table's row at open time T0 + k min — the last snapshot at or before that
instant, never a later one. Exit = the close of the 1m bar opening at (actual entry) + 239
min, i.e. 240 min after the actual entry. A minute without a `has_book` row cannot agree; a
trade with no book row in 1..K at all enters at T0 (a fallback, counted, cap 10 %).

The contrast is §9.6's: arm − incumbent, net bps per unit of notional, cluster-robust on UTC
exit days, pooled over the three served-family seeds; fees cancel. The gate is mechanical and
written in §E1: best book arm > 0 pooled, > 0 on the median seed, > 0 against its own
fixed-delay control.

🔴 The exploration population (the book era to 2026-09-09) was read by B1/B2/B3/X7: it can
close the question, not establish it. The confirmation is on forward `policy_bars` nobody has
read, once, on or after 2027-03-10, in the same look as X7.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from . import backtest, bookregime, dumps, metrics, regime
from . import walkforward as wf

# The served family: X8″'s three seeds (WALKFORWARD_PROTOCOL §10.8; BACKLOG X8-F). s3 is the
# served checkpoint m2_multi_20261003T191545Z_117836a9.pt.
RUNS = {"s1": "20261001T155917Z", "s2": "20261002T053534Z", "s3": "20261003T191545Z"}
SERVED_SEED = "s3"
COVERAGE = 0.05
COVERAGE_INFO = 0.02
INCUMBENT = bookregime.INCUMBENT
CONFIRM_ON_OR_AFTER = "2027-03-10"
CONFIRM_DAYS = 180.0
COST = metrics.TAKER_COST_BPS
SIZES = np.array([1.0, 2.0, 3.0, 4.0, 5.0]) / 3.0
MIN_NS = 60 * 1_000_000_000
HOLD_MIN = 240
DECISION_OFFSET_MIN = 5            # entry_ts is the 5m bar's open; the decision is its close
FALLBACK_MAX = 0.10
ACCEPT_EXACT_MIN = 0.999
ACCEPT_TOL = 1e-6
COIN_SEED = 20261011
ARMS = {                           # the list IS the registration (§E1)
    "imb5": ("imb", 5), "imb15": ("imb", 15),
    "micro5": ("micro", 5), "micro15": ("micro", 15),
    "both5": ("both", 5), "both15": ("both", 15),
    "fixed5": ("fixed", 5), "fixed15": ("fixed", 15),
    "coin15": ("coin", 15),
    "null0": ("fixed", 0),
}
BOOK_ARMS = ["imb5", "imb15", "micro5", "micro15", "both5", "both15"]
CONTROL_OF = {"imb5": "fixed5", "micro5": "fixed5", "both5": "fixed5",
              "imb15": "fixed15", "micro15": "fixed15", "both15": "fixed15"}


# --------------------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------------------

def load_dumps(pairs: list[str] | None = None) -> list[dumps.Dump]:
    return [dumps.load(r, seed=s, pairs=pairs) for s, r in RUNS.items()]


def load_1m() -> pd.DataFrame:
    path = os.path.join(bookregime.BOOK_DIR, "book_era_1m.parquet")
    if not os.path.exists(path):
        raise SystemExit(f"{path} missing — B0's 1m table (`m3 bookera`) is the grid")
    cols = ["pair", "ts", "close", "imbalance", "micro_mid", "has_book"]
    b = pd.read_parquet(path, columns=cols)
    b["pair"] = b["pair"].astype(str)
    return b.sort_values(["pair", "ts"], kind="mergesort").reset_index(drop=True)


class Grid:
    """Per-pair 1m arrays, indexed by exact open-time lookup."""

    def __init__(self, table: pd.DataFrame):
        self.by: dict[str, dict[str, np.ndarray]] = {}
        for p, g in table.groupby("pair", sort=False):
            self.by[p] = {"ts": g["ts"].to_numpy(np.int64),
                          "close": g["close"].to_numpy(np.float64),
                          "imb": g["imbalance"].to_numpy(np.float64),
                          "micro": g["micro_mid"].to_numpy(np.float64),
                          "has_book": g["has_book"].to_numpy(np.int64)}
        t = pd.to_datetime(table["ts"], unit="ns", utc=True)
        self.span = (f"{len(table):,} 1m rows x {table['pair'].nunique()} pairs, "
                     f"{t.min():%Y-%m-%d %H:%M} .. {t.max():%Y-%m-%d %H:%M}")

    def idx(self, pair: str, ts: int) -> int:
        """Row index of the 1m bar opening exactly at `ts`, or -1."""
        g = self.by.get(pair)
        if g is None:
            return -1
        k = int(np.searchsorted(g["ts"], ts))
        return k if k < g["ts"].size and g["ts"][k] == ts else -1


def population(ds: list[dumps.Dump], book5: pd.DataFrame) -> tuple[list[dumps.Dump], dict]:
    """Each seed's bars restricted to the book era (5m rows with has_book) and to rows where the
    incumbent's regime key is present — X7's restriction, minus the book keys it does not need."""
    keys = book5[["pair", "ts"]].drop_duplicates()
    out_ds, regimes = [], {}
    for d in ds:
        de = bookregime.restrict(d, keys)
        r = regime.build(de.df)
        r = r[r[INCUMBENT].notna()].reset_index(drop=True)
        out_ds.append(bookregime.restrict(de, r[["pair", "ts"]]))
        regimes[d.seed] = r
    return out_ds, regimes


def incumbent(ds: list[dumps.Dump], regimes: dict, spec_fields: dict, coverage: float) -> pd.DataFrame:
    f = {**spec_fields, "coverage": coverage, "regime_col": INCUMBENT, "size_by_regime": True}
    t = backtest.run(ds, backtest.PolicySpec(label="incumbent", **f), regimes).trades
    return t.sort_values(["seed", "pair", "entry_ts"], kind="mergesort").reset_index(drop=True)


# --------------------------------------------------------------------------------------
# the arms
# --------------------------------------------------------------------------------------

def rebuild(inc: pd.DataFrame, grid: Grid) -> tuple[np.ndarray, np.ndarray]:
    """(entry close at T0, exit close 240 min later) on the 1m grid; NaN where a bar is missing."""
    n = len(inc)
    e = np.full(n, np.nan)
    x = np.full(n, np.nan)
    pairs = inc["pair"].astype(str).to_numpy()
    entry = inc["entry_ts"].to_numpy(np.int64)
    for i in range(n):
        g = grid.by.get(pairs[i])
        if g is None:
            continue
        ke = grid.idx(pairs[i], entry[i] + (DECISION_OFFSET_MIN - 1) * MIN_NS)
        kx = grid.idx(pairs[i], entry[i] + (DECISION_OFFSET_MIN - 1 + HOLD_MIN) * MIN_NS)
        if ke >= 0:
            e[i] = g["close"][ke]
        if kx >= 0:
            x[i] = g["close"][kx]
    return e, x


def walk_arm(inc: pd.DataFrame, grid: Grid, mode: str, K: int, rng: np.random.Generator | None = None
             ) -> pd.DataFrame:
    """One arm: every incumbent trade re-entered at minute k ≤ K chosen by `mode`."""
    n = len(inc)
    pairs = inc["pair"].astype(str).to_numpy()
    entry = inc["entry_ts"].to_numpy(np.int64)
    side = inc["side"].to_numpy(np.float64)
    size = inc["size"].to_numpy(np.float64)
    ret = inc["fwd_ret"].to_numpy(np.float64).copy()
    exit_ts = inc["exit_ts"].to_numpy(np.int64).copy()
    delay = np.zeros(n, dtype=np.int64)
    at_cap = np.zeros(n, dtype=bool)
    fallback = np.zeros(n, dtype=bool)
    coin = rng.integers(1, K + 1, size=n) if mode == "coin" else None
    for i in range(n):
        g = grid.by.get(pairs[i])
        t0 = entry[i] + DECISION_OFFSET_MIN * MIN_NS
        if g is None:
            fallback[i] = True
            continue
        k_pick = 0
        if mode == "fixed":
            k_pick = K
        elif mode == "coin":
            k_pick = int(coin[i])
        else:
            seen_book = False
            k_pick = K
            for k in range(1, K + 1):
                kb = grid.idx(pairs[i], t0 + k * MIN_NS)
                if kb < 0 or g["has_book"][kb] != 1:
                    continue
                seen_book = True
                s_imb = np.sign(g["imb"][kb])
                s_mic = np.sign(g["micro"][kb])
                if mode == "imb":
                    ok = s_imb == side[i]
                elif mode == "micro":
                    ok = s_mic == side[i]
                else:
                    ok = (s_imb == side[i]) and (s_mic == side[i])
                if ok:
                    k_pick = k
                    break
            if not seen_book:
                fallback[i] = True
                continue
        # price at T0 + k min = close of the 1m bar opening at T0 + (k − 1) min; k = 0 is T0 itself
        ke = grid.idx(pairs[i], t0 + (k_pick - 1) * MIN_NS)
        kx = grid.idx(pairs[i], t0 + (k_pick - 1 + HOLD_MIN) * MIN_NS)
        if ke < 0 or kx < 0:
            fallback[i] = True
            continue
        ret[i] = g["close"][kx] / g["close"][ke] - 1.0
        # the incumbent's own convention (entry_ts + 240 min, bar-open based) plus the delay, so
        # null0's exit_ts equals the incumbent's exactly and day clusters move only with k
        exit_ts[i] = entry[i] + (HOLD_MIN + k_pick) * MIN_NS
        delay[i] = k_pick
        at_cap[i] = (K > 0) and (k_pick == K) and mode not in ("fixed", "coin")
    out = inc.copy()
    out["fwd_ret"] = ret
    out["signed_ret"] = side * ret * size
    out["exit_ts"] = exit_ts
    out["delay_min"] = delay
    out["at_cap"] = at_cap
    out["fallback"] = fallback
    return out


def overlaps(arm: pd.DataFrame) -> int:
    """Arm trades whose (moved) exit lands after the pair's next incumbent decision time."""
    a = arm.sort_values(["seed", "pair", "entry_ts"], kind="mergesort")
    nxt = a.groupby(["seed", "pair"], sort=False)["entry_ts"].shift(-1)
    nxt_decision = nxt + DECISION_OFFSET_MIN * MIN_NS
    return int(((a["exit_ts"] > nxt_decision) & nxt.notna()).sum())


# --------------------------------------------------------------------------------------
# checks and statistics
# --------------------------------------------------------------------------------------

def check_acceptance(inc: pd.DataFrame, grid: Grid) -> tuple[bool, str]:
    e, x = rebuild(inc, grid)
    have = np.isfinite(e) & np.isfinite(x)
    r = x / e - 1.0
    f = inc["fwd_ret"].to_numpy(np.float64)
    exact = int((r[have].astype(np.float32) == f[have].astype(np.float32)).sum())
    close = int((np.abs(r[have] - f[have]) <= ACCEPT_TOL).sum())
    n = int(have.sum())
    ok = n == len(inc) and close == n and exact >= ACCEPT_EXACT_MIN * n
    return ok, (f"1m rebuild of the 240m return: {exact:,}/{n:,} exact at float32, {close:,} within "
                f"{ACCEPT_TOL:g}, {len(inc) - n} unmatched bars")


def check_null(null: pd.DataFrame, inc: pd.DataFrame) -> tuple[bool, str]:
    dr = float(np.abs(null["signed_ret"].to_numpy() - inc["signed_ret"].to_numpy()).max()) if len(inc) else 0.0
    fb = int(null["fallback"].sum())
    return (dr <= ACCEPT_TOL and fb == 0 and len(null) == len(inc)), \
        f"null0: max |Δ signed_ret| {dr:.1e}, fallbacks {fb}, {len(null):,} vs {len(inc):,} trades"


def check_same_trades(a: pd.DataFrame, inc: pd.DataFrame) -> tuple[bool, str]:
    cols = ["seed", "pair", "entry_ts"]
    same = len(a) == len(inc) and bool((a[cols].to_numpy() == inc[cols].to_numpy()).all()) \
        and bool(np.allclose(a["size"].to_numpy(), inc["size"].to_numpy()))
    fb = float(a["fallback"].mean()) if len(a) else 0.0
    return same and fb <= FALLBACK_MAX, f"identical trades and sizes={same}, fallbacks {fb:.2%}"


def ledger(t: pd.DataFrame) -> pd.DataFrame:
    return wf._ledger(wf._utc_day(t["exit_ts"]), t["signed_ret"].to_numpy(np.float64),
                      t["size"].to_numpy(np.float64), "trade")


def contrast(a: pd.DataFrame, b: pd.DataFrame) -> dict:
    return wf.paired_notional_diff_bps(ledger(a), ledger(b))


def _span_days(t: pd.DataFrame) -> float:
    return float((t["exit_ts"].max() - t["entry_ts"].min()) / 86_400e9) if len(t) else 0.0


def table(arms: dict[str, pd.DataFrame], inc: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for name, t in arms.items():
        if name == "null0":
            continue
        c = contrast(t, inc)
        per = {s: contrast(t[t["seed"] == s], inc[inc["seed"] == s])["diff_bps"] for s in RUNS}
        ctrl = CONTROL_OF.get(name)
        vs_ctrl = contrast(t, arms[ctrl])["diff_bps"] if ctrl else float("nan")
        d = t["delay_min"].to_numpy()
        rows.append({"arm": name, "vs incumbent": c["diff_bps"],
                     "95% CI": f"[{c['lo95_bps']:+.2f}, {c['hi95_bps']:+.2f}]", "se": c["se_bps"],
                     "days": c["clusters"], "s1": per["s1"], "s2": per["s2"], "s3": per["s3"],
                     "median seed": float(np.median(list(per.values()))),
                     "vs control": vs_ctrl,
                     "delay mean/p90": f"{d.mean():.1f}/{np.percentile(d, 90):.0f}",
                     "at cap": float(t["at_cap"].mean()), "fallback": int(t["fallback"].sum()),
                     "overlaps": overlaps(t),
                     "net/notional @14": wf.notional_ratio_bps(ledger(t), COST)["mean_bps"]})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# the report
# --------------------------------------------------------------------------------------

def report(spec_fields: dict, stage: str, exploration_recorded: bool = False,
           config: str | None = None) -> int:
    print("=" * 100)
    print(f"BOOK_WAVE2_PLAN §E1 — BOOK-TIMED ENTRY, PAIRED ON THE INCUMBENT'S TRADES — stage {stage.upper()}")
    print("=" * 100)
    if stage == "confirm":
        today = pd.Timestamp.now(tz="UTC").normalize()
        if today < pd.Timestamp(CONFIRM_ON_OR_AFTER, tz="UTC"):
            print(f"\n🔴 refusing: §E1's confirmation is read once, on or after {CONFIRM_ON_OR_AFTER}, "
                  f"in the same look as X7; no earlier look at the forward window is permitted.")
            return 2
        if not exploration_recorded or not config:
            print("\n🔴 refusing: pass --exploration-recorded and --config <arm> transcribed from §E1.")
            return 2
        print("\n🔴 the confirmation loader (forward policy_bars + 1m candles and snapshots) is built "
              "when due, from §E1's confirmation paragraph. It does not exist yet.")
        return 2
    if stage != "explore":
        raise SystemExit(f"stage must be explore or confirm, got {stage!r}")

    print("\n🔴 NOT CLEAN EVIDENCE: B1/B2/B3/X7 already read these bars. This stage can close the")
    print("   question; only the forward confirmation can establish it.")
    book5 = _book5()
    pairs = sorted(book5["pair"].unique())
    ds = load_dumps(pairs)
    ds_pop, regimes = population(ds, book5)
    for d in ds_pop:
        t = pd.to_datetime(d.df["ts"], unit="ns", utc=True)
        print(f"  {d.seed} ({d.run_id}): {d.df[['pair', 'ts']].drop_duplicates().shape[0]:,} bars x "
              f"{d.df['pair'].nunique()} pairs, {t.min():%Y-%m-%d %H:%M} .. {t.max():%Y-%m-%d %H:%M}")
    grid = Grid(load_1m())
    print(f"  1m grid: {grid.span}")

    rc = 0
    for cov in (COVERAGE, COVERAGE_INFO):
        label = "PRIMARY" if cov == COVERAGE else "information only"
        print("\n" + "=" * 100)
        print(f"COVERAGE {cov} — {label}")
        print("=" * 100)
        inc = incumbent(ds_pop, regimes, spec_fields, cov)
        ok, msg = check_acceptance(inc, grid)
        print(f"  harness check 1 (acceptance): {'PASS' if ok else 'FAIL'} — {msg}")
        bad = not ok
        rng = np.random.default_rng(COIN_SEED)
        arms = {name: walk_arm(inc, grid, mode, K, rng=rng) for name, (mode, K) in ARMS.items()}
        ok, msg = check_null(arms["null0"], inc)
        print(f"  harness check 2 (null0 = incumbent): {'PASS' if ok else 'FAIL'} — {msg}")
        bad |= not ok
        for name, t in arms.items():
            ok, msg = check_same_trades(t, inc)
            if not ok:
                print(f"  harness check 3/4 ({name}): FAIL — {msg}")
            bad |= not ok
        if bad:
            print("  🔴 harness check failed; nothing below may be read.")
            return 3
        print(f"  harness checks 3/4: every arm holds the incumbent's {len(inc):,} trades and sizes, "
              f"fallbacks ≤ {FALLBACK_MAX:.0%} — PASS")
        ni = wf.notional_ratio_bps(ledger(inc), COST)
        print(f"  incumbent net/notional @14 {ni['mean_bps']:+.2f} [{ni['lo95_bps']:+.2f}, {ni['hi95_bps']:+.2f}] "
              f"on {ni['clusters']} days; span {_span_days(inc):.1f} days; "
              f"trades per seed {inc.groupby('seed').size().to_dict()}")
        tab = table(arms, inc)
        print(tab.to_string(index=False, float_format=lambda v: f"{v:+.2f}",
                            formatters={"at cap": lambda v: f"{v:.0%}"}))

        if cov != COVERAGE:
            continue
        book = tab[tab["arm"].isin(BOOK_ARMS)].sort_values("vs incumbent", ascending=False)
        best = book.iloc[0]
        name = best["arm"]
        s3 = contrast(arms[name][arms[name]["seed"] == SERVED_SEED], inc[inc["seed"] == SERVED_SEED])
        days = _span_days(inc)
        mde = 1.96 * s3["se_bps"] * np.sqrt(days / CONFIRM_DAYS) if days else float("nan")
        g1, g2, g3 = best["vs incumbent"] > 0, best["median seed"] > 0, best["vs control"] > 0
        print("\n" + "=" * 100)
        print("THE VERDICT, under §E1 as written")
        print("=" * 100)
        print(f"  chosen by the rule (highest pooled contrast among the six book arms): {name}  "
              f"{best['vs incumbent']:+.2f} {best['95% CI']}; median seed {best['median seed']:+.2f}; "
              f"vs its control {CONTROL_OF[name]} {best['vs control']:+.2f}")
        print(f"  forecast confirmation MDE ({SERVED_SEED}-only SE {s3['se_bps']:.2f} x sqrt({days:.0f}/{CONFIRM_DAYS:.0f}) x 1.96): "
              f"{mde:.2f} bps per notional")
        print(f"  gate: (i) best > 0 -> {g1}; (ii) median seed > 0 -> {g2}; (iii) > its fixed-delay control -> {g3}")
        passed = g1 and g2 and g3
        verdict = (f"GATE PASSED — transcribe the table into §E1 and add the confirmation row to BACKLOG, "
                   f"dated {CONFIRM_ON_OR_AFTER}, arm {name}") if passed else \
            "GATE NOT PASSED — §E1 closes on these bars; no other scalar, threshold, K or exit convention"
        print(f"\n  ==> {verdict}")
    return rc


def _book5() -> pd.DataFrame:
    """The 5m book-era table's (pair, ts) rows with a book — the bar population (§E1)."""
    path = os.path.join(bookregime.BOOK_DIR, "book_era_5m.parquet")
    if not os.path.exists(path):
        raise SystemExit(f"{path} missing — run `m3 bookera` (B0) first")
    b = pd.read_parquet(path, columns=["pair", "ts", "has_book"])
    b["pair"] = b["pair"].astype(str)
    return b[b["has_book"] == 1][["pair", "ts"]].reset_index(drop=True)
