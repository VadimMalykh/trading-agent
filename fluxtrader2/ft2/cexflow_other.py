"""The exchange-balance audit's DATA SIDE on the OTHER exchanges (2026-11-11, the day's shortlist item 3; nothing registered, no list frozen):
`cexflow`'s own ingest (`_rows`) and its own event rule (`cexflow.events`, called UNCHANGED with the module's inputs swapped for one call and
restored) on each raw DefiLlama file under data/raw/external/defillama_cex_other/<slug>_<date>.json. COUNTS only: no price is read, no bar at
or after a t0, no cost row; nothing under output/cexflow/ or ft2/cexflow_*.csv is written (Binance's path and R85's inputs stay as they are).

per exchange   the series' first / last stamp, the stamps' hour, the tracked bases (those with a perpetual), every |change| ≥ 5 % row with its
               `why`, the MEMBERS' inflow / outflow CELLS by fold — `cexflow.events`' columns and reasons to the letter.
own tokens     OWN: the exchange's own token excluded BY NAME (Binance's rule for BNB); the `…-OwnTokens` chains out with `-staking` / `-borrowed`.
list_commit    False everywhere: the other adapters' wallet-list git logs are not fetched (a gap named in the audit, not a flag).
contracts      `um_first_month.csv` and `candles_5m_archive` live on the work VM. Where the first is missing (the laptop) the contract table is a
               PROXY rebuilt from Binance's own `output/cexflow/events.csv` (base → symbol by the nearest Binance row in time, the perpetual's
               first bar as written there) plus the member files (a member never seen there: first bar = its first block − 30 d, a lower bound of
               its age) — `contracts: proxy` in the output; a base with no Binance jump and no membership has no perpetual here.
pooled         the members' inflow cells per fold over the exchanges, the distinct names, the cells with another exchange's (or Binance's)
               eligible inflow row on the same name within ±1 day, the five busiest names' share → output/cexflow_other/audit_other.md / .json.
"""
from __future__ import annotations

import contextlib
import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import cexflow, data
from . import coinbase as cb
from . import upgrades as up

RAW_DIR = data.RAW / "external" / "defillama_cex_other"
OUT = Path("output/cexflow_other")
BINANCE_EVENTS = Path("output/cexflow/events.csv")
SLUGS = ("okx", "bybit", "bitfinex", "robinhood", "bitget", "gate", "gemini", "bitstamp", "mexc", "deribit", "htx", "kucoin", "crypto-com", "hashkey-exchange", "bitkub")
OWN: dict[str, dict[str, str]] = {          # the exchange's own token, by name (Binance's rule for BNB)
    "okx": {"OKB": "the exchange's own token"}, "bitfinex": {"LEO": "the exchange's own token"}, "bitget": {"BGB": "the exchange's own token"},
    "gate": {"GT": "the exchange's own token"}, "mexc": {"MX": "the exchange's own token"}, "htx": {"HT": "the exchange's own token", "HTX": "the exchange's own token"},
    "kucoin": {"KCS": "the exchange's own token"}, "crypto-com": {"CRO": "the exchange's own token"}, "bybit": {"MNT": "the exchange's affiliated token (Mantle, the former BIT)"},
    "hashkey-exchange": {"HSK": "the exchange's own token"}, "bitkub": {"KUB": "the exchange's own token"},
}
FOLDS = ("F1", "F2", "F3", "F4", "F5")
NEAR = pd.Timedelta(days=1)
LIVE = ("eligible", cexflow.F5_LISTED)


def files(slugs=SLUGS) -> dict[str, Path]:
    """Per slug its NEWEST raw file (the name's date sorts)."""
    out = {}
    for s in slugs:
        f = sorted(glob.glob(str(RAW_DIR / f"{s}_*.json")))
        if f:
            out[s] = Path(f[-1])
    return out


def series_of(path: Path, bases: set[str]) -> tuple[pd.DataFrame, dict]:
    """`cexflow._rows` on the file, the `…-OwnTokens` legs out, then `cexflow.series`' sum over chains; the file's facts beside."""
    R = cexflow._rows(path, None)
    own = R["chain"].str.endswith("-OwnTokens") | (R["chain"] == "OwnTokens")
    R = R[~own]
    info = {"file": str(path), "md5": cexflow.md5(path), "chains": sorted(R["chain"].unique()), "tokens_all": int(R["base"].nunique()), "rows_all": int(len(R))}
    if len(R):
        st = pd.DatetimeIndex(R["stamp"].unique()).sort_values()
        daily = st[(st.hour == 0) & (st.minute == 0) & (st.second == 0)]
        info |= {"first_stamp": str(st[0]), "last_stamp": str(st[-1]), "stamps": int(len(st)), "stamps_at_0000": int(len(daily)), "stamps_off_0000": int(len(st) - len(daily)),
                 "first_daily": str(daily[0]) if len(daily) else None, "last_daily": str(daily[-1]) if len(daily) else None,
                 "max_gap_d": float(np.max(np.diff(st.as_unit("ns").asi8)) / 86400e9) if len(st) > 1 else None}
    R = R[R["base"].isin(bases)]
    info["bases_tracked"] = int(R["base"].nunique())
    S = R.groupby(["base", "stamp"], as_index=False).agg(amount=("amount", "sum"), usd=("usd", "sum"), chains_n=("chain", "nunique"))
    return S.sort_values(["base", "stamp"]).reset_index(drop=True), info


# ---- the contract table: the VM's file where it is, else the proxy ----------------------------------------------------------------
class Proxy:
    """Base → perpetual and the perpetual's first bar from Binance's own events table and the member files (the laptop: no `um_first_month.csv`)."""

    def __init__(self, binance_events: Path = BINANCE_EVENTS, members: pd.DataFrame | None = None):
        M = up.member_symbols() if members is None else members
        rows = []
        if Path(binance_events).exists():
            E = pd.read_csv(binance_events, usecols=["base", "symbol", "t0", "perp_first", "perp_first_source"]).dropna(subset=["symbol"])
            E["t0"] = pd.to_datetime(E["t0"], utc=True, format="ISO8601")
            E["perp_first"] = pd.to_datetime(E["perp_first"], utc=True, format="ISO8601")
            rows.append(E)
        seen = set(rows[0]["symbol"]) if rows else set()
        m = M[~M["symbol"].isin(seen)].groupby("symbol", as_index=False)["block"].min()
        if len(m):
            rows.append(pd.DataFrame({"base": m["symbol"].map(cb.base), "symbol": m["symbol"], "t0": m["block"], "perp_first": m["block"] - cexflow.PERP_AGE,
                                      "perp_first_source": "member_block"}))
        self.t = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["base", "symbol", "t0", "perp_first", "perp_first_source"])
        self.by_base = {b: g.sort_values("t0") for b, g in self.t.groupby("base")}
        self.first = self.t.dropna(subset=["perp_first"]).sort_values("perp_first").groupby("symbol").first()

    def contracts(self) -> pd.DataFrame:
        return self.t.drop_duplicates("symbol")[["symbol", "base"]].reset_index(drop=True)

    def contract_for(self, fm, tick: str, t0: pd.Timestamp):
        g = self.by_base.get(tick)
        if g is None:
            return None
        return str(g["symbol"].iloc[int(np.argmin(np.abs((g["t0"] - t0).to_numpy())))])

    def perp_first(self, symbols, fm) -> pd.DataFrame:
        return pd.DataFrame([{"symbol": s, "perp_first": self.first.loc[s, "perp_first"] if s in self.first.index else pd.NaT,
                              "perp_first_source": self.first.loc[s, "perp_first_source"] if s in self.first.index else "none"} for s in symbols])


@contextlib.contextmanager
def _swapped(S: pd.DataFrame, excluded: dict[str, str], proxy: Proxy | None):
    """`cexflow.events`' inputs for ONE call — the series, the exclusions, no commit days, the proxy's contract functions — then put back."""
    keep = (cexflow.series, cexflow.commit_days, cexflow.EXCLUDED, up.contracts, up.contract_for, up.perp_first)
    cexflow.series, cexflow.commit_days, cexflow.EXCLUDED = (lambda: S.copy()), (lambda: set()), dict(excluded)
    if proxy is not None:
        up.contracts, up.contract_for, up.perp_first = proxy.contracts, proxy.contract_for, proxy.perp_first
    try:
        yield
    finally:
        cexflow.series, cexflow.commit_days, cexflow.EXCLUDED, up.contracts, up.contract_for, up.perp_first = keep


def proxy_or_none() -> Proxy | None:
    return None if up.FIRST.exists() else Proxy()


def events_of(path: Path, slug: str, proxy: Proxy | None = None) -> tuple[pd.DataFrame, dict]:
    """`cexflow.events(write=False)` on one exchange's file: every |change| ≥ THRESH row with its `why`, plus the file's facts."""
    bases = set((proxy.contracts() if proxy is not None else up.contracts())["base"])
    S, info = series_of(path, bases)
    with _swapped(S, OWN.get(slug, {}), proxy):
        E = cexflow.events(write=False)
    E.insert(0, "exchange", slug)
    info |= {"exchange": slug, "contracts": "proxy" if proxy is not None else "um_first_month", "excluded": sorted(OWN.get(slug, {})), "jumps": int(len(E)),
             "eligible_rows": int((E["why"] == "eligible").sum()), "not_eligible": E[~E["why"].isin(LIVE)]["why"].value_counts().to_dict()}
    return E, info


def cells(E: pd.DataFrame, side: str = "in", member: bool = True) -> pd.DataFrame:
    return E[E["why"].isin(LIVE) & (E["side"] == side) & (E["member_at_t0"] == member) & E["cell"]]


def fold_counts(E: pd.DataFrame, side: str, member: bool = True) -> dict[str, int]:
    c = cells(E, side, member)["fold"].value_counts()
    return {f: int(c.get(f, 0)) for f in FOLDS}


def _near(c: pd.DataFrame, other: pd.DataFrame) -> np.ndarray:
    """Per cell: another table's live inflow row on the same symbol within ±NEAR of the cell's t0."""
    ns = lambda x: pd.DatetimeIndex(pd.to_datetime(x, utc=True)).as_unit("ns").asi8      # noqa: E731
    by = {s: ns(g["t0"]) for s, g in other.groupby("symbol")}
    return np.array([s in by and bool(np.any(np.abs(by[s] - t) <= NEAR.value)) for s, t in zip(c["symbol"], ns(c["t0"]))], dtype=bool)


def pooled(A: pd.DataFrame, B: pd.DataFrame | None) -> dict:
    """The members' inflow cells over the exchanges: per fold, the names, the coincidences (±1 day, the same name), the five busiest names' share.
    `A` every exchange's events (the `exchange` column); `B` Binance's events table, or None."""
    c = cells(A, "in").copy()
    live_in = A[A["why"].isin(LIVE) & (A["side"] == "in")].copy()
    for d in (c, live_in):
        d["t0"] = pd.to_datetime(d["t0"], utc=True)
    rep = {"cells_by_fold": {f: int((c["fold"] == f).sum()) for f in FOLDS}, "cells_F1F2": int(c["fold"].isin(["F1", "F2"]).sum()), "cells_F3F4": int(c["fold"].isin(["F3", "F4"]).sum())}
    for tag, fs in (("F1F2", ["F1", "F2"]), ("F3F4", ["F3", "F4"])):
        g = c[c["fold"].isin(fs)]
        other = np.zeros(len(g), dtype=bool)
        for ex in g["exchange"].unique():
            k = (g["exchange"] == ex).to_numpy()
            other[k] = _near(g[k], live_in[live_in["exchange"] != ex])
        top = g["symbol"].value_counts()
        # one (name, day) once: the cells of several exchanges on the same name within ±1 day collapsed to the earliest
        gs = g.sort_values("t0")
        last, n_unique = {}, 0
        for s, t in zip(gs["symbol"], gs["t0"]):
            if s not in last or (t - last[s]) > NEAR:
                n_unique += 1
            last[s] = t
        rep[tag] = {"cells": int(len(g)), "names": int(g["symbol"].nunique()), "exchanges_with_cells": int(g["exchange"].nunique()), "with_another_exchange_within_1d": int(other.sum()),
                    "name_days_after_collapsing_1d": int(n_unique), "top5_names": top.head(5).to_dict(), "top5_share": float(top.head(5).sum() / max(len(g), 1))}
        if B is not None:
            b = B[B["why"].isin(LIVE) & (B["side"] == "in")].copy()
            b["t0"] = pd.to_datetime(b["t0"], utc=True, format="ISO8601")
            bc = b[b["member_at_t0"] & b["cell"] & b["fold"].isin(fs)]
            rep[tag] |= {"with_a_binance_inflow_row_within_1d": int(_near(g, b).sum()), "binance_cells": int(len(bc)), "binance_names": int(bc["symbol"].nunique()),
                         "names_not_in_binance_cells": int(len(set(g["symbol"]) - set(bc["symbol"]))),
                         "binance_cells_with_another_exchange_within_1d": int(_near(bc, live_in).sum())}
    return rep


def audit(slugs=SLUGS, binance_events: Path = BINANCE_EVENTS) -> str:
    OUT.mkdir(parents=True, exist_ok=True)
    proxy = proxy_or_none()
    fs = files(slugs)
    parts, infos, bad = [], [], {}
    for slug in slugs:
        if slug not in fs:
            bad[slug] = "no file"
            continue
        try:
            E, info = events_of(fs[slug], slug, proxy)
        except Exception as e:  # noqa: BLE001
            bad[slug] = repr(e)[:300]
            continue
        E.to_csv(OUT / f"events_{slug}.csv", index=False)
        info |= {"member_in_cells": fold_counts(E, "in"), "member_out_cells": fold_counts(E, "out"), "nonmember_in_cells": fold_counts(E, "in", False),
                 "stamp_hours": sorted({round(float(h), 2) for h in E["stamp_hour"].unique()})[:6] if len(E) else []}
        parts.append(E); infos.append(info)
        print(f"{slug}: {info.get('first_daily')} → {info.get('last_daily')}, {info['bases_tracked']} bases, {info['jumps']} jumps, member in-cells {info['member_in_cells']}", flush=True)
    A = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    B = pd.read_csv(binance_events) if Path(binance_events).exists() else None
    P = pooled(A, B) if len(A) else {}
    rep = {"generated": f"{pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC", "contracts": "proxy" if proxy is not None else "um_first_month", "exchanges": infos, "unusable": bad, "pooled": P}
    (OUT / "audit_other.json").write_text(json.dumps(rep, indent=1, default=str))
    A.to_csv(OUT / "events_all.csv", index=False)
    t = pd.DataFrame([{"exchange": i["exchange"], "first_daily": (i.get("first_daily") or "")[:10], "last_daily": (i.get("last_daily") or "")[:10], "stamps": i.get("stamps"),
                       "off_0000": i.get("stamps_off_0000"), "max_gap_d": round(i.get("max_gap_d") or 0, 1), "tokens": i["tokens_all"], "bases": i["bases_tracked"], "jumps": i["jumps"],
                       "eligible": i["eligible_rows"], **{f"in_{f}": i["member_in_cells"][f] for f in FOLDS}, **{f"out_{f}": i["member_out_cells"][f] for f in FOLDS}} for i in infos])
    md = [f"# The exchange-balance audit on the other exchanges — counts only (`ft2/cexflow_other.py`)\n",
          f"generated {rep['generated']} · contracts: **{rep['contracts']}** · no price read, no bar after a t0, nothing frozen, nothing registered\n",
          "\n## Per exchange — the series and the MEMBERS' cells (|change| ≥ 5 %, one a name and side per 7 days) by fold\n", t.to_markdown(index=False), "\n",
          "\n*off_0000*: stamps not at 00:00 UTC (the file's live point is one). *bases*: tokens with a perpetual. *in_/out_*: members' inflow / outflow cells.\n",
          "\n## Pooled over the exchanges — the members' INFLOW cells\n", "```\n", json.dumps(P, indent=1, default=str), "\n```\n",
          "\n## Unusable\n", json.dumps(bad, indent=1) if bad else "none", "\n",
          "\n## Not eligible, by reason (all exchanges)\n", "```\n", A[~A["why"].isin(LIVE)]["why"].value_counts().to_string() if len(A) else "", "\n```\n"]
    (OUT / "audit_other.md").write_text("\n".join(md))
    return "\n".join(md)


if __name__ == "__main__":
    print(audit())
