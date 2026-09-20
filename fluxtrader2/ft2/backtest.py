"""P3 — the harness (PLAN §4 P3). `ft2 backtest <strategy>` → output/backtest/<name>/.

What it guarantees, so that a strategy cannot get any of it wrong:

  walk-forward   A fold is cut into blocks of REFIT_DAYS. Before each block the strategy's `fit` is
                 handed the market strictly before the block and labels that END before it; `decide`
                 is handed the market up to the block's end. `causal_check` re-runs a block on a
                 market truncated mid-block: a decision that changes was made with data from its future.
  the ledger     DECISIONS (what, when, which side, what size, why — and whether the book rule took
                 it) and FILLS (prices, every cost component, net) are separate tables. `price` turns
                 one into the other, so fees, latency and taker/maker are re-priced without re-deciding.
  the cost       P1's pair × day series (data/cost_daily.parquet), per leg, at the day of that leg:
                   taker  fee + half the calibrated spread + impact at NOTIONAL
                   maker  simulated on the bars, per leg: a limit order rests at the execution bar's close
                          for MAKER_WAIT bars; it is filled at that price (maker fee, nothing else) only if
                          a later bar trades THROUGH it, otherwise the leg crosses as a taker at the close
                          MAKER_WAIT bars on. Which orders fill depends on the path, so the adverse
                          selection is the rule's own: a reversal order that is not filled is the one
                          whose price already ran away.
                   maker_ev  P1's unconditional version, for reference: the day's measured fill share p
                          at (fee − post-fill drift), the other 1 − p at the taker leg, as an expected value.
                 Funding is the signed sum of the archive's events while the position is open (a long
                 pays a positive rate). A leg on a day P1 could not price (censored depth) is not
                 guessed: the trade is counted as `unpriced` and left out.
  latency        A decision at t (the bar closed at t) is executed at the close LATENCY bars later.
  the book rule  One open position per pair; a decision made while one is open is recorded and skipped.
  statistics     Mean net bps per unit of notional, interval clustered by day (ratio estimator, HAC
                 over days — holds cross midnight), its MDE, and the same per fold and per pair.
  noise floor    The whole pipeline — fit included, when the strategy uses labels — on labels whose
                 days were shuffled (`ceiling._shuffle_days`), `draws` times. Costs stay real, so the
                 null centres on minus the cost and the p-value is one-sided.
  folds          F1+F2 by default. A confirmation fold is read only with `--registration R<n>`, only if
                 that block exists in docs/PLAN.md §8, and only once per registration; every such read
                 is appended to output/backtest/confirmation_reads.csv.

A strategy is a `Strategy` subclass: `hold` (bars), `uses_labels`, `fit(M, y, now)`, `decide(M, a, b)`.
`decide` returns `decisions_from(...)`. Registered by name in `STRATEGIES` (P4's rules: ft2/rules.py).
"""
from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from . import ceiling, data, folds
from .ceiling import BAR, MDE_K, NOTIONAL, MAKER_H, hac, day_lags
from .cost import DAILY

OUT = Path("output/backtest")
READS = OUT / "confirmation_reads.csv"
PLAN = Path("docs/PLAN.md")
LATENCY = 1              # bars between the decision and the execution price
REFIT_DAYS = 30          # a block: the strategy is refitted (if it fits anything) this often
MAKER_WAIT = 3           # bars a maker order rests before the leg crosses as a taker (= P1's MAKER_H of 15 minutes)
EXECS = ("taker", "maker", "maker_ev")


# ---- the market a strategy sees -----------------------------------------------------------------------
@dataclasses.dataclass
class Market:
    """Wide frames indexed by decision time t (the bar closed at t). Nothing here is a cost or a label."""
    close: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    dv: pd.DataFrame
    extra: dict[str, pd.DataFrame] = dataclasses.field(default_factory=dict)

    @property
    def index(self) -> pd.DatetimeIndex:
        return self.close.index

    @property
    def columns(self) -> pd.Index:
        return self.close.columns

    def until(self, t: pd.Timestamp) -> "Market":
        """The market strictly before t."""
        n = self.index.searchsorted(t)
        return Market(self.close.iloc[:n], self.high.iloc[:n], self.low.iloc[:n], self.dv.iloc[:n], {k: v.iloc[:n] for k, v in self.extra.items()})


def market(symbols: list[str], end: pd.Timestamp) -> Market:
    P = ceiling.panel(symbols, end)
    return Market(P["close"], P["high"], P["low"], P["dv"])


@dataclasses.dataclass
class Costs:
    days: pd.DatetimeIndex
    taker_leg: np.ndarray        # day × pair, bps per side, fee excluded: half the calibrated spread + impact at NOTIONAL
    maker_adv: np.ndarray        # day × pair, bps: drift after a maker fill vs the resting price (negative = adverse)
    maker_fill: np.ndarray       # day × pair: share of resting orders filled within MAKER_H minutes
    fundcum: np.ndarray          # bar × pair: cumulative funding rate, bps, over events stamped ≤ t


def _ns(x) -> np.ndarray:
    return pd.DatetimeIndex(x).as_unit("ns").asi8


def load_costs(index: pd.DatetimeIndex, cols: pd.Index, end: pd.Timestamp) -> Costs:
    d = pd.read_parquet(DAILY)
    d = d[d["day"] < end]
    d["symbol"] = d["symbol"].astype(str)
    piv = lambda c: d.pivot(index="day", columns="symbol", values=c).reindex(columns=cols)      # noqa: E731
    sp = piv("spread_cal_bps")
    f = data.load("funding_archive", columns=["symbol", "ts", "rate"], symbols=list(cols))
    f = f[f["ts"] < end]
    cum = np.zeros((len(index), len(cols)))
    for j, sym in enumerate(cols):
        e = f[f["symbol"].astype(str) == sym].sort_values("ts")
        if len(e):
            cum[:, j] = np.concatenate([[0.0], np.cumsum(e["rate"].to_numpy() * 1e4)])[np.searchsorted(_ns(e["ts"]), _ns(index), "right")]
    return Costs(pd.DatetimeIndex(sp.index), (sp / 2 + piv(f"imp_{NOTIONAL}")).to_numpy(), piv(f"maker_adv_{MAKER_H}").to_numpy(),
                 piv(f"maker_fill_{MAKER_H}").to_numpy(), cum)


# ---- strategies ---------------------------------------------------------------------------------------
class Strategy:
    name = "?"
    hold = 48                    # bars a position is held
    uses_labels = False          # True: `fit` reads y, and the noise floor refits on every shuffle

    def params(self) -> dict:
        return {k: v for k, v in vars(self).items() if not k.startswith("_") and isinstance(v, (int, float, str, bool, tuple, list))}

    def fit(self, M: Market, y: pd.DataFrame, now: pd.Timestamp) -> None:
        """M is the market strictly before `now`; y[t, pair] is the move (bps) a position decided at t
        would have earned gross, only for labels that ended before `now`."""

    def decide(self, M: Market, a: pd.Timestamp, b: pd.Timestamp) -> pd.DataFrame:
        raise NotImplementedError


def decisions_from(side: pd.DataFrame, a: pd.Timestamp, b: pd.Timestamp, signal: pd.DataFrame | None = None, why: str = "") -> pd.DataFrame:
    """Decisions in [a, b) from a wide frame whose sign is the side and whose magnitude is the size (0 / NaN = none)."""
    s = side.loc[(side.index >= a) & (side.index < b)]
    v = np.nan_to_num(s.to_numpy(dtype=float))
    ii, jj = np.nonzero(v)
    sig = signal.reindex(index=s.index, columns=s.columns).to_numpy()[ii, jj] if signal is not None else np.full(len(ii), np.nan)
    return pd.DataFrame({"t": s.index[ii], "symbol": np.asarray(s.columns, dtype=str)[jj], "side": np.sign(v[ii, jj]).astype(int),
                         "size": np.abs(v[ii, jj]), "signal": sig, "why": why})


def _hash01(t_ns: np.ndarray, j: np.ndarray, salt: int) -> np.ndarray:
    """A uniform in [0, 1) that depends only on (bar, pair, salt) — so a truncated market gives the same draw."""
    x = (t_ns // 300_000_000_000).astype(np.uint64) * np.uint64(0x9E3779B97F4A7C15) + j.astype(np.uint64) * np.uint64(0xBF58476D1CE4E5B9) + np.uint64(salt)
    for m in (0xBF58476D1CE4E5B9, 0x94D049BB133111EB):
        x = (x ^ (x >> np.uint64(30))) * np.uint64(m)
    return ((x ^ (x >> np.uint64(31))) >> np.uint64(11)).astype(float) / float(1 << 53)


class Coin(Strategy):
    """No skill: a tenth of the bars, a random side. Through the harness it must come out at minus the
    cost of a round trip — the check that the ledger, the cost series and the statistics agree."""
    name = "coin"

    def __init__(self, hold: int = 48, share: float = 0.10, salt: int = 0):
        self.hold, self.share, self.salt = int(hold), float(share), int(salt)

    def decide(self, M, a, b):
        t, j = np.meshgrid(_ns(M.index), np.arange(len(M.columns)), indexing="ij")
        u, v = _hash01(t, j, self.salt), _hash01(t, j, self.salt + 1)
        side = pd.DataFrame(np.where(u < self.share, np.where(v < 0.5, -1.0, 1.0), 0.0), index=M.index, columns=M.columns).where(M.close.notna(), 0.0)
        return decisions_from(side, a, b, why="coin")


STRATEGIES: dict[str, type[Strategy]] = {"coin": Coin}


def get_strategy(name: str, params: dict) -> Strategy:
    from . import rules                                       # imported here: rules.py itself imports this module
    return {**STRATEGIES, **rules.STRATEGIES}[name](**params)


# ---- walk-forward -------------------------------------------------------------------------------------
def labels(M: Market, hold: int, latency: int) -> pd.DataFrame:
    lr = np.log(M.close)
    return (lr.shift(-(latency + hold)) - lr.shift(-latency)) * 1e4


def _same(d1: pd.DataFrame, d2: pd.DataFrame) -> bool:
    k = ["t", "symbol", "side", "size"]
    a, b = (d[k].sort_values(["t", "symbol"]).reset_index(drop=True) for d in (d1, d2))
    return len(a) == len(b) and bool((a[["t", "symbol", "side"]] == b[["t", "symbol", "side"]]).all().all()) and np.allclose(a["size"], b["size"], rtol=1e-9)


def causal_check(strategy: Strategy, M: Market, a: pd.Timestamp, b: pd.Timestamp) -> None:
    """Decisions up to the middle of [a, b) must not change when the market after it does not exist."""
    tm = a + (b - a) / 2
    full, cut = strategy.decide(M.until(b), a, b), strategy.decide(M.until(tm + BAR), a, b)
    if not _same(full[full["t"] <= tm], cut[cut["t"] <= tm]):
        raise AssertionError(f"{strategy.name}: decisions before {tm} change when the market after {tm} is removed — the rule reads its future")


def blocks(fold: str, last: pd.Timestamp, refit_days: int) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    a, b = folds.bounds(fold)
    b = min(b, last + BAR)
    step = pd.Timedelta(days=refit_days)
    return [(x, min(x + step, b)) for x in pd.date_range(a, b, freq=step, inclusive="left")]


def walk(strategy: Strategy, M: Market, fold_names, y: pd.DataFrame, latency: int = LATENCY, refit_days: int = REFIT_DAYS, check: bool = True) -> pd.DataFrame:
    out = []
    for f in fold_names:
        for n, (ba, bb) in enumerate(blocks(f, M.index[-1], refit_days)):
            cut = max(M.index.searchsorted(ba) - (latency + strategy.hold), 0)      # the last label handed over ended before ba
            strategy.fit(M.until(ba), y.iloc[:cut], ba)
            d = strategy.decide(M.until(bb), ba, bb)
            if check and n == 0:
                causal_check(strategy, M, ba, bb)
            out.append(d[(d["t"] >= ba) & (d["t"] < bb)].assign(hold=strategy.hold, fold=f, block=n))
    dec = pd.concat(out, ignore_index=True).sort_values(["t", "symbol"], kind="mergesort").reset_index(drop=True)
    return accept(dec, M.index)


def accept(dec: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """The book rule: one open position per pair. A position decided at row p is open until row p + hold
    (both legs are shifted by the same latency), so the next decision in that pair is taken from there."""
    pos, busy, acc = index.get_indexer(dec["t"]), {}, np.ones(len(dec), dtype=bool)
    for n, (p, s, h) in enumerate(zip(pos, dec["symbol"], dec["hold"])):
        if p < busy.get(s, -1):
            acc[n] = False
        else:
            busy[s] = p + h
    return dec.assign(accepted=acc, skip=np.where(acc, "", "position_open"))


# ---- the ledger's second half: fills --------------------------------------------------------------------
def _ahead(x: pd.DataFrame, w: int, how: str) -> np.ndarray:
    """The min / max of x over the w bars AFTER each row."""
    r = x[::-1].rolling(w, min_periods=1)
    return (r.min() if how == "min" else r.max())[::-1].shift(-1).to_numpy()


def price(dec: pd.DataFrame, M: Market, C: Costs, exec_: str, taker_bps: float, maker_bps: float, latency: int = LATENCY,
          src: np.ndarray | None = None) -> pd.DataFrame:
    """Fills for the accepted decisions. `src` (a row indexer from `_shuffle_days`) takes the PRICE PATH
    from another day — the noise floor; the times, the cost series and the funding stay the real ones."""
    d = dec[dec["accepted"]]
    idx, n = M.index, len(M.index)
    i, j = idx.get_indexer(d["t"]), M.columns.get_indexer(d["symbol"])
    h, s = d["hold"].to_numpy(), d["side"].to_numpy(dtype=float)
    px = M.close.to_numpy()
    w = MAKER_WAIT if exec_ == "maker" else 0
    i0 = i if src is None else src[i]
    ok = (i0 >= 0) & (i0 + latency + h + w < n) & (i + latency + h + w < n)
    rows = {"e": (np.where(ok, i0 + latency, 0), np.where(ok, i + latency, 0)), "x": (np.where(ok, i0 + latency + h, 0), np.where(ok, i + latency + h, 0))}
    if exec_ == "maker":
        below, above = _ahead(M.low, w, "min"), _ahead(M.high, w, "max")
    legs = {}
    for leg, (g, r) in rows.items():                                    # g: the row the price path is read at; r: the real row (costs, funding)
        dpos = C.days.get_indexer(idx[r].floor("D"))
        pick = lambda a: np.where(dpos >= 0, a[np.maximum(dpos, 0), j], np.nan)                  # noqa: E731
        other_t, p0 = pick(C.taker_leg), px[g, j]
        if exec_ == "taker":
            legs[leg] = (p0, np.full(len(d), taker_bps), other_t, np.zeros(len(d)))
        elif exec_ == "maker":
            buying = (s > 0) == (leg == "e")
            filled = np.where(buying, below[g, j] < p0, above[g, j] > p0)
            legs[leg] = (np.where(filled, p0, px[g + w, j]), np.where(filled, maker_bps, taker_bps), np.where(filled, 0.0, other_t), filled.astype(float))
        else:
            p = pick(C.maker_fill)
            legs[leg] = (p0, p * maker_bps + (1 - p) * taker_bps, p * -pick(C.maker_adv) + (1 - p) * other_t, p)
    pe, pxx = legs["e"][0], legs["x"][0]
    fee, other, p_fill = (legs["e"][k] + legs["x"][k] for k in (1, 2, 3))
    gross = np.where(ok, s * np.log(pxx / pe) * 1e4, np.nan)
    re_, rx = rows["e"][1], rows["x"][1]
    fund = -s * (C.fundcum[rx, j] - C.fundcum[re_, j])
    out = pd.DataFrame({"id": d.index, "t": d["t"].array, "symbol": d["symbol"].to_numpy(), "fold": d["fold"].to_numpy(), "side": s.astype(int),
                        "size": d["size"].to_numpy(), "exec": exec_, "entry_t": idx[re_], "exit_t": idx[rx], "entry_px": pe, "exit_px": pxx,
                        "gross_bps": gross, "fee_bps": fee, "other_cost_bps": other, "p_fill": p_fill / 2, "funding_bps": fund})
    out["net_bps"] = out["gross_bps"] - out["fee_bps"] - out["other_cost_bps"] + out["funding_bps"]
    return out


# ---- statistics -----------------------------------------------------------------------------------------
def scored_days(fold_names, last: pd.Timestamp) -> pd.DatetimeIndex:
    parts = [pd.date_range(a.floor("D"), min(b, last + BAR) - pd.Timedelta(1, "ns"), freq="D") for a, b in (folds.bounds(f) for f in fold_names)]
    return parts[0].append(parts[1:]) if len(parts) > 1 else parts[0]


def trade_stats(x: np.ndarray, w: np.ndarray, day: pd.DatetimeIndex, days: pd.DatetimeIndex, lags: int) -> dict:
    """Mean of x per unit of w with a day-clustered interval: the ratio estimator Σ w·x / Σ w over days
    (days without a trade count as zeros), its linearised residual per day, HAC over days."""
    ok = ~np.isnan(x) & ~np.isnan(w)
    x, w, pos = x[ok], w[ok], days.get_indexer(pd.DatetimeIndex(day)[ok])
    if not len(x) or (pos < 0).any():
        return {"n": int(len(x)), "mean": np.nan, "se": np.nan, "lo": np.nan, "hi": np.nan, "mde": np.nan, "days": len(days)}
    S, N = np.bincount(pos, w * x, len(days)), np.bincount(pos, w, len(days))
    m = S.sum() / N.sum()
    _, se_e, _ = hac(S - m * N, lags)
    se = se_e / N.mean()
    return {"n": int(len(x)), "mean": float(m), "se": float(se), "lo": float(m - 1.96 * se), "hi": float(m + 1.96 * se), "mde": float(MDE_K * se), "days": len(days)}


def summarize(fills: pd.DataFrame, days: pd.DatetimeIndex, hold: int) -> dict:
    f = fills.dropna(subset=["net_bps"])
    day, w, lags = pd.DatetimeIndex(f["t"]).floor("D"), f["size"].to_numpy(), day_lags(hold)
    r = {k: trade_stats(f[f"{k}_bps"].to_numpy(), w, day, days, lags) for k in ("net", "gross")}
    wm = lambda c: float(np.average(f[c], weights=w)) if len(f) else np.nan                       # noqa: E731
    return {"trades": len(f), "unpriced": int(len(fills) - len(f)), "days": len(days), "trades_per_day": len(f) / max(len(days), 1),
            "hit": float((f["gross_bps"] > 0).mean()) if len(f) else np.nan, "gross": r["gross"]["mean"], "fee": wm("fee_bps"),
            "other_cost": wm("other_cost_bps"), "funding": wm("funding_bps"), "p_fill": wm("p_fill"), **{f"net_{k}": v for k, v in r["net"].items() if k != "n"},
            "net": r["net"]["mean"]}


def open_positions(dec: pd.DataFrame, index: pd.DatetimeIndex, latency: int) -> tuple[int, float]:
    d = dec[dec["accepted"]]
    p = index.get_indexer(d["t"]) + latency
    ev = np.zeros(len(index) + 1)
    np.add.at(ev, np.minimum(p, len(index)), 1)
    np.add.at(ev, np.minimum(p + d["hold"].to_numpy(), len(index)), -1)
    o = np.cumsum(ev)
    return int(o.max()), float(d["hold"].sum() / max(len(index), 1))


# ---- the run ----------------------------------------------------------------------------------------------
def _guard(fold_names, registration: str | None) -> list[str]:
    conf = [f for f in fold_names if f in folds.CONFIRMATION]
    if not conf:
        return conf
    if not registration or not re.fullmatch(r"R\d+", registration):
        raise SystemExit(f"{conf} are confirmation folds: they are read only by a registered contrast (--registration R<n>, PLAN §3/§8)")
    if not PLAN.exists() or not re.search(rf"^### {registration} ", PLAN.read_text(), flags=re.M):
        raise SystemExit(f"no '### {registration} ' block in {PLAN}: write the registration before the read")
    if READS.exists():
        r = pd.read_csv(READS)
        again = sorted(set(r.loc[r["registration"] == registration, "fold"]) & set(conf))
        if again:
            raise SystemExit(f"{registration} has already read {again} ({READS}): a fold is read once per question")
    return conf


def run(strategy: Strategy, symbols: list[str], fold_names=folds.EXPLORATION, execs=EXECS, draws: int = 200, taker_bps: float = 5.0, maker_bps: float = 2.0,
        latency: int = LATENCY, refit_days: int = REFIT_DAYS, registration: str | None = None, name: str | None = None, seed: int = 0) -> dict:
    fold_names = sorted(fold_names)
    conf = _guard(fold_names, registration)
    end = folds.bounds(fold_names[-1])[1]
    M = market(symbols, end)
    C = load_costs(M.index, M.columns, end)
    y = labels(M, strategy.hold, latency)
    print(f"{strategy.name}: walk-forward over {'+'.join(fold_names)}, {len(M.index):,} bars × {len(M.columns)} pairs…", flush=True)
    dec = walk(strategy, M, fold_names, y, latency, refit_days)
    days = scored_days(fold_names, M.index[-1])
    fills = {e: price(dec, M, C, e, taker_bps, maker_bps, latency) for e in execs}
    rows = []
    for e, f in fills.items():
        rows.append({"exec": e, "scope": "all", **summarize(f, days, strategy.hold)})
        rows += [{"exec": e, "scope": fo, **summarize(f[f["fold"] == fo], scored_days([fo], M.index[-1]), strategy.hold)} for fo in fold_names]
        rows += [{"exec": e, "scope": s, **summarize(f[f["symbol"] == s], days, strategy.hold)} for s in M.columns]
    res = pd.DataFrame(rows)

    # noise floor
    scored = np.zeros(len(M.index))
    t = pd.Series(M.index, index=M.index)
    for f in fold_names:
        scored += folds.mask(t, f).to_numpy()
    nul = []
    for draw in range(1, draws + 1):
        src = ceiling._shuffle_days(M.index, scored, np.random.default_rng([seed, draw]))
        d = walk(strategy, M, fold_names, pd.DataFrame(y.to_numpy()[src], index=y.index, columns=y.columns), latency, refit_days, check=False) if strategy.uses_labels else dec
        for e in execs:
            f = price(d, M, C, e, taker_bps, maker_bps, latency, src=src).dropna(subset=["net_bps"])
            nul.append({"draw": draw, "exec": e, "trades": len(f), "net": float(np.average(f["net_bps"], weights=f["size"])) if len(f) else np.nan})
        if draw % 20 == 0:
            print(f"noise floor: {draw}/{draws}", flush=True)
    nul = pd.DataFrame(nul, columns=["draw", "exec", "trades", "net"])
    floor = []
    for e in execs:
        real, x = float(res.loc[(res["exec"] == e) & (res["scope"] == "all"), "net"].iloc[0]), nul.loc[nul["exec"] == e, "net"].dropna()
        floor.append({"exec": e, "draws": len(x), "net": real, "null_mean": x.mean(), "null_sd": x.std(), "null_p95": x.quantile(0.95) if len(x) else np.nan,
                      "p": (1 + int((x >= real).sum())) / (len(x) + 1) if len(x) else np.nan})
    floor = pd.DataFrame(floor)

    out = OUT / (name or strategy.name)
    out.mkdir(parents=True, exist_ok=True)
    dec.to_parquet(out / "decisions.parquet", index=False)
    for e, f in fills.items():
        f.to_parquet(out / f"fills_{e}.parquet", index=False)
    res.to_parquet(out / "results.parquet", index=False)
    nul.to_parquet(out / "null.parquet", index=False)
    max_open, avg_open = open_positions(dec, M.index, latency)
    meta = {"strategy": strategy.name, "params": strategy.params(), "folds": fold_names, "registration": registration, "taker_bps": taker_bps,
            "maker_bps": maker_bps, "latency_bars": latency, "refit_days": refit_days, "draws": draws, "seed": seed, "notional": NOTIONAL,
            "pairs": list(M.columns), "decisions": len(dec), "accepted": int(dec["accepted"].sum()), "max_open": max_open, "avg_open": avg_open,
            "generated": f"{pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC"}
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
    (out / "report.md").write_text(report(meta, res, floor))
    if conf:                                                   # only once the number exists
        READS.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"read_at": meta["generated"], "registration": registration, "fold": conf, "strategy": strategy.name,
                      "params": json.dumps(meta["params"])}).to_csv(READS, mode="a", header=not READS.exists(), index=False)
    return {"dir": out, "meta": meta, "results": res, "floor": floor, "decisions": dec, "fills": fills, "null": nul}


def report(meta: dict, res: pd.DataFrame, floor: pd.DataFrame) -> str:
    md = [f"# Backtest — `{meta['strategy']}` (`ft2 backtest`)\n", f"generated {meta['generated']}\n",
          f"\nparams {meta['params']} · folds {'+'.join(meta['folds'])}" + (f" · **registration {meta['registration']}**" if meta["registration"] else " (exploration)")
          + f" · fees {meta['taker_bps']} taker / {meta['maker_bps']} maker bps per side · executed {meta['latency_bars']} bar(s) after the decision"
          f" · blocks of {meta['refit_days']} days · {meta['decisions']:,} decisions, {meta['accepted']:,} taken (one position per pair)"
          f" · at most {meta['max_open']} positions open at once, {meta['avg_open']:.2f} on average\n",
          "\nWords: a basis point (bps) is 0.01 %; *gross* is the move earned before costs, *net* after fees, spread, impact and funding; "
          f"one *unit of notional* is {meta['notional']:,} USDT, so 1 bps net = {meta['notional'] / 1e4:.0f} USDT per trade. *taker* crosses the spread on both legs; "
          f"*maker* rests a limit order at the bar's close for {MAKER_WAIT * 5} minutes on each leg, is filled only if a later bar trades through it, and "
          "otherwise crosses as a taker at the price by then (so `other_cost` is what the unfilled legs paid and the missed move is inside gross); "
          "*maker_ev* is P1's day-average version, blind to which orders fill — a reference, optimistic for a rule that buys what is falling. "
          "The interval is 95 %, clustered by day; "
          "*MDE* is the smallest true mean this sample could tell from zero (80 % power). The *noise floor* is the same pipeline on labels whose days were "
          "shuffled; p is the share of shuffles that did at least as well.\n", "\n## Bottom line\n"]
    for _, r in res[res["scope"] == "all"].iterrows():
        fl = floor[floor["exec"] == r["exec"]].iloc[0]
        usd, cap = r["net"] * meta["notional"] / 1e4, max(meta["max_open"], 1) * meta["notional"]
        verdict = ("profitable outside the noise" if r["net_lo"] > 0 and fl["p"] <= 0.05 else "loses money outside the noise" if r["net_hi"] < 0
                   else "not distinguishable from zero on this sample")
        md.append(f"- **{r['exec']}: {verdict}.** {r['trades']:,} trades over {r['days']} days ({r['trades_per_day']:.1f} a day), right on {r['hit']:.1%}. "
                  f"Gross {r['gross']:+.2f} bps, fees {r['fee']:.2f}, spread/impact/adverse {r['other_cost']:.2f}, funding {r['funding']:+.2f} → "
                  f"**net {r['net']:+.2f} bps per trade [{r['net_lo']:+.2f}, {r['net_hi']:+.2f}]**, MDE {r['net_mde']:.2f}; noise floor {fl['null_mean']:+.2f} ± {fl['null_sd']:.2f}, "
                  f"p = {fl['p']:.3f} ({int(fl['draws'])} shuffles). In money: {usd:+.2f} USDT per trade, {usd * r['trades_per_day']:+.1f} USDT a day on up to "
                  f"{cap:,} USDT deployed ({usd * r['trades_per_day'] * 365 / cap:+.1%} a year, no leverage, no compounding)."
                  + (f" {r['unpriced']} trades left out as unpriceable." if r["unpriced"] else "") + "\n")
    cols = ["exec", "scope", "trades", "trades_per_day", "hit", "gross", "fee", "other_cost", "funding", "net", "net_lo", "net_hi", "net_mde", "p_fill", "unpriced"]
    fo = res["scope"].isin(["all", *meta["folds"]])
    md += ["\n## Per fold (bps per unit of notional)\n", res.loc[fo, cols].round(3).to_markdown(index=False), "\n",
           "\n## Per pair\n", res.loc[~fo, cols].round(3).to_markdown(index=False), "\n", "\n## Noise floor\n", floor.round(4).to_markdown(index=False), "\n"]
    return "\n".join(md)
