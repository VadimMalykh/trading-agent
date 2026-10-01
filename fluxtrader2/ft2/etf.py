"""P8 (B3′, PLAN §9 #7) — the US spot-ETF net flows as a data source: `ft2 etf fetch|ingest|inventory`.

source     Farside Investors' tables (farside.co.uk, free, keyless, an HTML page): one row a US trading day, one column a
           fund, US$ millions, negatives in parentheses, "-" where a fund did not exist, a blank row for the day in
           progress. BTC from 2024-01-11 (the funds' first day), ETH from 2024-07-23. US market holidays are rows of zeros
           until 2025-06 and absent after. The all-data page is the final table; the live page (`/btc/`) fills during the US
           evening as the funds report.
raw        data/raw/external/farside/<asset>_all_<YYYYMMDD>.html — a dated copy each fetch, so a later revision of the
           history can be seen; data/raw/external/farside/wayback/<timestamp>.html — Wayback Machine snapshots of the live
           page, the inventory's known-at measurement.
parquet    data/etf_flows.parquet: (asset, day, fund) → flow_musd, with fund "Total"; a US holiday row (every fund blank, the
           total 0.0; the ETH table also carries BTC's calendar) is kept and flagged `holiday`; the day in progress (the last
           row, every fund blank) is dropped.
known-at   a day's flow is not known at the US close: `inventory` reads every Wayback snapshot of the live page and, per UTC
           hour of the snapshot, says how often the last trading day's row was already there and equal to the final table.
           That measured hour, not the page's claim, is what a registration may use.
"""
from __future__ import annotations

import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from . import data

ASSETS = ("BTC", "ETH")
ALL = {"BTC": "https://farside.co.uk/bitcoin-etf-flow-all-data/", "ETH": "https://farside.co.uk/ethereum-etf-flow-all-data/"}
LIVE = {"BTC": "https://farside.co.uk/btc/", "ETH": "https://farside.co.uk/eth/"}
RAW = data.RAW / "external" / "farside"
WAYBACK = RAW / "wayback"
OUT = data.PROC / "etf_flows.parquet"
REPORT = Path("output/etf_inventory.md")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
CDX = "http://web.archive.org/cdx/search/cdx?url=farside.co.uk/btc/&output=json&fl=timestamp,statuscode&filter=statuscode:200&from=2024&collapse=timestamp:10"
SNAP = "http://web.archive.org/web/{ts}id_/https://farside.co.uk/btc/"
TOL = 0.15                             # US$m: a live total equal to the final within this is "final"
DATE_RE = re.compile(r"\d{1,2} \w{3} \d{4}")


def _get(u: str, timeout: int = 60, retries: int = 4) -> bytes:
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            time.sleep(45 * (attempt + 1) if e.code == 429 else 3 * (attempt + 1))      # the Wayback Machine rate-limits: wait it out
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{u}: {last!r}")


def _num(c: str) -> float:
    if c in ("-", ""):
        return np.nan
    s = c.replace(",", "").replace("*", "")
    v = float(s.strip("()"))
    return -v if s.startswith("(") else v


def parse(body: bytes) -> pd.DataFrame:
    """Farside's `table.etf` → wide frame (day × funds, "Total" last), US$m. Rows that are not a date (Seed, Total, Average …)
    are left out; a trailing row with every fund blank (the day in progress) is dropped. Raises when the page is not the
    table it should be."""
    text = body.decode("utf-8", "replace")
    tabs = re.findall(r'<table class="etf">(.*?)</table>', text, re.S)
    if not tabs:
        raise ValueError("no table.etf on the page")
    t = tabs[0]
    heads = [html.unescape(re.sub(r"<[^>]+>|&nbsp;", "", h)).strip() for h in re.findall(r"<th[^>]*>(.*?)</th>", t, re.S)]
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S):
        cells = [html.unescape(re.sub(r"<[^>]+>|&nbsp;", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if cells and DATE_RE.fullmatch(cells[0]):
            rows.append(cells)
    if not rows:
        raise ValueError("no dated row in the table")
    width = len(rows[0])
    if any(len(r) != width for r in rows):
        raise ValueError("rows of different widths")
    tickers = list(dict.fromkeys(h for h in heads if re.fullmatch(r"[A-Z]{3,5}", h)))    # the funds, in the header's order; "Total" and "Fee" are not tickers
    funds = [*tickers, "Total"]                                    # a data row is the date, the funds, the total last (the sum check below holds it to that)
    if len(funds) != width - 1:
        raise ValueError(f"header {funds} against rows of {width} cells")
    df = pd.DataFrame([[pd.Timestamp(pd.to_datetime(r[0], format="%d %b %Y"), tz="UTC")] + [_num(c) for c in r[1:]] for r in rows], columns=["day", *funds])
    df = df.sort_values("day").reset_index(drop=True)
    if df["day"].duplicated().any():
        raise ValueError("a day twice")
    blank = df[funds[:-1]].isna().all(axis=1)                     # every fund "-": a US market holiday — or, as the last row, the day in progress
    if blank.iloc[-1]:
        df = df.iloc[:-1].reset_index(drop=True)
    if not df["Total"].notna().all():
        raise ValueError("a row without a total")
    s = (df[funds[:-1]].fillna(0.0).sum(axis=1) - df["Total"]).abs()
    if (s > TOL).any():
        raise ValueError(f"funds do not sum to the total on {int((s > TOL).sum())} rows (largest {s.max():.1f})")
    return df


def fetch(assets=ASSETS, today: pd.Timestamp | None = None) -> dict:
    RAW.mkdir(parents=True, exist_ok=True)
    stamp = (today or pd.Timestamp.now("UTC")).strftime("%Y%m%d")
    out = {}
    for a in assets:
        body = _get(ALL[a])
        df = parse(body)                                           # it parses, or it is not kept
        dest = RAW / f"{a}_all_{stamp}.html"
        dest.write_bytes(body)
        out[a] = {"file": str(dest), "days": len(df), "first": df["day"].min(), "last": df["day"].max()}
        print(f"{a}: {len(df)} days {df['day'].min():%Y-%m-%d} → {df['day'].max():%Y-%m-%d} → {dest}", flush=True)
    return out


def latest_raw(asset: str) -> Path | None:
    files = sorted(RAW.glob(f"{asset}_all_*.html"))
    return files[-1] if files else None


def ingest(assets=ASSETS) -> dict:
    """The latest raw copy of each asset → the long parquet. A row with every fund blank is a US market holiday."""
    parts = []
    for a in assets:
        f = latest_raw(a)
        if f is None:
            raise SystemExit(f"etf ingest: no raw file for {a} — run `ft2 etf fetch` first")
        df = parse(f.read_bytes())
        funds = [c for c in df.columns if c != "day"]
        hol = df[[c for c in funds if c != "Total"]].isna().all(axis=1)                      # every fund blank: a US market holiday
        long = df.melt(id_vars="day", value_vars=funds, var_name="fund", value_name="flow_musd")
        long["asset"] = a
        long["holiday"] = long["day"].map(dict(zip(df["day"], hol)))
        parts.append(long[["asset", "day", "fund", "flow_musd", "holiday"]])
    out = pd.concat(parts, ignore_index=True)
    if "BTC" in assets and "ETH" in assets:                        # the ETH table carries BTC's holiday calendar too
        hdays = set(out.loc[(out["asset"] == "BTC") & out["holiday"], "day"])
        out.loc[(out["asset"] == "ETH") & out["day"].isin(hdays), "holiday"] = True
    out["asset"] = pd.Categorical(out["asset"], categories=list(ASSETS))
    out["fund"] = out["fund"].astype(str)
    out = out.sort_values(["asset", "day", "fund"]).reset_index(drop=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT, index=False)
    r = {"slice": "etf_flows", "rows_out": len(out), "first": out["day"].min(), "last": out["day"].max(), "file": str(OUT),
         "days": {a: int(out[out["asset"] == a]["day"].nunique()) for a in assets}}
    print(f"etf_flows rows_out={len(out):,} {r['days']} {r['first']:%Y-%m-%d} .. {r['last']:%Y-%m-%d}", flush=True)
    return r


def load() -> pd.DataFrame:
    return pd.read_parquet(OUT)


def totals(asset: str = "BTC") -> pd.Series:
    """The daily total, US$m, indexed by day (UTC midnight of the US trading date); holidays left out."""
    x = load()
    x = x[(x["asset"].astype(str) == asset) & (x["fund"] == "Total") & ~x["holiday"]]
    return x.set_index("day")["flow_musd"].sort_index()


# ---- known-at: the live page as the Wayback Machine saw it --------------------------------------------------------------------
def wayback_list() -> list[str]:
    r = json.loads(_get(CDX, timeout=120))
    return [x[0] for x in r[1:]]


def wayback_fetch(stamps: list[str], hours: set[int] | None = None, pause: float = 4.0) -> dict:
    """Snapshots at the UTC hours asked for (all if None) → WAYBACK/<ts>.html; cached."""
    WAYBACK.mkdir(parents=True, exist_ok=True)
    n = {"ok": 0, "skip": 0, "err": 0}
    for ts in stamps:
        if hours is not None and int(ts[8:10]) not in hours:
            continue
        dest = WAYBACK / f"{ts}.html"
        if dest.exists():
            n["skip"] += 1
            continue
        try:
            body = _get(SNAP.format(ts=ts), timeout=90, retries=3)
            parse(body)
            dest.write_bytes(body)
            n["ok"] += 1
        except Exception as e:  # noqa: BLE001
            print(f"  err {ts}: {e!r}", file=sys.stderr, flush=True)
            n["err"] += 1
        time.sleep(pause)
    return n


def known_at(snapshots: dict[str, pd.DataFrame], final: pd.DataFrame) -> pd.DataFrame:
    """One row a snapshot: the UTC time, the last US trading day before it (the final table's last day strictly before
    the snapshot's UTC date, or that date itself once the US session of that date has closed — 21:00 UTC), whether the
    live page had that day's row, and whether its total was the final one. Pure: no network."""
    fin = final.set_index("day")["Total"]
    days = fin.index
    rows = []
    for ts, live in snapshots.items():
        at = pd.Timestamp(pd.to_datetime(ts, format="%Y%m%d%H%M%S"), tz="UTC")
        d0 = at.normalize() if at.hour >= 21 else at.normalize() - pd.Timedelta(days=1)
        before = days[days <= d0]
        if not len(before):
            continue
        d = before[-1]                                             # the last trading day whose session has closed
        lv = live.set_index("day")["Total"]
        has = d in lv.index
        tot = float(lv[d]) if has else np.nan
        rows.append({"snapshot": at, "hour_utc": at.hour, "day": d, "hours_after_close": (at - (d + pd.Timedelta(hours=21))) / pd.Timedelta("1h"), "has_row": has,
                     "live_total": tot, "final_total": float(fin[d]), "final": bool(has and abs(tot - float(fin[d])) <= TOL)})
    return pd.DataFrame(rows)


def inventory(out: Path = REPORT, wayback: bool = True, hours: set[int] | None = None) -> str:
    x = load()
    md = [f"# The US spot-ETF net flows as fetched (`ft2 etf inventory`)\n",
          f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · {OUT} · Farside Investors' all-data tables, US$ millions, one row a US trading day\n"]
    rows = []
    for a in ASSETS:
        g = x[x["asset"].astype(str) == a]
        tot = g[g["fund"] == "Total"]
        f = latest_raw(a)
        rows.append({"asset": a, "raw": f.name if f else "", "funds": g["fund"].nunique() - 1, "days": tot["day"].nunique(), "first": tot["day"].min().date(), "last": tot["day"].max().date(),
                     "holiday_rows": int(tot["holiday"].sum()), "total_mean": tot["flow_musd"].mean(), "total_sd": tot["flow_musd"].std(),
                     "share_abs_gt_300": float((tot["flow_musd"].abs() > 300).mean()), "zero_days": int((tot["flow_musd"] == 0).sum())})
    md += ["\n## Extent\n", pd.DataFrame(rows).round(2).to_markdown(index=False), "\n"]
    tb = x[(x["fund"] == "Total")].pivot(index="day", columns="asset", values="flow_musd")
    md += ["\n## Days by month\n", tb.groupby(tb.index.tz_localize(None).to_period("M")).count().to_markdown(), "\n"]
    for a in ASSETS:
        t = tb[a].dropna()
        wk = pd.bdate_range(t.index.min(), t.index.max(), tz="UTC")
        miss = wk.difference(t.index)
        hol = x[(x["asset"].astype(str) == a) & (x["fund"] == "Total") & x["holiday"]]["day"]
        md += [f"\n## {a}: the calendar\n", f"\n- weekdays without a row: {len(miss)} ({', '.join(str(d.date()) for d in miss)})",
               f"\n- rows flagged holiday (every fund blank; the ETH table carries BTC's calendar too): {len(hol)} ({', '.join(str(d.date()) for d in hol)})",
               f"\n- other days with a zero total: {', '.join(str(d.date()) for d in t[(t == 0) & ~t.index.isin(hol)].index) or 'none'}\n"]
    both = tb.dropna()
    if len(both) > 50:
        md += [f"\n## BTC against ETH (described)\n", f"\n{len(both)} common days; correlation of the daily totals {both['BTC'].corr(both['ETH']):.2f}; "
               f"of their signs {np.sign(both['BTC']).corr(np.sign(both['ETH'])):.2f}.\n"]
    if wayback:
        stamps = wayback_list()
        n = wayback_fetch(stamps, hours)
        snaps = {}
        for f in sorted(WAYBACK.glob("*.html")):
            try:
                snaps[f.stem] = parse(f.read_bytes())
            except ValueError:
                continue
        final = parse(latest_raw("BTC").read_bytes())
        k = known_at(snaps, final)
        k.to_csv(out.with_name("etf_known_at.csv"), index=False)
        by = k.groupby("hour_utc").agg(snapshots=("final", "size"), has_row=("has_row", "mean"), final=("final", "mean"))
        bya = k.assign(h=np.floor(k["hours_after_close"]).clip(0, 30).astype(int)).groupby("h").agg(snapshots=("final", "size"), final=("final", "mean"))
        md += [f"\n## Known-at: the live page as the Wayback Machine saw it ({len(stamps)} snapshots listed, {len(snaps)} read; fetched {n})\n",
               "\nFor each snapshot: the last US trading day whose session had closed (21:00 UTC), whether the live page already had that day's row, and whether "
               f"its total equalled the final table's within {TOL} US$m. By the snapshot's UTC hour:\n", by.round(2).to_markdown(), "\n",
               "\nBy whole hours after that day's 21:00 UTC close (30 = a day or more):\n", bya.round(2).to_markdown(), "\n"]
        late = k[~k["final"] & (k["hours_after_close"] >= 12)]
        md += [f"\n- snapshots 12 h or more after the close whose row was still not final: {len(late)} of {int((k['hours_after_close'] >= 12).sum())}"
               + (": " + "; ".join(f"{r.snapshot:%Y-%m-%d %H:%M} day {r.day:%Y-%m-%d} live {r.live_total} final {r.final_total}" for r in late.head(12).itertuples()) if len(late) else "") + "\n"]
    out.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(md)
    out.write_text(text)
    return text


def main(action: str, no_wayback: bool = False, hours: list[int] | None = None) -> None:
    if action == "fetch":
        fetch()
    elif action == "ingest":
        ingest()
    elif action == "inventory":
        print(inventory(wayback=not no_wayback, hours=set(hours) if hours else None))
        print(f"wrote {REPORT}")
