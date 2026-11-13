"""Decision CK1 (2026-11-06; PLAN P8 decision CK) — the exchange's OWN on-chain balance per token as a per-name EVENT: the source audit,
`ft2 cexflow fetch|ingest|events|bars|audit|knownat`. Nothing here joins a bar AFTER a t0 to anything; no price is read; no fold is read for a
label; nothing is registered.

source     DefiLlama's CEX adapter for Binance (`api.llama.fi/protocol/binance-cex`; free, keyless; the laptop reaches it — decision CK's
           count): the labelled hot and cold wallets' balances per TOKEN per CHAIN, one point a day since 2022-11-12, read by the adapter at
           run time (the point's `date` is the run's unix second, not a midnight). `fetch` saves the whole file RAW under
           data/raw/external/defillama_cex/binance-cex_<YYYYMMDD>.json — the first fetch (2026-11-06, md5 45439f98…) is the known-at
           probe's first half; `knownat` compares the two newest files (every (stamp, chain, token) amount in both: identical or not). The
           wallet list is a public file with a git history (DefiLlama-Adapters/projects/binance/{config,index}.js); `fetch` saves its commit
           days too (adapter_commits_<YYYYMMDD>.json) — a jump on a commit's day may be the list's, not a holder's (`list_commit`).
table      data/cex_balance.parquet: (stamp, day, base, chain, amount, usd) for the bases of `um_first_month.csv` — the `-staking` and
           `-borrowed` chains out, `tokensInUsd` beside `tokens` (the day's price, known at the stamp).
event      per base the balance summed over chains at each stamp; the CHANGE against the previous stamp (consecutive stamps ≤ MAX_GAP apart;
           the series' first WARMUP days out); an event where |change| ≥ THRESH — `side` in (the balance up: a holder's deposit before a
           sale) or out (down: a withdrawal after a buy); t0 = ts_known = the stamp (the registration's decision bar is the first 5m bar
           closing after t0 + the lag the known-at probe sets); flags at FLAGS (10 %, 20 %); the perpetual by `upgrades.contract_for` in the
           stamp's month, its first bar and age by the same rule; `member_at_t0` from the screener's blocks (rule (a)'s population).
eligible   the perpetual ≥ PERP_AGE old at t0, the base not EXCLUDED (the exchange's own token — written by name with the reason), t0 in
           F1 … F4 (F5 listed, not frozen). The 7-day collapse per (name, side) is a FLAG (`cell`), not a drop. `revert_3d` (the balance
           moving back within three stamps) is POST-t0 information: in events.csv as a description, never in the frozen lists.
lists      output/cexflow/events.csv (every candidate row with its `why`), output/cexflow/cexflow_f12.csv / _f34.csv (the eligible), frozen
           by hand as ft2/cexflow_f12.csv / _f34.csv and committed BEFORE any bar after a t0 is read for anything; cexflow_f5.csv listed.
bars       per frozen event the count of the name's 5m bars over [t0 − 2 d, t0 + 8 d) in `candles_5m_archive` — COUNTS; with --fetch the
           missing (name, month) files are fetched (R28's route) and the slice re-ingested whole under krlist's fingerprint.
audit      the counts by fold × side × member × cell, the names' shares, the stamp's hour, the sizes, the list-commit share, the 0o (i)
           cells, rule (a)'s B_i on the t0 day from the names' own cost rows, the known-at probe's result → output/cexflow/audit.md / .json,
           DATA.md `cex_balance`.
"""
from __future__ import annotations

import glob
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from . import data
from . import coinbase as cb
from . import upgrades as up

LLAMA = "https://api.llama.fi/protocol/binance-cex"
GITHUB = "https://api.github.com/repos/DefiLlama/DefiLlama-Adapters/commits?path=projects/binance/{fn}&per_page=100"
RAW_DIR = data.RAW / "external" / "defillama_cex"
TABLE = "cex_balance"
OUT = Path("output/cexflow")
LISTS = {"f12": Path(__file__).with_name("cexflow_f12.csv"), "f34": Path(__file__).with_name("cexflow_f34.csv"), "f5": Path(__file__).with_name("cexflow_f5.csv")}
THRESH = 0.05                      # an event: |change| ≥ 5 % of the holding between consecutive stamps (decision CK (cxviii)'s count)
FLAGS = (0.10, 0.20)
MAX_GAP = pd.Timedelta(days=1.5)   # consecutive stamps only: a point missing between two reads leaves the change undated
WARMUP = pd.Timedelta(days=30)     # the series' first days: a wallet's first labelling is a level, not a flow
REVERT = 3                         # described: the balance moving back by ≥ half the jump within this many stamps
PERP_AGE = pd.Timedelta(days=30)
COLLAPSE = pd.Timedelta(days=7)
BAR = pd.Timedelta("5min")
DAY = pd.Timedelta(days=1)
FROZEN_FOLDS = ("F1", "F2", "F3", "F4")
TAGS = {"F1": "f12", "F2": "f12", "F3": "f34", "F4": "f34"}
F5_LISTED = "outside F1 … F4 (F5: listed, not frozen)"
UA = {"User-Agent": "ft2-cexflow/1", "Accept": "application/json"}
# the exchange's own wallet operations, excluded BY NAME with the reason before the lists are frozen (decision CK1 (ii)); the audit's per-name
# table (jumps, the revert share, the chains) is what a next exclusion is written from — never a name's price after a t0
EXCLUDED: dict[str, str] = {
    "BNB": "the exchange's own token — the labelled wallets are the issuer's treasury and gas, not holders' deposits",
}
LIST_COLS = ["symbol", "base", "mult", "t0", "ts_known", "release", "code", "fold", "block", "perp_first", "perp_first_source", "perp_age_days",
             "member_at_t0", "side", "stamp_hour", "gap_d", "amount_before", "amount_after", "change", "usd_before", "usd_jump", "chains_n",
             "flag_10", "flag_20", "list_commit", "repeat_n", "days_since_prior", "cell"]
DESCRIBED = ["revert_3d"]


# ---- the source ------------------------------------------------------------------------------------------------------------------
def _get(url: str, timeout: int = 180) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def fetch(stamp: pd.Timestamp | None = None) -> dict:
    """The adapter's whole file saved raw (binance-cex_<YYYYMMDD>.json) and the wallet list's commit days (adapter_commits_<YYYYMMDD>.json)."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    day = f"{stamp or pd.Timestamp.now('UTC'):%Y%m%d}"
    dest = RAW_DIR / f"binance-cex_{day}.json"
    if dest.exists():
        print(f"{dest} exists — kept (the probe wants the day's FIRST fetch)", flush=True)
    else:
        dest.write_bytes(_get(LLAMA))
    rep = {"file": str(dest), "bytes": dest.stat().st_size, "md5": md5(dest)}
    commits = {}
    for fn in ("config.js", "index.js"):
        try:
            c = json.loads(_get(GITHUB.format(fn=fn), timeout=60))
            commits[fn] = [{"date": x["commit"]["committer"]["date"], "sha": x["sha"][:10], "message": x["commit"]["message"].splitlines()[0][:120]} for x in c]
        except Exception as e:  # noqa: BLE001
            commits[fn] = {"error": repr(e)[:200]}
    (RAW_DIR / f"adapter_commits_{day}.json").write_text(json.dumps(commits, indent=1))
    rep["commits"] = {k: (len(v) if isinstance(v, list) else v) for k, v in commits.items()}
    print(json.dumps(rep, indent=1), flush=True)
    return rep


def _files(pattern: str) -> list[Path]:
    return [Path(p) for p in sorted(glob.glob(str(RAW_DIR / pattern)))]


def _latest(pattern: str) -> Path:
    f = _files(pattern)
    if not f:
        raise SystemExit(f"cexflow: no {pattern} under {RAW_DIR} — `ft2 cexflow fetch` first")
    return f[-1]


def _rows(path: Path, bases: set[str] | None = None) -> pd.DataFrame:
    """The raw file as (stamp, chain, base, amount, usd) rows — the `-staking` / `-borrowed` chains out; every token when `bases` is None."""
    if str(path).endswith(".gz"):                                   # R96's live files are saved gzipped (scripts/cexflow_live.py)
        import gzip
        d = json.loads(gzip.open(path, "rb").read())
    else:
        d = json.loads(path.read_text())
    out = []
    for ch, v in d.get("chainTvls", {}).items():
        if ch.endswith("-staking") or ch.endswith("-borrowed"):
            continue
        usd = {int(r["date"]): r.get("tokens", {}) for r in v.get("tokensInUsd", [])}
        for r in v.get("tokens", []):
            u = usd.get(int(r["date"]), {})
            for tok, amt in r.get("tokens", {}).items():
                if bases is None or tok in bases:
                    out.append((int(r["date"]), ch, tok, float(amt), float(u.get(tok, np.nan))))
    R = pd.DataFrame(out, columns=["stamp_s", "chain", "base", "amount", "usd"])
    R["stamp"] = pd.to_datetime(R["stamp_s"], unit="s", utc=True)
    return R.drop(columns="stamp_s")


def ingest(write: bool = True) -> dict:
    """The latest raw file → data/cex_balance.parquet for the bases of `um_first_month.csv`; the ingest's fingerprint beside."""
    path = _latest("binance-cex_*.json")
    bases = set(up.contracts()["base"])
    R = _rows(path, bases)
    R["day"] = R["stamp"].dt.floor("D")
    R = R.sort_values(["base", "chain", "stamp"]).reset_index(drop=True)
    rep = {"file": str(path), "md5": md5(path), "rows": int(len(R)), "bases": int(R["base"].nunique()), "chains": int(R["chain"].nunique()),
           "stamps": int(R["stamp"].nunique()), "first": str(R["stamp"].min()), "last": str(R["stamp"].max()), "amount_sum": float(R["amount"].sum())}
    if write:
        data.PROC.mkdir(parents=True, exist_ok=True)
        R.to_parquet(data.PROC / f"{TABLE}.parquet", index=False)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "ingest.json").write_text(json.dumps(rep, indent=1))
        print(json.dumps(rep, indent=1), flush=True)
    return rep


def series() -> pd.DataFrame:
    """Per (base, stamp) the balance summed over chains: amount, usd, chains_n — sorted."""
    p = data.PROC / f"{TABLE}.parquet"
    if not p.exists():
        raise SystemExit(f"cexflow: {p} missing — `ft2 cexflow ingest`")
    R = pd.read_parquet(p)
    S = R.groupby(["base", "stamp"], as_index=False).agg(amount=("amount", "sum"), usd=("usd", "sum"), chains_n=("chain", "nunique"))
    return S.sort_values(["base", "stamp"]).reset_index(drop=True)


def commit_days() -> set[pd.Timestamp]:
    """The wallet list's commit days (UTC, floored) from the latest adapter_commits file; empty when none."""
    f = _files("adapter_commits_*.json")
    if not f:
        return set()
    c = json.loads(f[-1].read_text())
    days = set()
    for v in c.values():
        if isinstance(v, list):
            days |= {pd.Timestamp(x["date"]).tz_convert("UTC").floor("D") for x in v}
    return days


# ---- the events ---------------------------------------------------------------------------------------------------------------
def events(write: bool = True) -> pd.DataFrame:
    """Every |change| ≥ THRESH between consecutive stamps with its flags and `why`; the eligible ones written as the lists to freeze."""
    S = series()
    fm = up.contracts()
    M = up.member_symbols()
    cd = commit_days()
    S["prev_amount"] = S.groupby("base")["amount"].shift(1)
    S["prev_stamp"] = S.groupby("base")["stamp"].shift(1)
    S["first_stamp"] = S.groupby("base")["stamp"].transform("min")
    S["gap_d"] = (S["stamp"] - S["prev_stamp"]) / DAY
    S["age_d"] = (S["stamp"] - S["first_stamp"]) / DAY
    S["change"] = S["amount"] / S["prev_amount"] - 1.0
    ok = S["prev_amount"].gt(0) & S["change"].abs().ge(THRESH)
    D = S[ok].copy()
    # the described revert: the balance back by ≥ half the jump within REVERT stamps (post-t0 — events.csv only)
    nxt = {k: S.loc[S["base"] == k, "amount"].to_numpy() for k in D["base"].unique()}
    idx = {k: S.index[S["base"] == k].to_numpy() for k in nxt}
    rev = []
    for r in D.itertuples():
        a = nxt[r.base]; pos = int(np.searchsorted(idx[r.base], r.Index))
        jump = r.amount - r.prev_amount
        after = a[pos + 1:pos + 1 + REVERT]
        rev.append(bool(len(after)) and bool(np.any((after - r.amount) * np.sign(jump) <= -0.5 * abs(jump))))
    D["revert_3d"] = rev
    D["side"] = np.where(D["change"] > 0, "in", "out")
    D["symbol"] = [up.contract_for(fm, b, t) for b, t in zip(D["base"], D["stamp"])]
    D["t0"] = D["stamp"]
    D["ts_known"] = D["stamp"]
    D["release"] = D["stamp"]
    D["stamp_hour"] = D["stamp"].dt.hour + D["stamp"].dt.minute / 60.0
    D["code"] = [f"{b}_{t:%Y%m%d}_{s}" for b, t, s in zip(D["base"], D["stamp"], D["side"])]
    D["amount_before"] = D["prev_amount"]
    D["amount_after"] = D["amount"]
    D["usd_before"] = D["usd"] / (1.0 + D["change"])
    D["usd_jump"] = D["usd"] - D["usd_before"]
    D["flag_10"] = D["change"].abs() >= FLAGS[0]
    D["flag_20"] = D["change"].abs() >= FLAGS[1]
    D["list_commit"] = [bool(cd) and (t.floor("D") in cd or (t.floor("D") - DAY) in cd) for t in D["stamp"]]
    has = D["symbol"].notna()
    D["mult"] = D["symbol"].map(lambda s: cb.mult_of(s) if isinstance(s, str) else np.nan)
    pf = up.perp_first(sorted(set(D.loc[has, "symbol"])), fm).set_index("symbol") if has.any() else pd.DataFrame(columns=["perp_first", "perp_first_source"])
    D["perp_first"] = D["symbol"].map(pf["perp_first"]) if len(pf) else pd.NaT
    D["perp_first_source"] = D["symbol"].map(pf["perp_first_source"]) if len(pf) else "none"
    D["perp_age_days"] = (D["t0"] - pd.to_datetime(D["perp_first"], utc=True)).dt.days
    D["fold"] = D["t0"].map(up.fold_of)
    D["block"] = [up.block_at(M, t) for t in D["t0"]]
    D["member_at_t0"] = [up.member_at(M, s, t) if isinstance(s, str) else False for s, t in zip(D["symbol"], D["t0"])]
    D = D.sort_values(["t0", "base", "side"]).reset_index(drop=True)
    why = []
    for r in D.itertuples():
        if r.base in EXCLUDED:
            w = f"excluded: {EXCLUDED[r.base]}"
        elif not isinstance(r.symbol, str):
            w = "no perpetual of the base listed in the stamp's month"
        elif r.age_d < WARMUP.days:
            w = f"the series younger than {WARMUP.days} days at the stamp (a wallet's first labelling)"
        elif r.gap_d > MAX_GAP / DAY:
            w = f"the previous stamp more than {MAX_GAP / DAY:.1f} days before (the change undated)"
        elif r.perp_first_source == "none" or pd.isna(r.perp_age_days):
            w = "no perpetual first bar known"
        elif r.perp_age_days < PERP_AGE.days:
            w = f"the perpetual younger than {PERP_AGE.days} days at the stamp (a launch, R28's population)"
        elif r.fold not in FROZEN_FOLDS:
            w = F5_LISTED if r.fold == "F5" else "outside F1 … F4"
        else:
            w = "eligible"
        why.append(w)
    D["why"] = why
    live = D["why"].isin(["eligible", F5_LISTED])
    D["repeat_n"] = 0
    D["days_since_prior"] = np.nan
    D["cell"] = False
    for (sym, side), g in D[live].groupby(["symbol", "side"]):
        last = None; prior = None
        for i, t in zip(g.index, g["t0"]):
            D.loc[i, "repeat_n"] = 0 if prior is None else D.loc[i, "repeat_n"]
            D.loc[i, "days_since_prior"] = np.nan if prior is None else (t - prior) / DAY
            k = last is None or (t - last) >= COLLAPSE
            D.loc[i, "cell"] = k
            if k:
                last = t
            prior = t
        D.loc[g.index, "repeat_n"] = np.arange(len(g))
    E = D[[*LIST_COLS, *DESCRIBED, "why"]].reset_index(drop=True)
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        E.to_csv(OUT / "events.csv", index=False)
        el = E[E["why"] == "eligible"]
        for tag in ("f12", "f34"):
            el[el["fold"].map(TAGS) == tag][LIST_COLS].to_csv(OUT / f"cexflow_{tag}.csv", index=False)
        E[E["why"] == F5_LISTED][LIST_COLS].to_csv(OUT / "cexflow_f5.csv", index=False)
        print(summary(E), flush=True)
    return E


def summary(E: pd.DataFrame) -> str:
    el = E[E["why"] == "eligible"]
    lines = [f"{len(E)} jumps of ≥ {THRESH:.0%} between consecutive stamps on {E['base'].nunique()} bases; {len(el)} eligible (the perpetual ≥ {PERP_AGE.days} d old, the series ≥ {WARMUP.days} d, t0 in F1 … F4)"]
    if len(el):
        t = el.groupby(["fold", "side", "member_at_t0"])["cell"].sum().unstack(["side", "member_at_t0"], fill_value=0)
        lines.append("eligible CELLS (the 7-day collapse per name and side) by fold × side × member_at_t0:\n" + t.to_string())
        lines.append(f"rows by side {el['side'].value_counts().to_dict()}; flag_10 {int(el['flag_10'].sum())}, flag_20 {int(el['flag_20'].sum())}; list_commit {int(el['list_commit'].sum())}; "
                     f"revert_3d (described) {int(el['revert_3d'].sum())}; distinct names F1+F2 {el[el['fold'].isin(['F1', 'F2'])]['symbol'].nunique()}, F3+F4 {el[el['fold'].isin(['F3', 'F4'])]['symbol'].nunique()}")
    lines.append(f"F5: {int((E['why'] == F5_LISTED).sum())} listed, not frozen")
    lines.append("not eligible, by reason:\n" + E[E["why"] != "eligible"]["why"].value_counts().to_string())
    return "\n".join(lines)


def frozen(tags=("f12", "f34")) -> pd.DataFrame:
    parts = []
    for tag in tags:
        p = LISTS[tag]
        if p.exists():
            d = pd.read_csv(p)
            for c in ("t0", "ts_known", "release", "block", "perp_first"):
                d[c] = pd.to_datetime(d[c], utc=True, format="ISO8601")
            if len(d):
                parts.append(d.assign(list=tag))
    if not parts:
        raise SystemExit(f"cexflow: no frozen list at {list(LISTS.values())} — run `ft2 cexflow events`, freeze the lists, commit")
    return pd.concat(parts, ignore_index=True)


# ---- the bars (counts) and the audit --------------------------------------------------------------------------------------------
def bars(fetch: bool = False, fetch_tags: tuple[str, ...] = ("f12",), fetch_flag: str | None = None) -> dict:
    """The frozen events' bars counted over [t0 − 2 d, t0 + 8 d); with `fetch` the missing (name, month) files of `fetch_tags` come from
    the archive and the slice is re-ingested whole under krlist's fingerprint; `fetch_flag` (0ac (v)'s rule) scopes the fetch to the rows
    carrying that flag (`member_at_t0`: the registered population — the non-members' months stay out); the count covers every row."""
    from . import archive, krlist
    L = frozen()
    OUT.mkdir(parents=True, exist_ok=True)
    cov = up.coverage(L)
    cov["list"] = L["list"].to_numpy()
    cov["flagged"] = L[fetch_flag].astype(bool).to_numpy() if fetch_flag else True
    need = krlist.missing_months(cov[cov["list"].isin(fetch_tags) & cov["flagged"]])
    rep = {"events": int(len(cov)), "complete": int((cov["share"] >= 0.95).sum()),
           "by_fold": {str(k): {"events": int(len(g)), "complete": int((g["share"] >= 0.95).sum()), "median_share": float(g["share"].median())} for k, g in cov.groupby("fold")},
           "missing_symbols": sorted(set(cov[cov["share"] < 0.95]["symbol"])), "missing_months_in_fetch_tags": need,
           "missing_files_in_fetch_tags": int(sum(len(m) for m in need.values()))}
    if fetch and need:
        fp = krlist.fingerprint()
        fp.to_csv(OUT / "fingerprint_before.csv", index=False)
        rep["fetch"] = {sym: archive.fetch_monthly("klines", sym, sub="5m", months=months) for sym, months in need.items()}
        rep["ingest"] = {k: str(v) for k, v in data.ingest_klines(krlist.ingest_symbols(sorted(need))).items()}
        chk = krlist.fingerprint_check(fp)
        (OUT / "fingerprint_check.json").write_text(json.dumps(chk, indent=1, default=str))
        rep["fingerprint"] = {"pass": chk["pass"], "changed": chk["changed"][:10], "names_before": chk["names_before"], "names_after": chk["names_after"]}
        if not chk["pass"]:
            print(json.dumps(rep, indent=1, default=str))
            raise SystemExit(2)
        cov = up.coverage(L)
        cov["list"] = L["list"].to_numpy()
        rep["complete_after"] = int((cov["share"] >= 0.95).sum())
        cov["flagged"] = L[fetch_flag].astype(bool).to_numpy() if fetch_flag else True
        rep["missing_after"] = krlist.missing_months(cov[cov["list"].isin(fetch_tags) & cov["flagged"]])
    cov.drop(columns=["months", "list", "flagged"], errors="ignore").to_csv(OUT / "bars.csv", index=False)
    print(json.dumps(rep, indent=1, default=str))
    return rep


def knownat(write: bool = True) -> dict:
    """The two newest raw files compared on every (stamp, chain, token) amount present in both — identical to 1e-9 relative, or not (a
    rewritten history); the stamps only in the newer are the days added, the stamps only in the older a removal — EXCEPT the older file's
    own last stamp: the adapter's run at fetch time (2026-11-06 07:02:23 in the first file), superseded by the next day's 00:00 point, is
    the live point, reported as `live_point_older` and not a removal (found 2026-11-09: 637,955 amounts equal, the live point the only
    stamp gone; the strict verdict kept as output/cexflow/knownat_20261109_strict.json)."""
    f = _files("binance-cex_*.json")
    if len(f) < 2:
        rep = {"files": [str(x) for x in f], "verdict": "one file — the second fetch is due a week after the first"}
    else:
        a, b = _rows(f[-2]), _rows(f[-1])
        ka, kb = a.set_index(["stamp", "chain", "base"])["amount"], b.set_index(["stamp", "chain", "base"])["amount"]
        both = ka.index.intersection(kb.index)
        x, y = ka.loc[both].to_numpy(), kb.loc[both].to_numpy()
        rel = np.abs(y - x) / np.maximum(np.abs(x), 1e-12)
        diff = rel > 1e-9
        sa, sb = set(a["stamp"]), set(b["stamp"])
        last_a = a["stamp"].max()
        live = last_a if last_a not in sb else None            # the older file's live point: its last stamp, gone from the newer
        removed = (sa - sb) - ({live} if live is not None else set())
        rep = {"files": [str(f[-2]), str(f[-1])], "md5": [md5(f[-2]), md5(f[-1])], "in_both": int(len(both)), "equal": int((~diff).sum()), "differ": int(diff.sum()),
               "max_rel_diff": float(rel.max()) if len(rel) else 0.0, "stamps_only_in_newer": sorted(str(s) for s in sb - sa), "stamps_only_in_older": sorted(str(s) for s in removed),
               "live_point_older": str(live) if live is not None else None, "live_point_keys": int((a["stamp"] == live).sum()) if live is not None else 0,
               "keys_only_in_older": int(len(ka.index.difference(kb.index))), "differ_sample": [f"{s} {c} {t}: {x[i]:.6g} → {y[i]:.6g}" for i, (s, c, t) in enumerate(both) if diff[i]][:20],
               "days_apart": float((pd.Timestamp(b["stamp"].max()) - pd.Timestamp(last_a)) / DAY)}
        rep["verdict"] = ("IDENTICAL on the overlap — a point-in-time source; the stamp is the adapter's run, t0 = the stamp" if rep["differ"] == 0 and not rep["stamps_only_in_older"]
                          else "REWRITTEN — the history moved under a re-fetch; the kind is dead as a point-in-time source (decision CK (cxix))")
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "knownat.json").write_text(json.dumps(rep, indent=1, default=str))
    print(json.dumps(rep, indent=1, default=str), flush=True)
    return rep


def audit(today: pd.Timestamp | None = None) -> str:
    from .govlist import BAR_MULT, TAKER_BPS, cost_rows
    today = today or pd.Timestamp.now("UTC")
    L = frozen()
    E = pd.read_csv(OUT / "events.csv") if (OUT / "events.csv").exists() else None
    cov = up.coverage(L)
    cr = cost_rows(L)
    OUT.mkdir(parents=True, exist_ok=True)
    cr.to_csv(OUT / "costs.csv", index=False)
    cells_tab = L[L["cell"]].groupby(["fold", "side", "member_at_t0"]).size().unstack(["side", "member_at_t0"], fill_value=0)
    names = {side: L[L["cell"] & (L["side"] == side) & L["member_at_t0"]].groupby("symbol").size().sort_values(ascending=False) for side in ("in", "out")}
    hod = pd.DatetimeIndex(L["t0"]).hour.value_counts().sort_index()
    q_change = L["change"].abs().quantile([0.5, 0.75, 0.9, 0.99]).round(4).to_dict()
    q_usd = L["usd_jump"].abs().quantile([0.1, 0.5, 0.9]).round(0).to_dict()
    q_age = L["perp_age_days"].quantile([0.1, 0.5, 0.9]).round(0).to_dict()
    pop = L[L["cell"] & (L["side"] == "in") & L["member_at_t0"]].copy()       # the registered population: members' inflow cells (rule (a))
    cells = {h: up.eligible_cells(pop, cov, hold=pd.Timedelta(days=h)) for h in (1, 3, 7)}
    bi = cr.set_index(["symbol", "t0"])["B_i"] if len(cr) else pd.Series(dtype=float)
    bi = bi[~bi.index.duplicated()]
    def bar_of(mask):
        if not len(cr):
            return {"priced": 0, "of": int(mask.sum())}
        v = pd.Series([bi.get((s, t), np.nan) for s, t in zip(L[mask]["symbol"], L[mask]["t0"])]).dropna()
        return {"priced": int(v.size), "of": int(mask.sum()), "B": round(float(v.mean()), 1) if v.size else None, "B_i_median": round(float(v.median()), 1) if v.size else None, "B_i_q90": round(float(v.quantile(0.9)), 1) if v.size else None}
    bars_by = {f"{tag} {side} {'members' if m else 'non-members'}": bar_of((L["list"] == tag) & L["cell"] & (L["side"] == side) & (L["member_at_t0"] == m))
               for tag in sorted(set(L["list"])) for side in ("in", "out") for m in (True, False)}
    rev = None
    if E is not None and "revert_3d" in E:
        el = E[E["why"] == "eligible"]
        rev = {"share_all": round(float(el["revert_3d"].mean()), 3) if len(el) else None,
               "by_name_members_in": {k: round(float(v), 2) for k, v in el[el["member_at_t0"] & (el["side"] == "in")].groupby("symbol")["revert_3d"].mean().sort_values(ascending=False).head(15).items()}}
    ka = json.loads((OUT / "knownat.json").read_text()) if (OUT / "knownat.json").exists() else {"verdict": "not run (`ft2 cexflow knownat` after the second fetch)"}
    raw = [{"file": p.name, "bytes": p.stat().st_size, "md5": md5(p)} for p in _files("binance-cex_*.json")]
    J = {"generated": f"{today:%Y-%m-%d %H:%M} UTC", "events": int(len(L)), "distinct_names": int(L["symbol"].nunique()),
         "cells_by_fold_side_member": {str(k): {f"{s} {m}": int(v) for (s, m), v in r.items()} for k, r in cells_tab.iterrows()},
         "population_members_in": {"cells": int(len(pop)), "by_fold": pop.groupby("fold").size().to_dict(), "names": int(pop["symbol"].nunique())},
         "top_names_members": {side: {k: int(v) for k, v in names[side].head(10).items()} for side in names},
         "top5_share_members_in": round(float(names["in"].head(5).sum() / max(1, names["in"].sum())), 3),
         "flags": {"flag_10": int(L["flag_10"].sum()), "flag_20": int(L["flag_20"].sum()), "list_commit": int(L["list_commit"].sum())},
         "change_abs_quantiles": q_change, "usd_jump_abs_q10_50_90": q_usd, "chains_n_median": float(L["chains_n"].median()),
         "stamp_hour_utc": {int(k): int(v) for k, v in hod.items()}, "gap_d_q10_50_90": L["gap_d"].quantile([0.1, 0.5, 0.9]).round(3).tolist(),
         "perp_age_days_q10_50_90": q_age, "perp_first_source": L["perp_first_source"].value_counts().to_dict(),
         "bars_complete": int((cov["share"] >= 0.95).sum()), "bars_by_fold": {str(k): int((g["share"] >= 0.95).sum()) for k, g in cov.groupby("fold")}, "bars_median_share": float(cov["share"].median()),
         "cells_0o_members_in": cells, "bar_rule_a": bars_by, "B_i_missing": int(cr["B_i"].isna().sum()) if len(cr) else int(len(L)),
         "revert_3d_described": rev, "excluded": EXCLUDED, "raw_files": raw, "known_at_probe": ka,
         "candidates": None if E is None else {"n": int(len(E)), "why": E["why"].value_counts().to_dict(), "F5_listed_not_frozen": int((E["why"] == F5_LISTED).sum()),
                                               "F5_cells_members_in": int(E[(E["why"] == F5_LISTED) & E["cell"] & (E["side"] == "in") & E["member_at_t0"]].shape[0])},
         "known_at": "t0 = ts_known = the adapter's run stamp (the balance read then); the registration's decision bar is the first 5m bar closing after t0 + the lag the forward probe sets; "
                     "`revert_3d` is post-t0 (described); nothing after t0 is read here"}
    (OUT / "audit.json").write_text(json.dumps(J, indent=1, default=str))
    md = [f"# cexflow — the exchange's own on-chain balance per token as a per-name event (decision CK1)",
          f"generated {J['generated']} · the frozen lists {', '.join(p.name for p in LISTS.values() if p.exists())}", "",
          f"**{len(L)} eligible jumps** (|change| ≥ {THRESH:.0%} between consecutive stamps) on {J['distinct_names']} names; the CELLS after the {COLLAPSE.days}-day collapse per name and side, by fold × side × member_at_t0:", cells_tab.to_string(), "",
          f"**The registered population (rule (a)): the MEMBERS' inflow cells** — {json.dumps(J['population_members_in'])}", "",
          "## The names (members' cells)", f"in: {json.dumps(J['top_names_members']['in'])}; the top five's share {J['top5_share_members_in']}", f"out: {json.dumps(J['top_names_members']['out'])}", "",
          "## Sizes and flags", f"|change| quantiles {json.dumps(q_change)}; |usd jump| q10 / q50 / q90 {json.dumps(q_usd)}; chains a name (median) {J['chains_n_median']}; flags {json.dumps(J['flags'])}", "",
          "## The stamp's hour (UTC) — the adapter's run", hod.to_string(), f"the gap between stamps (days) q10 / q50 / q90 {J['gap_d_q10_50_90']}", "",
          "## Bars in the window (t0 − 2 d → t0 + 8 d)", f"complete (≥ 95 %) {J['bars_complete']} of {len(L)}; by fold {json.dumps(J['bars_by_fold'])}; median share {J['bars_median_share']:.3f}", "",
          "## The cells a registration can read (0o (i): the members' inflow cells, t0 + hold inside the fold set's market AND the bars complete), by hold (days)", json.dumps(cells, default=str), "",
          f"## Rule (a) — the bar from the names' own cost rows on the t0 day: B = mean B_i, B_i = {BAR_MULT:.0f} × 2 × ({TAKER_BPS:.0f} + taker_leg)", json.dumps(bars_by), f"B_i missing {J['B_i_missing']}", "",
          "## The revert within three stamps (DESCRIBED — post-t0; the exchange's own rotations show here)", json.dumps(rev), "",
          "## Excluded by name", json.dumps(EXCLUDED), "",
          "## The raw files and the known-at probe", json.dumps(raw), json.dumps(ka, default=str)[:1500], "",
          "## Candidates not eligible", "" if E is None else E[E["why"] != "eligible"]["why"].value_counts().to_string(),
          "" if E is None else f"F5: {J['candidates']['F5_listed_not_frozen']} listed, not frozen (the members' inflow cells {J['candidates']['F5_cells_members_in']})", "",
          "## Known-at", J["known_at"]]
    (OUT / "audit.md").write_text("\n".join(md))
    return "\n".join(md)


def main(action: str, fetch_: bool = False, tags: tuple[str, ...] = ("f12",), flag: str | None = None) -> None:
    if action == "fetch":
        fetch()
    elif action == "ingest":
        ingest()
    elif action == "events":
        events()
    elif action == "bars":
        bars(fetch=fetch_, fetch_tags=tags, fetch_flag=flag)
    elif action == "knownat":
        knownat()
    elif action == "audit":
        print(audit())
    else:
        sys.exit(f"cexflow: unknown action {action}")
