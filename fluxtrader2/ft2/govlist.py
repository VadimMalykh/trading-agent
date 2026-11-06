"""Decision CG1 (2026-11-06; PLAN P8 decision CG) — a protocol's own GOVERNANCE VOTE (Snapshot) as a per-name EVENT: the source audit,
`ft2 govlist spaces|proposals|events|bars|audit`. Nothing here joins a bar AFTER a vote's end to anything; no price is read; no fold is read
for a label; nothing is registered.

source     Snapshot's hub (hub.snapshot.org/graphql; free, keyless; reachable from the work VM). `spaces` pages the `ranking` query (the
           spaces by activity, 20 a page at any skip — probed 2026-11-06; `api/explore` answers an empty dict and `spaces(orderBy …)`
           ignores the order) to RANK_MAX and saves them (data/raw/external/snapshot/ranking_<stamp>.json); the join to our bases is by the
           space's voting-token SYMBOL (`um_first_month.csv`'s bases), one space a base (the busiest by proposalsCount), spaces with fewer
           than MIN_PROPOSALS out, EXCLUDED spaces out by id with their reason (the hand check of the top spaces: a symbol match is not a
           protocol match — `fabien.eth` is not Ethereum's governance). A DAO whose space symbol is a derived token (VP, veCRV, stkAAVE) is
           NOT reached by the join and is counted beside, not chased. `proposals` fetches every proposal of the kept spaces (the `created_gt`
           cursor, 1,000 a call) and saves them (…/snapshot/proposals_<stamp>.json).
event      t0 = the vote's END (`end`, a unix second the proposal carries from its creation — the scheduled hour of the event); KNOWN-AT =
           `created` (`ts_known`; the proposal's IPFS stamp, immutable); the vote's `start`, its duration, the voters (`votes`), the weight
           (`scores_total`), the WINNING choice (the largest score) and whether it reads as a pass (`passed`: for / yes / approve …), the
           title's KIND by regex (gauge, grant, parameter, treasury, listing, election, other — described), `flagged` (Snapshot's own flag).
           Only CLOSED proposals; the perpetual by `upgrades.contract_for` in the end's month, its first bar and age by the same rule.
eligible   the perpetual ≥ PERP_AGE old at the end AND the end inside F1 … F4. F5's votes are listed and NOT frozen. The 7-day collapse is
           written as FLAGS on the rows, not as a drop: `cell_all` (the first vote of the name in a 7-day window over every eligible vote)
           and `cell_big` (the same over the votes with ≥ VOTES_MIN voters) — decision CH picks the registered population from the flags.
lists      output/govlist/events.csv (every closed proposal with its `why`), output/govlist/govvotes_f12.csv / _f34.csv (the eligible),
           frozen by hand as ft2/govvotes_f12.csv / _f34.csv and committed BEFORE any bar after an end is read for anything; govvotes_f5.csv
           the F5 rows, listed.
bars       per frozen event the count of the name's 5m bars over [min(created, end − 2 d), end + 8 d) in `candles_5m_archive` — COUNTS;
           with --fetch the F1+F2 events' missing (name, month) files are fetched (R28's route) and the slice re-ingested whole under
           krlist's fingerprint (a name that changes is a void).
audit      the counts by fold × cut × member, the kinds, the winners, the top names' share, the end's hour and weekday, the lead, the ages,
           the bars, the 0o (i) cells, rule (a)'s B_i on the end day from the names' own cost rows, the flagged count, the unreached
           DAOs → output/govlist/audit.md / .json, DATA.md `gov_votes`.
"""
from __future__ import annotations

import glob
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, folds
from . import coinbase as cb
from . import upgrades as up

SNAP = "https://hub.snapshot.org/graphql"
SNAP_DIR = data.RAW / "external" / "snapshot"
RANK_MAX = 14_000                 # the ranking's page at skip 12,000 holds spaces with ≈ 3 proposals; MIN_PROPOSALS is 5
RANK_PAGE = 20                    # the query's ceiling (first ≤ 20)
PAUSE = 0.6
MIN_PROPOSALS = 5
VOTES_MIN = 200                   # `cell_big`: the votes with at least this many voters
PERP_AGE = pd.Timedelta(days=30)
COLLAPSE = pd.Timedelta(days=7)
WINDOW = (pd.Timedelta(days=-2), pd.Timedelta(days=8))
BAR = pd.Timedelta("5min")
DAY = pd.Timedelta(days=1)
FROZEN_FOLDS = ("F1", "F2", "F3", "F4")
TAGS = {"F1": "f12", "F2": "f12", "F3": "f34", "F4": "f34"}
F5_LISTED = "outside F1 … F4 (F5: listed, not frozen)"
OUT = Path("output/govlist")
LISTS = {"f12": Path(__file__).with_name("govvotes_f12.csv"), "f34": Path(__file__).with_name("govvotes_f34.csv"), "f5": Path(__file__).with_name("govvotes_f5.csv")}
TAKER_BPS, NOTIONAL, BAR_MULT = 5.0, 10_000, 2.0     # krevent's B_i = BAR_MULT × 2 legs × (fee + taker_leg)
UA = {"User-Agent": "Mozilla/5.0 (ft2-govlist/1)", "Accept": "application/json", "Content-Type": "application/json"}
# the hand check of the symbol join (decision CG1's rule, applied 2026-11-06 on the 207 busiest-a-base spaces and the 90 verified ones among
# them): a space is the base's protocol if Snapshot VERIFIED it and its name is the protocol's (the verified mismatches EXCLUDED by id below),
# or if it is unverified and hand-KEPT by name; every other unverified space is out ("unverified, not hand-kept" — test spaces, personal
# spaces and NFT clubs carry our tickers as symbols: "Commonwealth Test Space" for DYDX, "cocos" for MATIC, "dcl.governance.test" for MANA).
EXCLUDED: dict[str, str] = {
    "fabien.eth": "a person's space, not Ethereum's governance", "dehedge.eth": "deHedge, not Degen", "hyperlockfi.eth": "Hyperlock, not Hyperlane",
    "g-dao.eth": "not the G token's protocol", "myirafund.eth": "myIRA.fund, not SelfKey", "monetadao.eth": "Moneta DAO, not Monad",
    "goatsino.eth": "GOATsino, not Goatseus Maximus", "zechubdao.eth": "ZecHub (a community wiki), not Zcash's governance", "ffdao.eth": "forefront, not Falcon Finance",
    "arbibots.eth": "BOTDAO (an NFT club), not the BOT token's protocol", "toshibase.eth": "a meme club, not shown to be Toshi's", "takefoundation.eth": "not shown to be the TAKE token's protocol",
    "spacetokendao.eth": "Space Token, not Space and Time", "raving.eth": "Rave Names, not the RAVE perpetual's protocol",
    "astardegens.eth": "Astar Degens, not Degen", "otterclam.eth": "OtterClam, not Polygon", "lightofhope.eth": "not SafeDAO", "thestandardio.eth": "The Standard, not the TST meme token",
    "bitteprotocol.eth": "a test DAO, not USDC", "justaveryintelligentsystem.eth": "not USDC",
}
KEPT_UNVERIFIED: dict[str, str] = {
    "agld-dao.eth": "Adventure Gold", "ainetwork.eth": "AI Network", "bzx.eth": "bZx", "celernetwork.eth": "Celer Network", "dego": "dego.finance",
    "fantomecosystem.eth": "Fantom", "fraxfinancegovernance.eth": "Frax Finance", "iotex.eth": "IoTeX Network", "kernelgov.eth": "KernelDAO", "loopringdao.eth": "Loopring",
    "mantra-dao": "MANTRA DAO", "orbs-network.eth": "Orbs", "rei-network.eth": "REI Network", "stormxio.eth": "StormX", "unfi.eth": "Unifi Protocol DAO",
    "vidt-dao.eth": "VIDT DAO", "yearn": "yearn.finance (archive)", "dfi": "DFI.money", "tutellusdao.eth": "Tutellus DAO", "loka.eth": "LOKA DAO (League of Kingdoms)",
    "myshell-dao.eth": "MyShell",
}
KIND_RE = [("gauge", re.compile(r"gauge|emission|incentive|bribe|weight|rewards? (program|distribution)|liquidity mining", re.I)),
           ("grant", re.compile(r"grant|fund(ing)? request|budget|sponsor|bounty|compensation|salary|contributor", re.I)),
           ("treasury", re.compile(r"treasury|buyback|buy ?back|burn|revenue|fee switch|fees? (to|for)|diversif|reserve", re.I)),
           ("listing", re.compile(r"\blist|onboard|add .* (as|to) (collateral|market|asset)|new (market|asset|pool|chain)|deploy", re.I)),
           ("parameter", re.compile(r"param|rate|ltv|collateral|cap\b|limit|risk|oracle|interest|borrow|supply cap|liquidation|threshold", re.I)),
           ("election", re.compile(r"elect|council|committee|delegate|steward|multisig|signer|guardian|ratif", re.I))]
PASS_RE = re.compile(r"^\s*(for|yes|yae|yay|aye|approve|accept|agree|support|in favou?r|pass|✅|👍)", re.I)
LIST_COLS = ["symbol", "base", "mult", "t0", "ts_known", "release", "code", "fold", "block", "perp_first", "perp_first_source", "perp_age_days",
             "member_at_t0", "lead_d", "space", "start", "duration_d", "votes", "scores_total", "n_choices", "winner", "passed", "kind", "flagged",
             "repeat_n", "cell_all", "cell_big", "title"]


# ---- the hub ---------------------------------------------------------------------------------------------------------------------
def _gql(query: str, tries: int = 5, timeout: int = 90) -> dict:
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(SNAP, data=json.dumps({"query": query}).encode(), headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read().decode())
            if d.get("errors"):
                raise RuntimeError(str(d["errors"])[:200])
            return d.get("data") or {}
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(5 + 20 * i)
    raise RuntimeError(f"snapshot: {query[:60]}…: {err!r}")


def fetch_ranking() -> Path:
    """Every space of the `ranking` query to RANK_MAX, saved as ranking_<YYYYMMDD>.json (id, name, symbol, verified, proposalsCount, followersCount)."""
    rows = []
    for skip in range(0, RANK_MAX, RANK_PAGE):
        page = (_gql('{ ranking(first: %d, skip: %d, where: {}) { items { id name symbol verified proposalsCount followersCount } } }' % (RANK_PAGE, skip)).get("ranking") or {}).get("items") or []
        if not page:
            break
        rows += page
        if skip % 2000 == 0:
            print(f"ranking skip {skip}: {page[0]['id']} {page[0].get('proposalsCount')}", flush=True)
        time.sleep(PAUSE)
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    dest = SNAP_DIR / f"ranking_{pd.Timestamp.now('UTC'):%Y%m%d}.json"
    dest.write_text(json.dumps(rows))
    return dest


def _latest(pattern: str) -> Path:
    files = sorted(glob.glob(str(SNAP_DIR / pattern)))
    if not files:
        raise SystemExit(f"govlist: no {pattern} under {SNAP_DIR} — run the fetch on the VM")
    return Path(files[-1])


def spaces(fetch: bool = False, write: bool = True) -> pd.DataFrame:
    """The spaces joined to our bases by symbol: ≥ MIN_PROPOSALS, verified and not EXCLUDED or hand-KEPT, one a base (the busiest of those).
    The others with a symbol of ours (the smaller spaces of a base, the excluded, the unverified) go beside as spaces_other.csv with their
    reason; the DAOs the join cannot reach are the audit's count."""
    if fetch:
        print(f"saved {fetch_ranking()}", flush=True)
    R = pd.DataFrame(json.load(open(_latest("ranking_*.json"))))
    R = R.drop_duplicates("id")
    R["symbol"] = R["symbol"].fillna("").astype(str).str.upper().str.strip()
    R["proposals"] = R["proposalsCount"].fillna(0).astype(int)
    R["followers"] = R["followersCount"].fillna(0).astype(int)
    fm = up.contracts()
    bases = set(fm["base"])
    S = R[R["symbol"].isin(bases) & (R["proposals"] >= MIN_PROPOSALS)].copy()
    S["verified"] = S["verified"].fillna(False).astype(bool)
    S["excluded"] = S["id"].map(EXCLUDED)
    S.loc[~S["verified"] & ~S["id"].isin(KEPT_UNVERIFIED) & S["excluded"].isna(), "excluded"] = "unverified, not hand-kept"
    S = S.sort_values(["symbol", "proposals"], ascending=[True, False])
    kept = S[S["excluded"].isna()].drop_duplicates("symbol", keep="first")
    other = S[~S["id"].isin(kept["id"])]
    kept = kept.rename(columns={"symbol": "base"})[["id", "name", "base", "verified", "proposals", "followers"]].reset_index(drop=True)
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        kept.to_csv(OUT / "spaces.csv", index=False)
        other.rename(columns={"symbol": "base"})[["id", "name", "base", "verified", "proposals", "followers", "excluded"]].to_csv(OUT / "spaces_other.csv", index=False)
        print(f"{len(R)} spaces in the ranking; with a symbol of ours and ≥ {MIN_PROPOSALS} proposals {len(S)} ({S['symbol'].nunique()} bases); excluded by the hand check "
              f"{int(S['excluded'].notna().sum())}; kept one a base {len(kept)} (verified {int(kept['verified'].fillna(False).astype(bool).sum())}, proposals {int(kept['proposals'].sum())}); "
              f"the smaller spaces of the same bases beside {len(other)}", flush=True)
    return kept


def fetch_proposals(space_ids: list[str], batch: int = 25) -> Path:
    """Every proposal of the spaces (the `created_gt` cursor, 1,000 a call), saved as proposals_<YYYYMMDD>.json."""
    rows = []
    for i in range(0, len(space_ids), batch):
        ids, cur = space_ids[i:i + batch], 0
        while True:
            page = _gql('{ proposals(first: 1000, where: {space_in: %s, created_gt: %d}, orderBy: "created", orderDirection: asc) '
                        '{ id created start end votes scores_total scores choices state flagged type title space { id } } }' % (json.dumps(ids), cur)).get("proposals") or []
            if not page:
                break
            rows += page
            cur = max(q["created"] for q in page)
            time.sleep(PAUSE * 2)
            if len(page) < 1000:
                break
        print(f"proposals: {len(rows)} after {min(i + batch, len(space_ids))} of {len(space_ids)} spaces", flush=True)
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    dest = SNAP_DIR / f"proposals_{pd.Timestamp.now('UTC'):%Y%m%d}.json"
    dest.write_text(json.dumps(rows))
    return dest


def proposals(fetch: bool = False) -> pd.DataFrame:
    """The latest proposals file on disk as one row a proposal (the kept spaces only)."""
    S = spaces(fetch=False, write=False)
    if fetch:
        print(f"saved {fetch_proposals(list(S['id']))}", flush=True)
    P = pd.DataFrame(json.load(open(_latest("proposals_*.json"))))
    if not len(P):
        return P
    P["space"] = P["space"].map(lambda s: s["id"] if isinstance(s, dict) else s)
    P = P[P["space"].isin(set(S["id"]))].drop_duplicates("id").copy()
    P["base"] = P["space"].map(S.set_index("id")["base"])
    for c in ("created", "start", "end"):
        P[c] = pd.to_datetime(P[c].astype("int64"), unit="s", utc=True)
    P["votes"] = P["votes"].fillna(0).astype(int)
    P["scores_total"] = P["scores_total"].fillna(0.0).astype(float)
    P["flagged"] = P["flagged"].fillna(False).astype(bool) if "flagged" in P else False
    return P


# ---- the winner and the kind ----------------------------------------------------------------------------------------------------
def winner_of(choices, scores) -> tuple[str, bool | None, int]:
    """(the winning choice's label, whether it reads as a pass, the number of choices); a vote without scores → ('', None, n)."""
    ch = list(choices) if isinstance(choices, (list, tuple)) else []
    sc = list(scores) if isinstance(scores, (list, tuple)) else []
    if not ch or not sc or len(sc) != len(ch) or not any(np.isfinite(float(s or 0)) and float(s or 0) > 0 for s in sc):
        return "", None, len(ch)
    w = int(np.argmax([float(s or 0) for s in sc]))
    label = str(ch[w])
    return label, bool(PASS_RE.search(label)), len(ch)


def kind_of(title: str) -> str:
    for k, rx in KIND_RE:
        if rx.search(title or ""):
            return k
    return "other"


# ---- the events ---------------------------------------------------------------------------------------------------------------
def events(write: bool = True) -> pd.DataFrame:
    """Every closed proposal of the kept spaces with its flags and `why`; the eligible ones written as the lists to freeze."""
    P = proposals(fetch=False)
    fm = up.contracts()
    P["symbol"] = [up.contract_for(fm, b, e) for b, e in zip(P["base"], P["end"])]
    D = P[P["symbol"].notna()].copy()
    syms = sorted(set(D["symbol"]))
    pf = up.perp_first(syms, fm).set_index("symbol")
    M = up.member_symbols()
    D["mult"] = D["symbol"].map(cb.mult_of)
    D["t0"] = D["end"]
    D["ts_known"] = D["created"]
    D["release"] = D["created"]
    D["code"] = D["id"]
    D["perp_first"] = D["symbol"].map(pf["perp_first"])
    D["perp_first_source"] = D["symbol"].map(pf["perp_first_source"])
    D["perp_age_days"] = (D["t0"] - D["perp_first"]).dt.days
    D["lead_d"] = (D["t0"] - D["ts_known"]) / DAY
    D["duration_d"] = (D["end"] - D["start"]) / DAY
    wk = [winner_of(c, s) for c, s in zip(D["choices"], D["scores"])]
    D["winner"] = [w[0] for w in wk]
    D["passed"] = [w[1] for w in wk]
    D["n_choices"] = [w[2] for w in wk]
    D["kind"] = D["title"].map(kind_of)
    D["fold"] = D["t0"].map(lambda t: up.fold_of(t) if pd.notna(t) else None)
    D["block"] = [up.block_at(M, t) if pd.notna(t) else pd.NaT for t in D["t0"]]
    D["member_at_t0"] = [up.member_at(M, s, t) if pd.notna(t) else False for s, t in zip(D["symbol"], D["t0"])]
    D = D.sort_values(["t0", "created", "id"]).reset_index(drop=True)
    D["repeat_n"] = D.groupby("symbol").cumcount()
    why = []
    for r in D.itertuples():
        if r.state != "closed":
            w = "not closed (active or pending)"
        elif pd.isna(r.t0) or pd.isna(r.ts_known):
            w = "no end or no creation stamp"
        elif r.ts_known > r.t0:
            w = "created after its end (malformed)"
        elif r.perp_first_source == "none" or pd.isna(r.perp_age_days):
            w = "no perpetual first bar known"
        elif r.perp_age_days < PERP_AGE.days:
            w = f"the perpetual younger than {PERP_AGE.days} days at the end (a launch, R28's population)"
        elif r.fold not in FROZEN_FOLDS:
            w = F5_LISTED if r.fold == "F5" else "outside F1 … F4"
        else:
            w = "eligible"
        why.append(w)
    D["why"] = why
    # the 7-day collapse as flags, over the eligible and the F5-listed rows, per name in end order
    live = D["why"].isin(["eligible", F5_LISTED])
    D["cell_all"] = False
    D["cell_big"] = False
    for col, mask in (("cell_all", live), ("cell_big", live & (D["votes"] >= VOTES_MIN))):
        last: dict[str, pd.Timestamp] = {}
        keep = []
        for r in D[mask].itertuples():
            k = r.symbol not in last or (r.t0 - last[r.symbol]) >= COLLAPSE
            keep.append(k)
            if k:
                last[r.symbol] = r.t0
        D.loc[mask, col] = keep
    E = D[[*LIST_COLS, "state", "why"]].reset_index(drop=True)
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        E.to_csv(OUT / "events.csv", index=False)
        el = E[E["why"] == "eligible"]
        for tag in ("f12", "f34"):
            el[el["fold"].map(TAGS) == tag][LIST_COLS].to_csv(OUT / f"govvotes_{tag}.csv", index=False)
        E[E["why"] == F5_LISTED][LIST_COLS].to_csv(OUT / "govvotes_f5.csv", index=False)
        print(summary(E), flush=True)
    return E


def summary(E: pd.DataFrame) -> str:
    el = E[E["why"] == "eligible"]
    lines = [f"{len(E)} proposals of the kept spaces with a perpetual of ours; {len(el)} eligible (closed, the perpetual ≥ {PERP_AGE.days} d old at the end, the end in F1 … F4)"]
    if len(el):
        lines.append("eligible by fold × cell flags (cell_all / cell_big):\n" + el.groupby("fold")[["cell_all", "cell_big"]].sum().to_string())
        lines.append(f"distinct names by fold set: F1+F2 {el[el['fold'].isin(['F1', 'F2'])]['symbol'].nunique()}, F3+F4 {el[el['fold'].isin(['F3', 'F4'])]['symbol'].nunique()}; "
                     f"members at the end {int(el['member_at_t0'].sum())} of {len(el)}; flagged {int(el['flagged'].sum())}; "
                     f"the lead (days) q10 / q50 / q90 {' / '.join(f'{x:.2f}' for x in el['lead_d'].quantile([.1, .5, .9]))}; kinds {el['kind'].value_counts().to_dict()}")
    lines.append(f"F5: {int((E['why'] == F5_LISTED).sum())} listed, not frozen")
    lines.append("not eligible, by reason:\n" + E[E["why"] != "eligible"]["why"].value_counts().to_string())
    return "\n".join(lines)


def frozen(tags=("f12", "f34")) -> pd.DataFrame:
    parts = []
    for tag in tags:
        p = LISTS[tag]
        if p.exists():
            d = pd.read_csv(p)
            for c in ("t0", "ts_known", "release", "block", "perp_first", "start"):
                d[c] = pd.to_datetime(d[c], utc=True, format="ISO8601")
            parts.append(d.assign(list=tag))
    if not parts:
        raise SystemExit(f"govlist: no frozen list at {list(LISTS.values())} — run `ft2 govlist events`, freeze the lists, commit")
    return pd.concat(parts, ignore_index=True)


# ---- the bars (counts) and the cost rows -----------------------------------------------------------------------------------------
def bars(fetch: bool = False, fetch_tags: tuple[str, ...] = ("f12",)) -> dict:
    """The frozen events' bars counted (`upgrades.coverage`'s window from min(created, end − 2 d) to end + 8 d); with `fetch` the (name,
    month) files missing for the events of `fetch_tags` come from the archive and the slice is re-ingested whole under krlist's fingerprint."""
    from . import archive, krlist
    L = frozen()
    OUT.mkdir(parents=True, exist_ok=True)
    cov = up.coverage(L)
    cov["list"] = L["list"].to_numpy()
    need = krlist.missing_months(cov[cov["list"].isin(fetch_tags)])
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
        rep["by_fold_after"] = {str(k): int((g["share"] >= 0.95).sum()) for k, g in cov.groupby("fold")}
        rep["missing_after"] = krlist.missing_months(cov[cov["list"].isin(fetch_tags)])
    cov.drop(columns=["months", "list"], errors="ignore").to_csv(OUT / "bars.csv", index=False)
    print(json.dumps(rep, indent=1, default=str))
    return rep


def cost_rows(L: pd.DataFrame, fallback_days: int = 7) -> pd.DataFrame:
    """Rule (a)'s B_i = BAR_MULT × 2 × (fee + the taker leg) from `costwide`'s proxy on the end's day (else the last row within `fallback_days`
    before; none → NaN, counted): the bar a registration on these names must clear, from the names' own rows."""
    from .cost import DAILY_WIDE
    cols = ["symbol", "t0", "taker_leg", "cost_day", "B_i"]
    if not Path(DAILY_WIDE).exists():
        return pd.DataFrame(columns=cols)
    w = pd.read_parquet(DAILY_WIDE)
    w["symbol"] = w["symbol"].astype(str)
    w["day"] = up._utc(w["day"]).dt.floor("D")
    imp = f"imp_{NOTIONAL}"
    if imp not in w.columns or "spread_cal_bps" not in w.columns:
        return pd.DataFrame(columns=cols)
    w["leg"] = w["spread_cal_bps"] / 2 + w[imp]
    k = w.set_index(["symbol", "day"])["leg"].sort_index()
    out = []
    for r in L.itertuples(index=False):
        d0 = r.t0.floor("D")
        leg, used = np.nan, pd.NaT
        if r.symbol in k.index.get_level_values(0):
            s = k.loc[r.symbol]
            s = s[(s.index <= d0) & (s.index >= d0 - pd.Timedelta(days=fallback_days))].dropna()
            if len(s):
                leg, used = float(s.iloc[-1]), s.index[-1]
        out.append({"symbol": r.symbol, "t0": r.t0, "taker_leg": leg, "cost_day": used, "B_i": BAR_MULT * 2.0 * (TAKER_BPS + leg) if np.isfinite(leg) else np.nan})
    return pd.DataFrame(out)


def unreached(write: bool = True) -> pd.DataFrame:
    """The DAOs the symbol join cannot reach: the ranking's spaces with ≥ MIN_PROPOSALS whose symbol is NOT a base of ours but is a base
    with a derived-token prefix (veCRV, stkAAVE, xSUSHI) or whose name contains a base's name of ≥ 4 letters. Counted beside, not chased."""
    R = pd.DataFrame(json.load(open(_latest("ranking_*.json")))).drop_duplicates("id")
    R["symbol"] = R["symbol"].fillna("").astype(str).str.upper().str.strip()
    R["proposals"] = R["proposalsCount"].fillna(0).astype(int)
    allb = set(up.contracts()["base"])
    bases = sorted({b for b in allb if len(b) >= 4}, key=len, reverse=True)
    R = R[(R["proposals"] >= MIN_PROPOSALS) & ~R["symbol"].isin(allb)]
    rows = []
    for r in R.itertuples():
        name = str(r.name or "").upper().replace(" ", "")
        stripped = re.sub(r"^(VE|STK|ST|GOV|X|G|S|W|E|V)(?=[A-Z0-9]{2,})", "", r.symbol)       # veCRV → CRV, stkAAVE → AAVE, xSUSHI → SUSHI
        hit = stripped if stripped in allb and stripped != r.symbol else next((b for b in bases if b in name), None)
        if hit:
            rows.append({"id": r.id, "name": r.name, "symbol": r.symbol, "base_in_name": hit, "proposals": r.proposals})
    U = pd.DataFrame(rows, columns=["id", "name", "symbol", "base_in_name", "proposals"]).sort_values("proposals", ascending=False)
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        U.to_csv(OUT / "spaces_unreached.csv", index=False)
    return U


# ---- the audit ------------------------------------------------------------------------------------------------------------------
def audit(today: pd.Timestamp | None = None) -> str:
    today = today or pd.Timestamp.now("UTC")
    L = frozen()
    E = pd.read_csv(OUT / "events.csv") if (OUT / "events.csv").exists() else None
    cov = up.coverage(L)
    cr = cost_rows(L)
    OUT.mkdir(parents=True, exist_ok=True)
    cr.to_csv(OUT / "costs.csv", index=False)
    try:
        U = unreached()
    except SystemExit:
        U = pd.DataFrame(columns=["id", "name", "symbol", "base_in_name", "proposals"])
    big = L[L["votes"] >= VOTES_MIN]
    by_fc = L.groupby("fold")[["cell_all", "cell_big"]].sum()
    by_fm = L[L["cell_all"]].groupby(["fold", "member_at_t0"]).size().unstack(fill_value=0)
    by_fm_big = L[L["cell_big"]].groupby(["fold", "member_at_t0"]).size().unstack(fill_value=0)
    kinds = L[L["cell_all"]].groupby(["kind"]).size().sort_values(ascending=False)
    kinds_big = L[L["cell_big"]].groupby(["kind"]).size().sort_values(ascending=False)
    names_all = L[L["cell_all"]].groupby("symbol").size().sort_values(ascending=False)
    names_big = L[L["cell_big"]].groupby("symbol").size().sort_values(ascending=False)
    hod = pd.DatetimeIndex(L["t0"]).hour.value_counts().sort_index()
    dow = pd.DatetimeIndex(L["t0"]).dayofweek.value_counts().sort_index()
    q_lead = L["lead_d"].quantile([0.1, 0.25, 0.5, 0.75, 0.9]).round(2).to_dict()
    q_dur = L["duration_d"].quantile([0.1, 0.5, 0.9]).round(2).to_dict()
    q_age = L["perp_age_days"].quantile([0.1, 0.5, 0.9]).round(0).to_dict()
    cells = {h: up.eligible_cells(L[L["cell_all"]], cov, hold=pd.Timedelta(days=h)) for h in (1, 3, 7)}
    cells_big = {h: up.eligible_cells(L[L["cell_big"]], cov, hold=pd.Timedelta(days=h)) for h in (1, 3, 7)}
    bi = cr.set_index(["symbol", "t0"])["B_i"] if len(cr) else pd.Series(dtype=float)
    bi = bi[~bi.index.duplicated()]                   # a batch ending at one second has one end day and one B_i
    def bar_of(mask):
        if not len(cr):
            return {"priced": 0, "of": int(mask.sum())}
        v = pd.Series([bi.get((s, t), np.nan) for s, t in zip(L[mask]["symbol"], L[mask]["t0"])]).dropna()
        return {"priced": int(v.size), "of": int(mask.sum()), "B": round(float(v.mean()), 1) if v.size else None, "B_i_median": round(float(v.median()), 1) if v.size else None,
                "B_i_q90": round(float(v.quantile(0.9)), 1) if v.size else None}
    bars_by = {f"{tag} {cut}": bar_of((L["list"] == tag) & L[cut]) for tag in sorted(set(L["list"])) for cut in ("cell_all", "cell_big")}
    passed = L[L["cell_all"]]["passed"]
    J = {"generated": f"{today:%Y-%m-%d %H:%M} UTC", "events": int(len(L)), "distinct_names": int(L["symbol"].nunique()), "spaces": int(L["space"].nunique()),
         "cells_by_fold": {str(k): {c: int(v) for c, v in r.items()} for k, r in by_fc.iterrows()},
         "cells_all_by_fold_member": {str(k): {str(c): int(v) for c, v in r.items()} for k, r in by_fm.iterrows()},
         "cells_big_by_fold_member": {str(k): {str(c): int(v) for c, v in r.items()} for k, r in by_fm_big.iterrows()},
         "names_by_fold_set": {tag: {"all": int(g[g["cell_all"]]["symbol"].nunique()), "big": int(g[g["cell_big"]]["symbol"].nunique())} for tag, g in L.groupby("list")},
         "top_names_all": {k: int(v) for k, v in names_all.head(10).items()}, "top5_share_all": round(float(names_all.head(5).sum() / max(1, names_all.sum())), 3),
         "top_names_big": {k: int(v) for k, v in names_big.head(10).items()}, "top5_share_big": round(float(names_big.head(5).sum() / max(1, names_big.sum())), 3),
         "kinds_all": {k: int(v) for k, v in kinds.items()}, "kinds_big": {k: int(v) for k, v in kinds_big.items()},
         "passed_share_all": {"passed": int((passed == True).sum()), "failed": int((passed == False).sum()), "unparsed": int(passed.isna().sum())},  # noqa: E712
         "votes_q10_50_90": L["votes"].quantile([0.1, 0.5, 0.9]).round(0).tolist(), "big_rows": int(len(big)), "flagged": int(L["flagged"].sum()),
         "lead_d_quantiles": q_lead, "duration_d_quantiles": q_dur, "perp_age_days_q10_50_90": q_age, "perp_first_source": L["perp_first_source"].value_counts().to_dict(),
         "t0_hour_utc": {int(k): int(v) for k, v in hod.items()}, "t0_on_the_hour": int((pd.DatetimeIndex(L["t0"]).minute == 0).sum()), "t0_dow": {int(k): int(v) for k, v in dow.items()},
         "bars_complete": int((cov["share"] >= 0.95).sum()), "bars_by_fold": {str(k): int((g["share"] >= 0.95).sum()) for k, g in cov.groupby("fold")}, "bars_median_share": float(cov["share"].median()),
         "cells_0o_all": cells, "cells_0o_big": cells_big, "bar_rule_a": bars_by, "B_i_missing": int(cr["B_i"].isna().sum()) if len(cr) else int(len(L)),
         "unreached_daos": {"n": int(len(U)), "top": U.head(15).to_dict("records")},
         "candidates": None if E is None else {"n": int(len(E)), "why": E["why"].value_counts().to_dict(), "F5_listed_not_frozen": int((E["why"] == F5_LISTED).sum()),
                                               "F5_cells": {"all": int(E[(E["why"] == F5_LISTED)]["cell_all"].sum()), "big": int(E[(E["why"] == F5_LISTED)]["cell_big"].sum())}},
         "known_at": "the proposal's `created` (ts_known): the END is fixed then and public; t0 = the end; the decision bar of a registration is the first 5m bar that closes after t0; the tally is public through the vote (the mechanism's weakness, decision CG (cii)); nothing after t0 is read here"}
    (OUT / "audit.json").write_text(json.dumps(J, indent=1, default=str))
    md = [f"# govlist — a protocol's own governance vote (Snapshot) as a per-name event (decision CG1)",
          f"generated {J['generated']} · the frozen lists {', '.join(p.name for p in LISTS.values() if p.exists())}", "",
          f"**{len(L)} eligible votes** on {J['distinct_names']} names from {J['spaces']} spaces (closed, the perpetual ≥ {PERP_AGE.days} d old at the end, the end in F1 … F4); "
          f"the cells after the {COLLAPSE.days}-day collapse by fold (all / ≥ {VOTES_MIN} voters):", by_fc.to_string(), "",
          f"names by fold set {json.dumps(J['names_by_fold_set'])}; flagged {J['flagged']}; the perpetual's age p10 / p50 / p90 {q_age.get(0.1)} / {q_age.get(0.5)} / {q_age.get(0.9)} days.", "",
          "## cell_all by fold × member_at_t0", by_fm.to_string(), "", f"## cell_big (≥ {VOTES_MIN} voters) by fold × member_at_t0", by_fm_big.to_string(), "",
          "## The names (cell_all)", json.dumps(J["top_names_all"]) + f"; the top five's share {J['top5_share_all']}", "## The names (cell_big)", json.dumps(J["top_names_big"]) + f"; the top five's share {J['top5_share_big']}", "",
          "## The kinds (the title's regex; described)", f"all: {json.dumps(J['kinds_all'])}", f"big: {json.dumps(J['kinds_big'])}", "",
          "## The winner (cell_all)", json.dumps(J["passed_share_all"]), f"voters q10 / q50 / q90 {J['votes_q10_50_90']}", "",
          "## The lead — end − created, days (quantiles); the duration — end − start", f"{json.dumps(q_lead)}; duration {json.dumps(q_dur)}", "",
          "## The hour of day of the end (UTC)", hod.to_string(), f"on the hour exactly {J['t0_on_the_hour']} of {len(L)}", "", "## The day of week of the end (0 = Monday)", dow.to_string(), "",
          "## Bars in the window (min(created, end − 2 d) → end + 8 d)", f"complete (≥ 95 %) {J['bars_complete']} of {len(L)}; by fold {json.dumps(J['bars_by_fold'])}; median share {J['bars_median_share']:.3f}", "",
          "## The cells a registration can read (0o (i): t0 + hold inside the fold set's market AND the bars complete), by hold (days)", "all: " + json.dumps(cells, default=str), "big: " + json.dumps(cells_big, default=str), "",
          f"## Rule (a) — the bar from the names' own cost rows on the end day: B = mean B_i, B_i = {BAR_MULT:.0f} × 2 × ({TAKER_BPS:.0f} + taker_leg)", json.dumps(bars_by), f"B_i missing {J['B_i_missing']}", "",
          "## The DAOs the symbol join cannot reach (a derived-token symbol; counted, not chased)", f"{J['unreached_daos']['n']}: " + "; ".join(f"{r['name']} ({r['symbol']}, {r['base_in_name']}, {r['proposals']})" for r in J["unreached_daos"]["top"]), "",
          "## Candidates not eligible", "" if E is None else E[E["why"] != "eligible"]["why"].value_counts().to_string(),
          "" if E is None else f"F5: {J['candidates']['F5_listed_not_frozen']} listed, not frozen (cells all / big {J['candidates']['F5_cells']})", "",
          "## Known-at", J["known_at"]]
    (OUT / "audit.md").write_text("\n".join(md))
    return "\n".join(md)


def main(action: str, fetch: bool = False, tags: tuple[str, ...] = ("f12",)) -> None:
    if action == "spaces":
        spaces(fetch=fetch)
    elif action == "proposals":
        P = proposals(fetch=fetch)
        print(f"{len(P)} proposals on {P['base'].nunique() if len(P) else 0} bases; closed {int((P['state'] == 'closed').sum()) if len(P) else 0}; flagged {int(P['flagged'].sum()) if len(P) else 0}")
    elif action == "events":
        events()
    elif action == "bars":
        bars(fetch=fetch, fetch_tags=tags)
    elif action == "audit":
        print(audit())
    else:
        sys.exit(f"govlist: unknown action {action}")
