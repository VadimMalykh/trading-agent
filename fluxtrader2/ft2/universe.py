"""The wider universe (PLAN §9 #2, registration R10): which USDⓈ-M perpetuals beyond the collector's twelve,
chosen by one rule written before any of them was looked at.

Selection (`ft2 universe`): every symbol the public archive lists under monthly klines, quoted in USDT and not
a dated contract, ranked by its MEDIAN daily quote volume over SELECT_WINDOW — the four months before F0 — and
required to have a 1d bar on every day of that window (listed before it, not delisted inside it). The top
SELECT_N are the universe. Nothing after 2022-08-18 enters the choice, so F0, F1 … are untouched by it; the
pre-history FP carries one mild bias (a pair delisted before 2022-04 cannot be in the universe). A pair that
is delisted later simply stops having bars: the harness trades the pairs present at each bar.

The chosen list is frozen in WIDE below (written by hand from output/universe_wide.md, once) so that every
later run reads the same universe; the selection command is kept so that the choice can be reproduced.
"""
from __future__ import annotations

import io
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from . import archive

SELECT_WINDOW = (date(2022, 4, 18), date(2022, 8, 17))     # the four months before F0 (2022-08-18)
SELECT_N = 40
OUT_MD = Path("output/universe_wide.md")
EXCLUDE = {"BTCDOMUSDT", "DEFIUSDT", "BTCSTUSDT", "USDCUSDT", "BTCUSDT_", "FOOTBALLUSDT", "BLUEBIRDUSDT"}   # indices / stables: not a pair in the sense used here

# Frozen 2026-09-22 05:19 UTC from output/universe_wide.md (854 candidates, 135 with a bar on all 122 days of the window). Eight of the
# collector's twelve are in it (BTC, ETH, SOL, AVAX, ADA, XRP, DOGE, LINK); ZEC ranked below 40, PEPE / WLD / HYPE did not exist yet.
WIDE: list[str] = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'GMTUSDT', 'AVAXUSDT', 'APEUSDT', 'BNBUSDT', 'ADAUSDT', 'NEARUSDT', 'XRPUSDT', 'FTMUSDT', 'SANDUSDT', 'MATICUSDT', 'DOTUSDT', 'WAVESUSDT', '1000SHIBUSDT', 'DOGEUSDT', 'GALAUSDT', 'ETCUSDT', 'LINKUSDT', 'AXSUSDT', 'ATOMUSDT', 'LTCUSDT', 'TRXUSDT', 'MANAUSDT', 'AAVEUSDT', 'CRVUSDT', 'UNFIUSDT', 'PEOPLEUSDT', 'RUNEUSDT', 'DYDXUSDT', 'BCHUSDT', 'FILUSDT', 'EOSUSDT', 'ZILUSDT', 'THETAUSDT', 'ENSUSDT', 'UNIUSDT', 'ALICEUSDT', 'OGNUSDT']
NEW = [s for s in WIDE if s not in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOGEUSDT")]   # the 32 the collector never recorded


def candidates() -> list[str]:
    syms = archive.list_prefixes("data/futures/um/monthly/klines/")
    return sorted(s for s in syms if s.endswith("USDT") and "_" not in s and s.isascii() and s.isalnum() and s not in EXCLUDE)


def _daily_1d(sym: str, months: list[str]) -> pd.DataFrame:
    """The symbol's 1d klines over `months`, read straight from the monthly zips (kept under ROOT/klines/<sym>/)."""
    try:
        archive.fetch_monthly("klines", sym, sub="1d", months=months)
    except Exception as e:  # noqa: BLE001 — one symbol's listing failing must not lose the ranking; it shows up as incomplete
        print(f"  {sym}: {e!r}", flush=True)
    parts = []
    for m in months:
        f = archive.ROOT / "klines" / sym / f"{sym}-1d-{m}.zip"
        if not (f.exists() and f.with_suffix(".zip.ok").exists()):
            continue
        with zipfile.ZipFile(f) as z:
            raw = z.read(z.namelist()[0])
        df = pd.read_csv(io.BytesIO(raw), header=None, dtype=str)
        df = df[df[0].str.isdigit()]
        parts.append(pd.DataFrame({"day": pd.to_datetime(df[0].astype("int64"), unit="ms", utc=True).dt.floor("D"),
                                   "quote_volume": df[7].astype(float), "close": df[4].astype(float)}))
    out = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["day", "quote_volume", "close"])
    out.insert(0, "symbol", sym)
    return out


def select(n: int = SELECT_N, window: tuple[date, date] = SELECT_WINDOW) -> pd.DataFrame:
    a, b = (pd.Timestamp(d, tz="UTC") for d in window)
    months = archive.months_between(window[0], window[1])
    syms = candidates()
    print(f"{len(syms)} USDT perpetuals listed by the archive; reading 1d klines {months[0]} .. {months[-1]}", flush=True)
    with ThreadPoolExecutor(max_workers=8) as ex:
        frames = list(ex.map(lambda s: _daily_1d(s, months), syms))
    d = pd.concat(frames, ignore_index=True)
    d = d[(d["day"] >= a) & (d["day"] <= b)]
    need = (b - a).days + 1
    g = d.groupby("symbol")
    r = pd.DataFrame({"days": g.size(), "median_quote_volume": g["quote_volume"].median(), "first_day": g["day"].min()}).reset_index()
    r["complete"] = r["days"] >= need
    r = r.sort_values("median_quote_volume", ascending=False).reset_index(drop=True)
    r["rank"] = r.index + 1
    r["selected"] = False
    r.loc[r[r["complete"]].index[:n], "selected"] = True
    chosen = r[r["selected"]]["symbol"].tolist()
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    txt = "\n".join([f"# The wider universe (`ft2 universe`) — top {n} USDT perpetuals by median daily quote volume, {window[0]} → {window[1]}\n",
                     f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · {len(syms)} candidates, {int(r['complete'].sum())} with a bar on all {need} days\n",
                     "\nWIDE = " + repr(chosen) + "\n", "\n" + r.assign(median_quote_volume=(r["median_quote_volume"] / 1e6).round(2)).rename(
                         columns={"median_quote_volume": "median_quote_volume_musd"}).to_markdown(index=False), "\n"])
    OUT_MD.write_text(txt)
    print(txt)
    return r


# ---- the screener's universe (PLAN P8, registration R18) ------------------------------------------------------------
# Not one list chosen once, but a membership per 30-day block of the harness: at each block start, the SCREEN_K USDT
# perpetuals with the largest median daily quote volume over the 30 days before it, the training names left out. With each
# member, four things known before the block — what a screener could rank names by. Daily bars only; nothing at or after
# the block start enters, no 5m bar, no label, no forecast.
SCREEN_K = 60
SCREEN_DAYS = 30             # the trailing window of liq and vol; a member has a daily bar on every one of these days
SCREEN_BASE_DAYS = 180       # `play` compares the last 30 days' volume with the last 180 days'
SCREEN_BASE_MIN = 90         # … and needs at least this many daily bars in them (a younger name has no `play`)
SCREEN_FROM = date(2020, 1, 1)
CHARACTERISTICS = {"young": "age_days", "violent": "vol_pct", "in_play": "play", "liquid": "liq_musd"}     # screen → column
HIGH_IS_LOW = {"young"}      # the screen's top third is the LOWEST third of its column
MEMBERS_CSV = Path(__file__).with_name("screen_members.csv")     # frozen from OUT_SCREEN_CSV, once, and committed
OUT_SCREEN_MD = Path("output/universe_screen.md")
OUT_SCREEN_CSV = Path("output/universe_screen_members.csv")


def characteristics(d: pd.DataFrame, starts: list[pd.Timestamp], exclude: set[str], k: int = SCREEN_K) -> pd.DataFrame:
    """Members and their characteristics per block start, from daily bars (symbol, day, quote_volume, close) alone.

    liq_musd  median daily quote volume over the SCREEN_DAYS days before the block, in millions of USDT
    vol_pct   sd of the daily log returns over the same days, in per cent
    play      liq over the median daily quote volume of the SCREEN_BASE_DAYS days before the block
    age_days  days from the symbol's first daily bar to the block start"""
    px = d.pivot(index="day", columns="symbol", values="close").sort_index()
    qv = d.pivot(index="day", columns="symbol", values="quote_volume").sort_index()
    days = pd.date_range(px.index.min(), px.index.max(), freq="D")
    px, qv = px.reindex(days), qv.reindex(days)
    r = np.log(px).diff()
    first = qv.apply(pd.Series.first_valid_index)
    rows = []
    for a in starts:
        a0 = pd.Timestamp(a).floor("D")
        w = (days >= a0 - pd.Timedelta(days=SCREEN_DAYS)) & (days < a0)
        wb = (days >= a0 - pd.Timedelta(days=SCREEN_BASE_DAYS)) & (days < a0)
        complete = qv.loc[w].notna().sum() == SCREEN_DAYS
        liq = qv.loc[w].median()
        base = qv.loc[wb]
        play = (liq / base.median()).where(base.notna().sum() >= SCREEN_BASE_MIN)
        pick = liq[complete & ~liq.index.isin(exclude) & (liq > 0)].nlargest(k).index
        rows.append(pd.DataFrame({"block": pd.Timestamp(a), "symbol": pick, "liq_musd": (liq[pick] / 1e6).to_numpy(), "vol_pct": (r.loc[w, pick].std() * 100).to_numpy(),
                                  "play": play[pick].to_numpy(), "age_days": [(a0 - first[s]).days for s in pick]}))
    return pd.concat(rows, ignore_index=True)


def thirds(m: pd.DataFrame, chars: dict[str, str] | None = None) -> pd.DataFrame:
    """Per block and screen: 2 = the screen's top third of the block's members (the youngest, the most violent, the most in
    play, the most liquid), 1 the middle, 0 the bottom; −1 where the member has no value. Ties are broken by symbol."""
    m = m.sort_values(["block", "symbol"]).reset_index(drop=True)
    for name, col in (chars or CHARACTERISTICS).items():
        v = -m[col] if name in HIGH_IS_LOW else m[col]
        rk = v.groupby(m["block"]).rank(method="first")
        n = v.notna().groupby(m["block"]).transform("sum")
        m[name] = np.where(v.isna(), -1, np.minimum((rk - 1) * 3 // n.clip(lower=1), 2)).astype(int)
    return m


def members(path: Path | str | None = None, hindsight: Path | str | None = None) -> pd.DataFrame:
    """The frozen members with their thirds; with `hindsight` (R19), also the thirds of the hindsight screen."""
    m = pd.read_csv(path or MEMBERS_CSV)
    m["block"] = pd.to_datetime(m["block"], utc=True)
    m = thirds(m)
    if hindsight is not None:
        h = pd.read_csv(hindsight)
        m = thirds(m.merge(h[["symbol", *HINDSIGHT.values()]], on="symbol", how="left", validate="m:1"), HINDSIGHT)
    return m


def screen_symbols(path: Path | str | None = None) -> list[str]:
    """Every name that is a member in some block, in a fixed order."""
    return sorted(set(members(path)["symbol"]))


# The months before F1 (registration R23): the same rule on the 30-day blocks of R23's scored days, which the calendar
# fixes — the archive's open interest begins 2021-12-01, the last 7-day label must end before F1 begins (PRE_END).
PRE_DAYS = (date(2021, 12, 10), date(2023, 4, 23))               # the first and the last scored day
PRE_END = pd.Timestamp("2023-05-01", tz="UTC")                   # F1's first instant: nothing at or after it is read
PRE_MEMBERS_CSV = Path(__file__).with_name("screen_members_pre.csv")     # frozen from OUT_PRE_CSV, once, and committed
OUT_PRE_MD = Path("output/universe_screen_pre.md")
OUT_PRE_CSV = Path("output/universe_screen_pre_members.csv")


F34_MEMBERS_CSV = Path(__file__).with_name("screen_members_f34.csv")     # R25: the members of F3+F4's blocks (`screen_select(("F3", "F4"))`), frozen once


def pre_starts() -> list[pd.Timestamp]:
    """The block starts of R23's scored days: every 30 days from the first one."""
    from .backtest import REFIT_DAYS
    a, b = (pd.Timestamp(d, tz="UTC") for d in PRE_DAYS)
    return list(pd.date_range(a, b, freq=pd.Timedelta(days=REFIT_DAYS)))


def screen_select(fold_names=("F1", "F2"), k: int = SCREEN_K, exclude: list[str] | None = None, pre: bool = False) -> pd.DataFrame:
    from . import folds
    from .__main__ import PAIRS
    from .backtest import REFIT_DAYS, blocks
    global OUT_SCREEN_CSV, OUT_SCREEN_MD
    if pre:
        starts, fold_names = pre_starts(), (f"{PRE_DAYS[0]} → {PRE_DAYS[1]}",)
        OUT_SCREEN_CSV, OUT_SCREEN_MD = OUT_PRE_CSV, OUT_PRE_MD
    else:
        starts = [a for f in fold_names for a, _ in blocks(f, pd.Timestamp(folds.FOLDS[f][1], tz="UTC"), REFIT_DAYS)]
    months = archive.months_between(SCREEN_FROM, (max(starts) - pd.Timedelta(days=1)).date())
    syms = candidates()
    print(f"{len(syms)} USDT perpetuals listed by the archive; reading 1d klines {months[0]} .. {months[-1]}", flush=True)
    with ThreadPoolExecutor(max_workers=8) as ex:
        d = pd.concat(list(ex.map(lambda s: _daily_1d(s, months), syms)), ignore_index=True)
    m = characteristics(d, starts, set(exclude if exclude is not None else PAIRS), k)
    OUT_SCREEN_CSV.parent.mkdir(parents=True, exist_ok=True)
    m.assign(block=m["block"].dt.strftime("%Y-%m-%d")).to_csv(OUT_SCREEN_CSV, index=False, float_format="%.6g")
    t = thirds(m)
    per = t.groupby("symbol").agg(blocks=("block", "size"), first=("block", "min"), last=("block", "max"), liq_musd=("liq_musd", "median"), vol_pct=("vol_pct", "median"),
                                  age_days=("age_days", "min"), **{f"top_{c}": (c, lambda x: int((x == 2).sum())) for c in CHARACTERISTICS}).reset_index()
    per = per.sort_values("blocks", ascending=False).assign(first=lambda x: x["first"].dt.date, last=lambda x: x["last"].dt.date)
    blk = t.groupby("block").agg(members=("symbol", "size"), liq_musd_min=("liq_musd", "min"), liq_musd_p50=("liq_musd", "median"), vol_pct_p50=("vol_pct", "median"),
                                 age_days_p50=("age_days", "median"), no_play=("play", lambda x: int(x.isna().sum()))).reset_index().assign(block=lambda x: x["block"].dt.date)
    txt = "\n".join([f"# The screener's universe (`ft2 universe --screen`) — per block, the top {k} USDT perpetuals by median daily quote volume over the {SCREEN_DAYS} days before it\n",
                     f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · {len(syms)} candidates · folds {'+'.join(fold_names)} · {len(starts)} blocks · "
                     f"{t['symbol'].nunique()} names are a member at least once · left out (the training names): {', '.join(sorted(exclude if exclude is not None else PAIRS))}\n",
                     f"\nMembers and characteristics → `{OUT_SCREEN_CSV}` (frozen into `ft2/{(PRE_MEMBERS_CSV if pre else MEMBERS_CSV).name}`). Daily bars before the block start only.\n",
                     "\n## Per block\n", blk.round(3).to_markdown(index=False), "\n", "\n## Per name\n", per.round(3).to_markdown(index=False), "\n"])
    OUT_SCREEN_MD.write_text(txt)
    print(txt)
    return m


# ---- the hindsight diagnostic (PLAN P8, registration R19) ------------------------------------------------------------
# One thing about a name that NO screener could have known: how much it is traded long after the block — its median daily
# quote volume over HINDSIGHT_WINDOW, a day without a bar counted as zero (delisted, or renamed: the symbol is the name).
# It is there to be compared with the screens that use no hindsight, never to be traded. Quote volume only: no price of
# the window is read.
HINDSIGHT_WINDOW = (date(2026, 1, 1), date(2026, 8, 31))
HINDSIGHT = {"hindsight": "hind_musd"}                           # screen → column; the top third is the HIGHEST third
HINDSIGHT_CSV = Path(__file__).with_name("screen_hindsight.csv")  # frozen from OUT_HINDSIGHT_CSV, once, and committed
OUT_HINDSIGHT_MD = Path("output/universe_hindsight.md")
OUT_HINDSIGHT_CSV = Path("output/universe_hindsight.csv")


def hindsight_volume(d: pd.DataFrame, names: list[str], window: tuple[date, date] = HINDSIGHT_WINDOW) -> pd.DataFrame:
    """Per name: `hind_musd`, the median daily quote volume over the window in millions of USDT, a missing day counted as
    zero; `hind_days`, the days of the window with a bar. From daily bars (symbol, day, quote_volume)."""
    a, b = (pd.Timestamp(x, tz="UTC") for x in window)
    days = pd.date_range(a, b, freq="D")
    qv = d[(d["day"] >= a) & (d["day"] <= b)].pivot(index="day", columns="symbol", values="quote_volume").reindex(index=days, columns=names)
    return pd.DataFrame({"symbol": names, "hind_musd": (qv.fillna(0.0).median() / 1e6).to_numpy(), "hind_days": qv.notna().sum().to_numpy()})


def hindsight_select(window: tuple[date, date] = HINDSIGHT_WINDOW) -> pd.DataFrame:
    names = screen_symbols()
    months = archive.months_between(*window)
    print(f"{len(names)} members; reading 1d klines {months[0]} .. {months[-1]}", flush=True)
    with ThreadPoolExecutor(max_workers=8) as ex:
        d = pd.concat(list(ex.map(lambda s: _daily_1d(s, months), names)), ignore_index=True)
    h = hindsight_volume(d[["symbol", "day", "quote_volume"]], names, window)
    OUT_HINDSIGHT_CSV.parent.mkdir(parents=True, exist_ok=True)
    h.to_csv(OUT_HINDSIGHT_CSV, index=False, float_format="%.6g")
    m = thirds(members().merge(h, on="symbol", how="left", validate="m:1"), HINDSIGHT)
    need = len(pd.date_range(*window, freq="D"))
    blk = m.groupby("block").agg(members=("symbol", "size"), gone=("hind_musd", lambda x: int((x == 0).sum())), hind_musd_p50=("hind_musd", "median"),
                                 top_third_min_musd=("hind_musd", lambda x: float(x[m.loc[x.index, "hindsight"] == 2].min()))).reset_index().assign(block=lambda x: x["block"].dt.date)
    per = h.merge(m.groupby("symbol").agg(blocks=("block", "size"), top_hindsight=("hindsight", lambda x: int((x == 2).sum()))).reset_index(), on="symbol")
    txt = "\n".join([f"# The hindsight characteristic (`ft2 universe --hindsight`) — each member's median daily quote volume, {window[0]} → {window[1]}\n",
                     f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · {len(names)} names · {int((h['hind_musd'] == 0).sum())} with a median of zero (gone or renamed) · "
                     f"{int((h['hind_days'] == need).sum())} with a bar on all {need} days\n",
                     f"\nPer name → `{OUT_HINDSIGHT_CSV}` (frozen into `ft2/screen_hindsight.csv`). Quote volume only; no price of the window is read.\n",
                     "\n## Per block\n", blk.round(3).to_markdown(index=False), "\n",
                     "\n## Per name\n", per.sort_values("hind_musd", ascending=False).round(3).to_markdown(index=False), "\n"])
    OUT_HINDSIGHT_MD.write_text(txt)
    print(txt)
    return h
