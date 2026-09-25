"""P7 — the serving path: R14 (`ridgebook`, candle features) paper-traded live and UNCHANGED (PLAN §4 P7, §8 R17).
`ft2 serve <action>` on the always-on host `fluxtrader2-serve`; runbook docs/SERVE.md.

The model is `forecast.RidgeBook` with R14's registered arguments (PARAMS), fitted by the harness's own block rule and
scored by its own `_forecast`/`decide`. Nothing here forecasts, sizes or decides; this module only (a) keeps a candle
file, (b) says WHEN the harness's fit and decide are called and on WHICH prefix of the market, (c) writes down what
they said, and (d) proves that what it wrote is what the harness would have written.

  the clock      LATENCY 1, unchanged: a decision at the grid bar t (on the hour; the bar closed at t) is executed at
                 the close of the bar t + 5 min and exits at the close hold bars later, t + 5 min + 24 h.
                   HH:00 + 15 s  `decide`  fetch the closed bars, forecast on the grid bar HH:00, write the decisions
                   HH:05 + 15 s  `mark`    record the entry mark for HH:00's decisions (the close of the bar ending HH:05
                                           plus the live best bid/ask) and the exit mark for yesterday's HH:00 decisions
                 A decision is TAKEN only if it was written before its entry bar closed (`decided_at` < t + 5 min);
                 one written later (the host was down) is recorded with its forecast and skip = `late`, never traded.
  the refit      at the harness's block starts: `bt.blocks` for F3, F4, F5 (the embargoed fold start, then every
                 REFIT_DAYS), then every REFIT_DAYS after F5's last one, for ever (`block_starts`). Fitted on the market
                 strictly before the block start and on labels that ended before it — `RidgeBook.fit` as the harness
                 calls it, even when the refit is done late (the prefix is the block start's, not now's). Saved as
                 output/serve/models/model_<block start>.json (μ, σ, coefficients per group; σ_ref) so that every
                 decision can be re-scored from the model that made it, and so the scorer never fits.
  the market     data/serve/candles_seed.parquet (the collector's 5m candles of the twelve, `ft2 serve seed` on the work
                 VM, never rewritten) + data/serve/candles_live.parquet (closed bars appended from Binance futures REST
                 `/fapi/v1/klines`, the same klines the collector records). A stored bar is never overwritten; a fetched
                 bar that disagrees with a stored one is counted (health `overlap_mismatch`), not applied.
                 The scorer sees only the TAIL of the market (LOOKBACK + 12 bars up to t): every candle feature looks
                 back at most LOOKBACK bars, so the tail's value at t is the full panel's (tests/test_p5_forecast.py
                 proves it for a prefix; tests/test_p7_serve.py for the tail against the harness).
  the book rule  one position per pair, exactly `bt.accept`: a taken decision at t blocks the pair for decisions at
                 t' < t + hold bars; the open positions are read back from the ledger, not kept in memory.
  the ledger     output/serve/, append-only CSVs, decision and fill apart (Protocol, "Ledger"):
                   decisions.csv  one row per grid bar × pair, traded or not: t, symbol, group, f_bps, sigma_h, side,
                                  size, skip ('' taken | no_signal | position_open | late | no_bar), model_id, decided_at
                   marks.csv      one row per taken decision × leg: id, t, symbol, side, size, leg (entry|exit), mark_t,
                                  close, bid, ask, quote_at, funding_bps (exit leg: −side × Σ rates over the hold), marked_at
                   quotes.csv     best bid/ask of all twelve at every mark time, traded or not — the live spread
                   funding.csv    settled funding events (symbol, ts, rate) from `/fapi/v1/fundingRate`
                   health.json    what `ft2 serve status` prints; runs.log one line per run
                 No money number is computed here before R17's read (PLAN P7 "How it is read"): `ledger()` joins the
                 rows, it does not price them.
  identity       (1) `replay`: this module's hourly path (fresh scorer from the JSON model, tail market) run over F3+F4
                 on the seed must reproduce output/backtest/r16_ridgebook_1d_ho12_f34's forecast.parquet (f_bps, sigma_h
                 per cell) and its accepted decisions (t, symbol, side, size) exactly — or nothing goes live.
                 (2) `check`: the harness (block-wise `fit`/`decide`, then `bt.accept`) re-run over the ledger's whole
                 life on the appended candle file, diffed against decisions.csv; a difference not explained by a `late`
                 or `no_bar` row is a serving bug (look-ahead, a missed bar, a stale model) to fix before the ledger
                 continues. Also `bt.causal_check` on the current block. Monthly, from day one (fluxtrader1's X8b lesson).
"""
from __future__ import annotations

import dataclasses
import json
import sys
import time
import traceback
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from . import backtest as bt
from . import folds
from .__main__ import PAIRS
from .ceiling import BAR, START
from .forecast import LOOKBACK, RidgeBook

# R14 exactly (PLAN §8 R14, R16, R17). A change here is a new registration, not an edit.
PARAMS: dict = {"hold": 288, "min_bps": 15.0, "cap": 2.0, "groups": 4, "grid": 12, "min_pairs": 5, "holdout": True, "features": "candle"}
LATENCY = bt.LATENCY
REFIT_DAYS = bt.REFIT_DAYS
TAIL = LOOKBACK + 12                    # bars of market the scorer is handed: enough for every feature at the last bar
GRID = pd.Timedelta("1h")
OVERLAP_BARS = 12                       # bars re-fetched before the last stored one, to compare (never to overwrite)
BASE = "https://fapi.binance.com"
KLINE_LIMIT = 1500
FUNDING_LOOKBACK = pd.Timedelta("3D")   # funding events re-fetched on every mark run (idempotent)
F_TOL = 1e-6                            # identity checks: |Δ f_bps| and |Δ sigma_h| tolerated


@dataclasses.dataclass
class Config:
    """Where the files are and what is served. The default IS the registration; tests pass a synthetic one."""
    pairs: list = dataclasses.field(default_factory=lambda: list(PAIRS))
    params: dict = dataclasses.field(default_factory=lambda: dict(PARAMS))
    data: Path = Path("data/serve")
    out: Path = Path("output/serve")
    refit_folds: tuple = folds.CONFIRMATION   # the folds whose harness blocks the live refit schedule continues

    @property
    def hold(self) -> int:
        return int(self.params["hold"])

    seed = property(lambda c: c.data / "candles_seed.parquet")
    live = property(lambda c: c.data / "candles_live.parquet")
    models = property(lambda c: c.out / "models")
    decisions = property(lambda c: c.out / "decisions.csv")
    marks = property(lambda c: c.out / "marks.csv")
    quotes = property(lambda c: c.out / "quotes.csv")
    funding = property(lambda c: c.out / "funding.csv")
    health = property(lambda c: c.out / "health.json")
    state = property(lambda c: c.out / "state.json")
    log = property(lambda c: c.out / "runs.log")


# ---- Binance futures REST (public, no key) ---------------------------------------------------------------------------
def http_get(path: str, params: dict, retries: int = 3, timeout: float = 10.0):
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    err = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ft2-serve"}), timeout=timeout) as r:
                return json.loads(r.read())
        except Exception as e:                                  # noqa: BLE001 — retried, then raised with the cause
            err = e
            time.sleep(2.0 * (i + 1))
    raise RuntimeError(f"GET {path} {params} failed after {retries} tries: {err!r}")


def _ms(t: pd.Timestamp) -> int:
    return int(t.value // 1_000_000)


def klines(symbol: str, start: pd.Timestamp, now: pd.Timestamp, http=http_get) -> pd.DataFrame:
    """Closed 5m bars of `symbol` with open_time ≥ start (open_time + 5 min ≤ now), paged."""
    rows, t0 = [], _ms(start)
    while True:
        page = http("/fapi/v1/klines", {"symbol": symbol, "interval": "5m", "startTime": t0, "limit": KLINE_LIMIT})
        if not page:
            break
        rows += [k for k in page if int(k[0]) + 300_000 <= _ms(now)]
        if len(page) < KLINE_LIMIT or int(page[-1][0]) + 300_000 > _ms(now):
            break
        t0 = int(page[-1][0]) + 300_000
    if not rows:
        return pd.DataFrame(columns=["symbol", "open_time", "open", "high", "low", "close", "volume"])
    a = np.array([[float(k[i]) for i in (0, 1, 2, 3, 4, 5)] for k in rows])
    return pd.DataFrame({"symbol": symbol, "open_time": pd.to_datetime(a[:, 0].astype("int64"), unit="ms", utc=True),
                         "open": a[:, 1], "high": a[:, 2], "low": a[:, 3], "close": a[:, 4], "volume": a[:, 5]})


def book_ticker(pairs: list[str], http=http_get) -> pd.DataFrame:
    """Best bid/ask of every futures symbol in one call, kept for `pairs`."""
    q = http("/fapi/v1/ticker/bookTicker", {})
    d = pd.DataFrame(q)[["symbol", "bidPrice", "askPrice"]].rename(columns={"bidPrice": "bid", "askPrice": "ask"})
    d = d[d["symbol"].isin(pairs)].copy()
    d[["bid", "ask"]] = d[["bid", "ask"]].astype(float)
    return d.set_index("symbol").reindex(pairs).reset_index()


def funding_events(symbol: str, start: pd.Timestamp, http=http_get) -> pd.DataFrame:
    q = http("/fapi/v1/fundingRate", {"symbol": symbol, "startTime": _ms(start), "limit": 1000})
    if not q:
        return pd.DataFrame(columns=["symbol", "ts", "rate"])
    return pd.DataFrame({"symbol": symbol, "ts": pd.to_datetime([int(e["fundingTime"]) for e in q], unit="ms", utc=True).round("s"),
                         "rate": [float(e["fundingRate"]) for e in q]})


# ---- the candle file ----------------------------------------------------------------------------------------------------
CANDLE_COLS = ["symbol", "open_time", "open", "high", "low", "close", "volume"]


def seed(cfg: Config = Config(), src: Path = Path("data/candles_5m.parquet"), dst: Path | None = None) -> dict:
    """On the work VM: the collector's 5m candles of the pairs, from F0's start, → the seed file (never rewritten later)."""
    dst = dst or cfg.seed
    c = pd.read_parquet(src, columns=CANDLE_COLS)
    c["symbol"] = c["symbol"].astype(str)
    c = c[c["symbol"].isin(cfg.pairs) & (c["open_time"] + BAR >= START)]
    c = c.sort_values(["symbol", "open_time"], kind="mergesort").drop_duplicates(["symbol", "open_time"], keep="last").reset_index(drop=True)
    dst.parent.mkdir(parents=True, exist_ok=True)
    c.to_parquet(dst, index=False, row_group_size=50_000)
    per = c.groupby("symbol")["open_time"].agg(["min", "max", "size"])
    return {"file": str(dst), "rows": len(c), "pairs": len(per), "first": c["open_time"].min(), "last": c["open_time"].max(), "per_pair": per}


def _read(path: Path, since: pd.Timestamp | None) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=CANDLE_COLS)
    if since is None:
        return pd.read_parquet(path, columns=CANDLE_COLS)
    import pyarrow as pa
    import pyarrow.dataset as ds
    lo = pa.scalar(int(pd.Timestamp(since).tz_convert("UTC").value), type=pa.timestamp("ns", "UTC"))
    return ds.dataset(str(path)).to_table(columns=CANDLE_COLS, filter=ds.field("open_time") >= lo).to_pandas()


def load_candles(cfg: Config, since: pd.Timestamp | None = None) -> pd.DataFrame:
    """Seed + live, long; where both hold a bar the seed's is kept. `since` filters on open_time (row groups are pruned)."""
    parts = [d for d in (_read(cfg.seed, since), _read(cfg.live, since)) if len(d)]
    c = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=CANDLE_COLS)
    c["symbol"] = c["symbol"].astype(str)
    c["open_time"] = pd.to_datetime(c["open_time"], utc=True)
    return c.sort_values(["symbol", "open_time"], kind="mergesort").drop_duplicates(["symbol", "open_time"], keep="first").reset_index(drop=True)


def last_bars(cfg: Config) -> pd.Series:
    """Last stored open_time per pair (NaT if none)."""
    parts = []
    for p in (cfg.seed, cfg.live):
        if p.exists():
            parts.append(pd.read_parquet(p, columns=["symbol", "open_time"]))
    if not parts:
        return pd.Series(pd.NaT, index=cfg.pairs, dtype="datetime64[ns, UTC]")
    c = pd.concat(parts, ignore_index=True)
    c["symbol"] = c["symbol"].astype(str)
    return c.groupby("symbol")["open_time"].max().reindex(cfg.pairs)


def fetch(cfg: Config, now: pd.Timestamp, http=http_get) -> dict:
    """Append every closed bar after the last stored one, per pair; compare the OVERLAP_BARS re-fetched bars with the stored
    ones and count the differences (the stored bar always wins). Returns what happened, per pair."""
    last = last_bars(cfg)
    live = _read(cfg.live, None)
    new, report = [], {}
    for sym in cfg.pairs:
        t_last = last[sym]
        start = (t_last - OVERLAP_BARS * BAR) if pd.notna(t_last) else (START - BAR)
        try:
            k = klines(sym, start, now, http)
        except Exception as e:                                  # noqa: BLE001 — one pair failing must not stop the others
            report[sym] = {"new": 0, "mismatch": 0, "error": repr(e)}
            continue
        stored = load_candles(cfg, since=start)
        stored = stored[stored["symbol"] == sym]
        m = k.merge(stored, on=["symbol", "open_time"], how="inner", suffixes=("", "_stored"))
        mism = int(((m["close"] != m["close_stored"]) | (m["high"] != m["high_stored"]) | (m["low"] != m["low_stored"])).sum())
        fresh = k[~k["open_time"].isin(set(stored["open_time"]))]
        new.append(fresh)
        report[sym] = {"new": int(len(fresh)), "mismatch": mism, "last": (fresh["open_time"].max() if len(fresh) else t_last)}
    add = pd.concat([f for f in new if len(f)], ignore_index=True) if any(len(f) for f in new) else pd.DataFrame(columns=CANDLE_COLS)
    if len(add):
        live = pd.concat([d for d in (live, add) if len(d)], ignore_index=True)
        live["symbol"] = live["symbol"].astype(str)
        live["open_time"] = pd.to_datetime(live["open_time"], utc=True)
        live = live.sort_values(["symbol", "open_time"], kind="mergesort").drop_duplicates(["symbol", "open_time"], keep="first")
        cfg.live.parent.mkdir(parents=True, exist_ok=True)
        live.to_parquet(cfg.live, index=False)
    return report


def market(c: pd.DataFrame, pairs: list[str]) -> bt.Market:
    """`ceiling.panel` on the candle file: decision time t = open_time + 5 min, the full 5-minute range, the pairs as
    columns in their fixed order (all of them, present or not — the harness's twelve-column market)."""
    c = c.assign(t=c["open_time"] + BAR)
    c = c[c["t"] >= START]
    if c.empty:
        raise ValueError("no candles")
    idx = pd.date_range(c["t"].min(), c["t"].max(), freq="5min", name="t")
    P = {k: c.pivot(index="t", columns="symbol", values=k).reindex(index=idx, columns=pairs) for k in ("close", "high", "low", "volume")}
    return bt.Market(P["close"], P["high"], P["low"], P["volume"] * P["close"])


# ---- the refit schedule and the model file -----------------------------------------------------------------------------
def block_starts(until: pd.Timestamp, fold_names=folds.CONFIRMATION, refit_days: int = REFIT_DAYS) -> list[pd.Timestamp]:
    """The harness's block starts (`bt.blocks`) for the folds given, then every refit_days after the last, up to `until`."""
    step, out = pd.Timedelta(days=refit_days), []
    for f in fold_names:
        a, b = folds.bounds(f)
        out += list(pd.date_range(a, b, freq=step, inclusive="left"))
    while out[-1] + step <= until:
        out.append(out[-1] + step)
    return [t for t in out if t <= until]


def block_start(t: pd.Timestamp, cfg: Config) -> pd.Timestamp:
    """The block the grid bar t belongs to: the last scheduled refit at or before t."""
    s = block_starts(t, cfg.refit_folds)
    if not s:
        raise ValueError(f"{t} is before the first block ({folds.bounds(cfg.refit_folds[0])[0]})")
    return s[-1]


def ensure_chunked(s: RidgeBook, M: bt.Market, days: int = 60) -> None:
    """`RidgeBook._ensure` over the market in prefixes of `days`: the same cached features (they look back only, and the
    two-step test in tests/test_p5_forecast.py holds), at a fraction of the one-shot peak memory (the 2 GB host)."""
    ends = list(pd.date_range(M.index[0], M.index[-1], freq=f"{days}D")[1:]) + [M.index[-1] + BAR]
    for e in ends:
        s._ensure(M.until(e))


def fit(M: bt.Market, ba: pd.Timestamp, cfg: Config) -> RidgeBook:
    """The harness's block fit: the market strictly before ba, labels that ended before ba (`bt.walk`, line for line)."""
    s = RidgeBook(**cfg.params)
    Mb = M.until(ba)
    ensure_chunked(s, Mb)
    y = bt.labels(Mb, cfg.hold, LATENCY)
    cut = max(Mb.index.searchsorted(ba) - (LATENCY + cfg.hold), 0)
    s.fit(Mb, y.iloc[:cut], ba)
    return s


def model_id(ba: pd.Timestamp) -> str:
    return f"model_{ba:%Y-%m-%d}"


def save_model(s: RidgeBook, ba: pd.Timestamp, M: bt.Market, cfg: Config, path: Path | None = None) -> Path:
    path = path or cfg.models / f"{model_id(ba)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    Mb = M.until(ba)
    doc = {"model_id": model_id(ba), "block_start": ba.isoformat(), "fitted_at": pd.Timestamp.now("UTC").isoformat(),
           "data_end": Mb.index[-1].isoformat() if len(Mb.index) else None, "bars": int(len(Mb.index)), "params": cfg.params, "pairs": list(M.columns),
           "sigma_ref": None if np.isnan(s._sigma_ref) else float(s._sigma_ref),
           "groups": {str(g): None if m is None else {"mu": m[0].tolist(), "sd": m[1].tolist(), "coef": m[2].tolist()} for g, m in s._models.items()}}
    path.write_text(json.dumps(doc))
    return path


def load_model(path: Path, cfg: Config) -> RidgeBook:
    """A scorer that never fits: `RidgeBook` with the saved μ, σ, coefficients and σ_ref."""
    doc = json.loads(path.read_text())
    if doc["params"] != cfg.params or doc["pairs"] != list(cfg.pairs):
        raise ValueError(f"{path} was fitted with {doc['params']} on {doc['pairs']}, not the served {cfg.params} on {cfg.pairs}")
    s = RidgeBook(**cfg.params)
    s._models = {int(g): None if m is None else (np.array(m["mu"]), np.array(m["sd"]), np.array(m["coef"])) for g, m in doc["groups"].items()}
    s._sigma_ref = np.nan if doc["sigma_ref"] is None else float(doc["sigma_ref"])
    s._last_now = pd.Timestamp(doc["block_start"])
    return s


def model_for(ba: pd.Timestamp, M: bt.Market, cfg: Config) -> tuple[RidgeBook, Path, bool]:
    """The saved model of block ba, fitted and saved first if it does not exist yet. Returns (scorer, path, refitted)."""
    path = cfg.models / f"{model_id(ba)}.json"
    fitted = False
    if not path.exists():
        save_model(fit(M, ba, cfg), ba, M, cfg, path)
        fitted = True
    return load_model(path, cfg), path, fitted


# ---- the scorer ---------------------------------------------------------------------------------------------------------------
def tail(M: bt.Market, t: pd.Timestamp) -> bt.Market:
    """The market up to and including the bar t, TAIL bars deep."""
    n = M.index.searchsorted(t, side="right")
    if n == 0 or M.index[n - 1] != t:
        raise ValueError(f"{t} is not a bar of the market (last {M.index[-1] if len(M.index) else None})")
    lo = max(n - TAIL - 1, 0)
    return bt.Market(M.close.iloc[lo:n], M.high.iloc[lo:n], M.low.iloc[lo:n], M.dv.iloc[lo:n])


def forecast_at(s: RidgeBook, M: bt.Market, t: pd.Timestamp) -> pd.DataFrame:
    """R14's forecast and trade rows at the grid bar t, one row per pair: f_bps, sigma_h (NaN = no forecast), side and
    size (0 = the rule does not trade). `RidgeBook._forecast` for the cells and `RidgeBook.decide` for the trades — the
    registered code path, on the tail of the market."""
    Mt = tail(M, t)
    ts, f, sig_h, _ = s._forecast(Mt, t, t + BAR)
    if len(ts) != 1 or ts[0] != t:
        raise ValueError(f"{t} is not a grid bar")
    d = s.decide(Mt, t, t + BAR).set_index("symbol")
    out = pd.DataFrame({"t": t, "symbol": list(M.columns), "group": s._group(len(M.columns)), "f_bps": f[0], "sigma_h": sig_h[0], "side": 0, "size": 0.0}).set_index("symbol")
    out.loc[d.index, "side"] = d["side"].astype(int)
    out.loc[d.index, "size"] = d["size"]
    return out.reset_index()[["t", "symbol", "group", "f_bps", "sigma_h", "side", "size"]]


def grid_bars(a: pd.Timestamp, b: pd.Timestamp) -> pd.DatetimeIndex:
    """The grid bars t in [a, b): on the hour (`RidgeBook._grid` with grid = 12)."""
    return pd.date_range(a.ceil("h"), b - pd.Timedelta("1ns"), freq=GRID)


# ---- the ledger ---------------------------------------------------------------------------------------------------------------
DEC_COLS = ["id", "t", "symbol", "group", "f_bps", "sigma_h", "side", "size", "skip", "model_id", "decided_at"]
MARK_COLS = ["id", "t", "symbol", "side", "size", "leg", "mark_t", "close", "bid", "ask", "quote_at", "funding_bps", "marked_at"]


def _csv(path: Path, cols: list[str], times: tuple[str, ...]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=cols)
    d = pd.read_csv(path, dtype={"skip": str, "symbol": str, "id": str, "leg": str, "model_id": str}, keep_default_na=True)
    for c in times:
        d[c] = pd.to_datetime(d[c], utc=True)
    if "skip" in d:
        d["skip"] = d["skip"].fillna("")
    return d


def _append(path: Path, rows: pd.DataFrame) -> None:
    if rows.empty:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    rows.to_csv(path, mode="a", header=not path.exists(), index=False)


def read_decisions(cfg: Config) -> pd.DataFrame:
    return _csv(cfg.decisions, DEC_COLS, ("t", "decided_at"))


def read_marks(cfg: Config) -> pd.DataFrame:
    return _csv(cfg.marks, MARK_COLS, ("t", "mark_t", "quote_at", "marked_at"))


def read_funding(cfg: Config) -> pd.DataFrame:
    return _csv(cfg.funding, ["symbol", "ts", "rate"], ("ts",))


def _id(t: pd.Timestamp, symbol: str) -> str:
    return f"{t:%Y%m%dT%H%M}-{symbol}"


def busy_until(dec: pd.DataFrame, hold: int) -> dict[str, pd.Timestamp]:
    """Per pair, the first bar at which a new position may be taken: the last taken decision's t + hold bars (`bt.accept`)."""
    taken = dec[dec["skip"] == ""]
    if taken.empty:
        return {}
    return (taken.groupby("symbol")["t"].max() + hold * BAR).to_dict()


def decide_bar(s: RidgeBook, M: bt.Market, t: pd.Timestamp, busy: dict[str, pd.Timestamp], now: pd.Timestamp, mid: str, cfg: Config) -> pd.DataFrame:
    """The decision rows of the grid bar t, with the book rule and the lateness rule applied; `busy` is updated in place."""
    rows = forecast_at(s, M, t)
    gone = np.isnan(M.close.loc[t].to_numpy()) if t in M.index else np.ones(len(cfg.pairs), dtype=bool)
    skip = np.where(rows["side"] == 0, "no_signal", "")
    skip = np.where(gone & (skip == "no_signal"), "no_bar", skip)
    late = now >= t + BAR
    for i, sym in enumerate(rows["symbol"]):
        if skip[i] == "" and sym in busy and t < busy[sym]:
            skip[i] = "position_open"
        elif skip[i] == "" and late:
            skip[i] = "late"
        elif skip[i] == "":
            busy[sym] = t + cfg.hold * BAR
    rows["skip"], rows["model_id"], rows["decided_at"] = skip, mid, now
    rows.insert(0, "id", [_id(t, sym) for sym in rows["symbol"]])
    return rows[DEC_COLS]


# ---- state, health, log -----------------------------------------------------------------------------------------------------
def read_state(cfg: Config) -> dict:
    return json.loads(cfg.state.read_text()) if cfg.state.exists() else {}


def write_state(cfg: Config, **kw) -> dict:
    st = read_state(cfg) | kw
    cfg.state.parent.mkdir(parents=True, exist_ok=True)
    cfg.state.write_text(json.dumps(st, indent=1, default=str))
    return st


def _log(cfg: Config, line: str) -> None:
    cfg.log.parent.mkdir(parents=True, exist_ok=True)
    with cfg.log.open("a") as f:
        f.write(f"{pd.Timestamp.now('UTC'):%Y-%m-%dT%H:%M:%SZ} {line}\n")


def health(cfg: Config, now: pd.Timestamp, **extra) -> dict:
    """Everything `status` needs, from the files alone (so it is right even when a run crashed)."""
    st = read_state(cfg)
    dec, marks = read_decisions(cfg), read_marks(cfg)
    last = last_bars(cfg)
    taken = dec[dec["skip"] == ""]
    entries = set(marks.loc[marks["leg"] == "entry", "id"]) if len(marks) else set()
    exits = set(marks.loc[marks["leg"] == "exit", "id"]) if len(marks) else set()
    open_ = taken[~taken["id"].isin(exits)]
    models = sorted(cfg.models.glob("model_*.json")) if cfg.models.exists() else []
    cur = json.loads(models[-1].read_text()) if models else None
    prev = cfg.health.exists() and json.loads(cfg.health.read_text()) or {}
    since = pd.Timestamp(st["ledger_start"]) if "ledger_start" in st else None
    missing_24h = 0
    if pd.notna(last).any():                                   # the 288 bars that should be closed by now, per pair
        hi = now.floor("5min") - BAR
        lo = hi - 287 * BAR
        c = load_candles(cfg, since=lo)
        c = c[(c["open_time"] >= lo) & (c["open_time"] <= hi)]
        missing_24h = int(sum(288 - int((c["symbol"] == p).sum()) for p in cfg.pairs))
    h = {"updated": now.isoformat(), "ledger_start": st.get("ledger_start"), "last_decide": prev.get("last_decide"), "last_mark": prev.get("last_mark"),
         "last_bar": {p: (None if pd.isna(v) else (v + BAR).isoformat()) for p, v in last.items()}, "bars_missing_24h": missing_24h,
         "decisions": int(len(dec)), "grid_bars_decided": int(dec["t"].nunique()) if len(dec) else 0, "last_decision_t": dec["t"].max().isoformat() if len(dec) else None,
         "taken": int(len(taken)), "late": int((dec["skip"] == "late").sum()), "no_bar": int((dec["skip"] == "no_bar").sum()),
         "open_positions": int(len(open_)), "entries_marked": int(len(entries)), "exits_marked": int(len(exits)),
         "model_id": cur["model_id"] if cur else None, "model_block_start": cur["block_start"] if cur else None,
         "model_age_days": None if not cur else float((now - pd.Timestamp(cur["block_start"])).total_seconds() / 86400),
         "next_refit": (block_start(now.floor("h"), cfg) + pd.Timedelta(days=REFIT_DAYS)).isoformat() if since else None,
         "overlap_mismatch": prev.get("overlap_mismatch", 0), "last_check": prev.get("last_check"), "last_error": prev.get("last_error")}
    h.update(extra)
    cfg.health.parent.mkdir(parents=True, exist_ok=True)
    cfg.health.write_text(json.dumps(h, indent=1, default=str))
    return h


def status(cfg: Config = Config()) -> str:
    if not cfg.health.exists():
        return "no health.json yet — not started"
    h = json.loads(cfg.health.read_text())
    lb = [v for v in h["last_bar"].values() if v]
    line = (f"{h['updated'][:16]}Z  decide {str(h['last_decide'])[:16]}  mark {str(h['last_mark'])[:16]}  last bar {min(lb)[:16] if lb else None}  "
            f"missing24h {h['bars_missing_24h']}  decisions {h['decisions']} taken {h['taken']} late {h['late']} open {h['open_positions']}  "
            f"marks {h['entries_marked']}/{h['exits_marked']}  model {h['model_id']} ({h['model_age_days'] and round(h['model_age_days'], 1)} d)  "
            f"check {h['last_check'] and h['last_check'].get('pass')}  err {h['last_error']}")
    return line + "\n" + json.dumps(h, indent=1, default=str)


# ---- the runs -----------------------------------------------------------------------------------------------------------------
def _guarded(cfg: Config, name: str, fn, now: pd.Timestamp):
    t0 = time.time()
    try:
        r = fn()
        _log(cfg, f"{name} ok {time.time() - t0:.1f}s {r}")
        return r
    except Exception as e:                                       # noqa: BLE001 — recorded in health and the log, then re-raised for systemd
        _log(cfg, f"{name} FAILED {time.time() - t0:.1f}s {e!r}")
        try:
            health(cfg, now, last_error=f"{name} {pd.Timestamp.now('UTC'):%Y-%m-%dT%H:%M}Z: {e!r}")
        except Exception:                                        # noqa: BLE001
            traceback.print_exc()
        raise


def start(cfg: Config = Config(), now: pd.Timestamp | None = None, http=http_get) -> dict:
    """Go live: the ledger starts at the next grid bar. Refuses unless the candle file is caught up."""
    now = now or pd.Timestamp.now("UTC")
    rep = fetch(cfg, now, http)
    last = last_bars(cfg)
    stale = [p for p in cfg.pairs if pd.isna(last[p]) or last[p] + BAR < now - pd.Timedelta("15min")]
    if stale:
        raise SystemExit(f"candles not caught up for {stale}: {rep}")
    first = now.floor("h") if now < now.floor("h") + BAR else now.ceil("h")      # this hour's bar if its entry bar is still open, else the next
    st = write_state(cfg, ledger_start=first.isoformat(), started_at=now.isoformat(), params=cfg.params, pairs=cfg.pairs)
    health(cfg, now)
    _log(cfg, f"start ledger_start={st['ledger_start']}")
    return st


def run_decide(cfg: Config = Config(), now: pd.Timestamp | None = None, http=http_get) -> dict:
    now = now or pd.Timestamp.now("UTC")

    def go():
        rep = fetch(cfg, now, http)
        mism = int(sum(r.get("mismatch", 0) for r in rep.values()))
        st = read_state(cfg)
        if "ledger_start" not in st:
            health(cfg, now, last_decide=now.isoformat(), overlap_mismatch=mism, fetch=rep)
            return {"pending": 0, "note": "not started"}
        dec = read_decisions(cfg)
        last_t = dec["t"].max() if len(dec) else pd.Timestamp(st["ledger_start"]) - GRID
        last_bar = last_bars(cfg).max() + BAR
        pending = grid_bars(last_t + BAR, last_bar + BAR)
        pending = pending[pending >= pd.Timestamp(st["ledger_start"])]
        out, busy, refits, M, cache = [], busy_until(dec, cfg.hold), 0, None, {}
        if len(pending):
            need_full = any(not (cfg.models / f"{model_id(block_start(t, cfg))}.json").exists() for t in pending)
            M = market(load_candles(cfg, None if need_full else pending[0] - (TAIL + 2) * BAR), cfg.pairs)
        for t in pending:
            ba = block_start(t, cfg)
            if ba not in cache:
                s, path, fitted = model_for(ba, M, cfg)
                cache[ba] = (s, path.stem)
                refits += fitted
            s, mid = cache[ba]
            rows = decide_bar(s, M, t, busy, now, mid, cfg)
            _append(cfg.decisions, rows)
            out.append(rows)
        n_taken = int(sum((r["skip"] == "").sum() for r in out)) if out else 0
        n_late = int(sum((r["skip"] == "late").sum() for r in out)) if out else 0
        health(cfg, now, last_decide=now.isoformat(), overlap_mismatch=mism, fetch=rep, last_error=None)
        return {"pending": len(pending), "taken": n_taken, "late": n_late, "refits": refits, "mismatch": mism}

    return _guarded(cfg, "decide", go, now)


def funding_bps(f: pd.DataFrame, symbol: str, side: int, entry_t: pd.Timestamp, exit_t: pd.Timestamp) -> float:
    """−side × Σ (rate × 1e4) over the events with entry_t < ts ≤ exit_t (`bt.price`: fundcum[exit] − fundcum[entry])."""
    e = f[(f["symbol"] == symbol) & (f["ts"] > entry_t) & (f["ts"] <= exit_t)]
    return float(-side * e["rate"].sum() * 1e4)


def run_mark(cfg: Config = Config(), now: pd.Timestamp | None = None, http=http_get) -> dict:
    now = now or pd.Timestamp.now("UTC")

    def go():
        rep = fetch(cfg, now, http)
        mism = int(sum(r.get("mismatch", 0) for r in rep.values()))
        q = book_ticker(cfg.pairs, http)
        mark_t = now.floor("5min")
        q = q.assign(mark_t=mark_t, quote_at=now)[["mark_t", "symbol", "bid", "ask", "quote_at"]]
        _append(cfg.quotes, q)
        fund = read_funding(cfg)
        new = []
        for sym in cfg.pairs:
            since = (fund.loc[fund["symbol"] == sym, "ts"].max() if len(fund) else pd.NaT)
            since = (since - pd.Timedelta("1h")) if pd.notna(since) else now - FUNDING_LOOKBACK
            try:
                e = funding_events(sym, since, http)
            except Exception as ex:                             # noqa: BLE001
                rep[sym] = rep.get(sym, {}) | {"funding_error": repr(ex)}
                continue
            if len(e) and len(fund):
                e = e[~e.set_index(["symbol", "ts"]).index.isin(fund.set_index(["symbol", "ts"]).index)]
            new.append(e)
        if any(len(e) for e in new):
            add = pd.concat([e for e in new if len(e)], ignore_index=True)
            _append(cfg.funding, add)
            fund = pd.concat([d for d in (fund, add) if len(d)], ignore_index=True)
        dec, marks = read_decisions(cfg), read_marks(cfg)
        taken = dec[dec["skip"] == ""]
        done = {leg: set(marks.loc[marks["leg"] == leg, "id"]) for leg in ("entry", "exit")} if len(marks) else {"entry": set(), "exit": set()}
        pend = {"entry": taken[~taken["id"].isin(done["entry"])].assign(mark_t=lambda d: d["t"] + LATENCY * BAR),
                "exit": taken[taken["id"].isin(done["entry"]) & ~taken["id"].isin(done["exit"])].assign(mark_t=lambda d: d["t"] + (LATENCY + cfg.hold) * BAR)}
        last = last_bars(cfg) + BAR
        rows = []
        if any(len(p) for p in pend.values()):
            lo = min(p["mark_t"].min() for p in pend.values() if len(p))
            c = load_candles(cfg, since=lo - 2 * BAR)
            close = c.assign(t=c["open_time"] + BAR).pivot(index="t", columns="symbol", values="close") if len(c) else pd.DataFrame()
            qi = q.set_index("symbol")
            for leg, p in pend.items():
                for _, r in p.iterrows():
                    if r["mark_t"] > last[r["symbol"]]:
                        continue                                # the bar is not in yet; the next run marks it
                    px = close.at[r["mark_t"], r["symbol"]] if (r["mark_t"] in close.index and r["symbol"] in close.columns) else np.nan
                    fb = funding_bps(fund, r["symbol"], int(r["side"]), r["t"] + LATENCY * BAR, r["mark_t"]) if leg == "exit" else np.nan
                    rows.append({"id": r["id"], "t": r["t"], "symbol": r["symbol"], "side": int(r["side"]), "size": r["size"], "leg": leg, "mark_t": r["mark_t"],
                                 "close": px, "bid": qi.at[r["symbol"], "bid"], "ask": qi.at[r["symbol"], "ask"], "quote_at": now, "funding_bps": fb, "marked_at": now})
        _append(cfg.marks, pd.DataFrame(rows, columns=MARK_COLS))
        health(cfg, now, last_mark=now.isoformat(), overlap_mismatch=mism, fetch=rep, last_error=None)
        return {"entries": sum(r["leg"] == "entry" for r in rows), "exits": sum(r["leg"] == "exit" for r in rows), "quotes": int(len(q)), "mismatch": mism}

    return _guarded(cfg, "mark", go, now)


def ledger(cfg: Config = Config()) -> pd.DataFrame:
    """One row per taken decision with its entry and exit marks joined (no prices are turned into money here)."""
    dec, marks = read_decisions(cfg), read_marks(cfg)
    d = dec[dec["skip"] == ""].drop(columns=["skip"])
    for leg in ("entry", "exit"):
        m = marks[marks["leg"] == leg].set_index("id")[["mark_t", "close", "bid", "ask", "quote_at", "funding_bps", "marked_at"]]
        m = m.rename(columns={c: f"{leg}_{c.replace('mark_t', 't')}" for c in m.columns})
        if leg == "entry":
            m = m.drop(columns=["entry_funding_bps"])
        d = d.merge(m, left_on="id", right_index=True, how="left")
    return d.reset_index(drop=True)


# ---- identity check 1: the hourly path over F3+F4 against R16's files --------------------------------------------------------------
def replay(cfg: Config, fold_names=("F3", "F4"), against: Path | None = Path("output/backtest/r16_ridgebook_1d_ho12_f34"), out: Path | None = None,
           models: Path | None = None, verbose: bool = True) -> dict:
    """Run the live path — refit at the harness's block starts, model saved to and loaded from JSON, one grid bar at a time
    on the tail of the market, the book rule from the ledger — over the folds' blocks, and diff it against a harness run's
    forecast.parquet and decisions.parquet. Returns the ledger it built and the diff; `pass` must be True before go-live."""
    fold_names = folds.order(fold_names)
    M = market(load_candles(cfg), cfg.pairs)
    models = models or (cfg.out / "replay" / "models")
    rows, busy, n_bars = [], {}, 0
    t_start = time.time()
    for f in fold_names:
        for ba, bb in bt.blocks(f, M.index[-1], REFIT_DAYS):
            path = save_model(fit(M, ba, cfg), ba, M, cfg, models / f"{model_id(ba)}.json")
            s = load_model(path, cfg)
            for t in grid_bars(ba, bb):
                rows.append(decide_bar(s, M, t, busy, t + pd.Timedelta("15s"), path.stem, cfg))
                n_bars += 1
            if verbose:
                print(f"replay: block {ba:%Y-%m-%d} → {bb:%Y-%m-%d} done, {n_bars} bars, {time.time() - t_start:.0f}s", flush=True)
    led = pd.concat(rows, ignore_index=True)
    res = {"bars": n_bars, "rows": len(led), "taken": int((led["skip"] == "").sum())}
    if against is not None:
        ref_f = pd.read_parquet(Path(against) / "forecast.parquet")
        ref_d = pd.read_parquet(Path(against) / "decisions.parquet")
        res |= diff(led, ref_f, ref_d, explain=False)
    if out or against is not None:
        out = out or cfg.out / "replay"
        out.mkdir(parents=True, exist_ok=True)
        led.to_parquet(out / "ledger.parquet", index=False)
        (out / "replay.md").write_text(_diff_md("Replay — the live path over " + "+".join(fold_names) + (f" against `{against}`" if against else ""), res))
    return res | {"ledger": led}


def diff(led: pd.DataFrame, ref_f: pd.DataFrame, ref_d: pd.DataFrame, explain: bool, hold_bars: int = PARAMS["hold"]) -> dict:
    """The ledger against a harness run: every forecast cell equal (NaN with NaN, else within F_TOL) and the same accepted
    set (t, symbol, side, size). With `explain`, a disagreement at a bar where the ledger has a `no_bar` row, or on a pair
    the ledger skipped as `late` within the previous hold, is counted as explained (downtime), not as a failure."""
    L = led.copy()
    L["t"] = pd.to_datetime(L["t"], utc=True)
    F = ref_f.copy()
    F["t"] = pd.to_datetime(F["t"], utc=True)
    m = L.merge(F[["t", "symbol", "f_bps", "sigma_h"]], on=["t", "symbol"], how="outer", suffixes=("", "_ref"), indicator=True)
    both = m["_merge"] == "both"
    df = (m["f_bps"] - m["f_bps_ref"]).abs()
    ds = (m["sigma_h"] - m["sigma_h_ref"]).abs()
    nan_ok = m["f_bps"].isna() == m["f_bps_ref"].isna()
    cell_bad = both & ~((nan_ok & (df.fillna(0) <= F_TOL)) & ((m["sigma_h"].isna() == m["sigma_h_ref"].isna()) & (ds.fillna(0) <= F_TOL)))
    only_led, only_ref = m["_merge"] == "left_only", m["_merge"] == "right_only"
    if explain:
        no_bar_t = set(L.loc[L["skip"] == "no_bar", "t"])
        cell_bad &= ~m["t"].isin(no_bar_t)
        only_ref &= ~m["t"].isin(no_bar_t)
    D = ref_d[ref_d["accepted"]].copy()
    D["t"] = pd.to_datetime(D["t"], utc=True)
    T = L[L["skip"] == ""]
    a = T.merge(D[["t", "symbol", "side", "size"]], on=["t", "symbol"], how="outer", suffixes=("", "_ref"), indicator=True)
    a_both = a["_merge"] == "both"
    same = a_both & (a["side"] == a["side_ref"]) & np.isclose(a["size"].fillna(-1), a["size_ref"].fillna(-1), rtol=1e-9, atol=1e-12)
    bad = a[~same].copy()
    if explain and len(bad):
        late = L[L["skip"] == "late"][["t", "symbol"]]
        expl = []
        for _, r in bad.iterrows():
            w = late[(late["symbol"] == r["symbol"]) & (late["t"] <= r["t"]) & (late["t"] > r["t"] - hold_bars * BAR)]
            expl.append(len(w) > 0 or r["t"] in no_bar_t)
        bad["explained"] = expl
    else:
        bad["explained"] = False
    n_cells = int(both.sum())
    res = {"cells_compared": n_cells, "cells_only_ledger": int(only_led.sum()), "cells_only_ref": int(only_ref.sum()), "cells_differ": int(cell_bad.sum()),
           "max_abs_df_bps": float(df[both].max()) if n_cells else np.nan, "max_abs_dsigma": float(ds[both].max()) if n_cells else np.nan,
           "taken_ledger": int(len(T)), "taken_ref": int(len(D)), "taken_same": int(same.sum()), "taken_differ": int((~bad["explained"]).sum()) if len(bad) else 0,
           "taken_differ_explained": int(bad["explained"].sum()) if len(bad) else 0,
           "differ_rows": bad.drop(columns=["_merge"]).head(50).to_dict("records") if len(bad) else []}
    res["pass"] = bool(res["cells_differ"] == 0 and res["cells_only_ref"] == 0 and res["taken_differ"] == 0)
    return res


def _diff_md(title: str, r: dict) -> str:
    keys = ["pass", "bars", "rows", "taken", "cells_compared", "cells_only_ledger", "cells_only_ref", "cells_differ", "max_abs_df_bps", "max_abs_dsigma",
            "taken_ledger", "taken_ref", "taken_same", "taken_differ", "taken_differ_explained", "causal_check"]
    md = [f"# {title}\n", f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC\n", "\n| key | value |\n|---|---|"]
    md += [f"| {k} | {r[k]} |" for k in keys if k in r]
    if r.get("differ_rows"):
        md += ["\n## Decisions that differ (first 50)\n", pd.DataFrame(r["differ_rows"]).to_markdown(index=False)]
    return "\n".join(md) + "\n"


# ---- identity check 2: the harness over the ledger's life, against the ledger ---------------------------------------------------------
def check(cfg: Config = Config(), now: pd.Timestamp | None = None) -> dict:
    """The harness (block-wise fit/decide on the full candle file, then `bt.accept`) from the ledger's start to its last
    decided bar, diffed against decisions.csv; plus `bt.causal_check` on the current block. Written to
    output/serve/checks/check_<date>.md and health['last_check']."""
    now = now or pd.Timestamp.now("UTC")
    st = read_state(cfg)
    dec = read_decisions(cfg)
    if "ledger_start" not in st or dec.empty:
        raise SystemExit("nothing to check: the ledger has not started")
    t0, t1 = pd.Timestamp(st["ledger_start"]), dec["t"].max()
    M = market(load_candles(cfg), cfg.pairs)
    y = bt.labels(M, cfg.hold, LATENCY)
    s = RidgeBook(**cfg.params)
    ensure_chunked(s, M)
    starts = block_starts(t1, cfg.refit_folds)
    starts = [b for b in starts if b >= block_start(t0, cfg)]
    out, last_block = [], None
    for i, ba in enumerate(starts):
        bb = starts[i + 1] if i + 1 < len(starts) else t1 + BAR
        cut = max(M.index.searchsorted(ba) - (LATENCY + cfg.hold), 0)
        s.fit(M.until(ba), y.iloc[:cut], ba)
        d = s.decide(M.until(bb), max(ba, t0), bb)
        out.append(d[(d["t"] >= max(ba, t0)) & (d["t"] < bb)].assign(hold=cfg.hold, fold="live", block=i))
        last_block = (ba, bb)
    hd = pd.concat(out, ignore_index=True).sort_values(["t", "symbol"], kind="mergesort").reset_index(drop=True)
    hd = bt.accept(hd, M.index)
    cells = s.oos()
    cells = cells[(cells["t"] >= t0) & (cells["t"] <= t1)]
    res = diff(dec, cells, hd, explain=True, hold_bars=cfg.hold)
    causal = "not run"
    if last_block is not None:
        ba, bb = last_block
        try:
            bt.causal_check(s, M, max(ba, t0), min(bb, M.index[-1] + BAR))
            causal = "pass"
        except AssertionError as e:
            causal, res["pass"] = f"FAIL: {e}", False
    res["causal_check"] = causal
    res |= {"window": [t0.isoformat(), t1.isoformat()], "blocks": len(starts)}
    d = cfg.out / "checks"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"check_{now:%Y-%m-%d}.md").write_text(_diff_md(f"Causal check — the harness over {t0:%Y-%m-%d} → {t1:%Y-%m-%d %H:%M} against the ledger", res))
    health(cfg, now, last_check={"date": now.isoformat(), "pass": res["pass"], "cells_differ": res["cells_differ"], "taken_differ": res["taken_differ"],
                                  "taken_differ_explained": res["taken_differ_explained"], "causal_check": causal})
    _log(cfg, f"check pass={res['pass']} cells={res['cells_compared']} differ={res['cells_differ']} taken_differ={res['taken_differ']} explained={res['taken_differ_explained']} causal={causal}")
    return res


# ---- the command --------------------------------------------------------------------------------------------------------------------
def main(args) -> None:
    cfg = Config()
    if args.action == "seed":
        r = seed(cfg, Path(args.src), Path(args.dst) if args.dst else None)
        print(f"seed {r['file']}: {r['rows']:,} rows, {r['pairs']} pairs, {r['first']} .. {r['last']}\n{r['per_pair']}")
    elif args.action == "fetch":
        print(fetch(cfg, pd.Timestamp.now("UTC")))
    elif args.action == "start":
        print(start(cfg))
    elif args.action == "decide":
        print(run_decide(cfg))
    elif args.action == "mark":
        print(run_mark(cfg))
    elif args.action == "status":
        print(status(cfg))
    elif args.action == "check":
        r = check(cfg)
        print(_diff_md("Causal check", r))
        sys.exit(0 if r["pass"] else 1)
    elif args.action == "replay":
        r = replay(cfg, args.folds, Path(args.against))
        print(_diff_md("Replay", {k: v for k, v in r.items() if k != "ledger"}))
        sys.exit(0 if r["pass"] else 1)
    elif args.action == "ledger":
        print(ledger(cfg).to_string())
