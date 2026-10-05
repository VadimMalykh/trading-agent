"""Command entry point: `python -m ft2 <subcommand>` (always via scripts/ft2.sh).

Subcommands are added phase by phase (docs/PLAN.md §4).
"""
import argparse
import sys


def cmd_smoke(_args):
    import numpy, pandas, pyarrow, scipy, sklearn, statsmodels, lightgbm  # noqa: F401
    print("fluxtrader2 image ok:",
          f"numpy {numpy.__version__}, pandas {pandas.__version__}, pyarrow {pyarrow.__version__},",
          f"scipy {scipy.__version__}, sklearn {sklearn.__version__},",
          f"statsmodels {statsmodels.__version__}, lightgbm {lightgbm.__version__}")


ARCHIVE_INGEST = {"metrics": "ingest_metrics", "depth": "ingest_depth", "funding_archive": "ingest_funding_archive",
                  "levels": "ingest_levels", "klines": "ingest_klines", "premium": "ingest_premium"}   # levels: the collector ladder, windowed export → data/ladder/


def cmd_ingest(args):
    from . import data
    slices = args.slices or [s for s in data.SLICES if (data.RAW / f"{s}.csv.gz").exists()]
    for s in slices:
        r = getattr(data, ARCHIVE_INGEST[s])(_symbols(args)) if s in ARCHIVE_INGEST else data.ingest(s)
        print(f"{r['slice']:<15} rows_in={r['rows_in']:>11,} dups={r['dups_dropped']:>6,} "
              f"rows_out={r['rows_out']:>11,}  {r['first']} .. {r['last']}", flush=True)


def cmd_inventory(args):
    from . import inventory
    print(inventory.run())


PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT",
         "DOGEUSDT", "ZECUSDT", "1000PEPEUSDT", "WLDUSDT", "HYPEUSDT"]


def _symbols(args) -> list[str]:
    """--symbols, or --universe wide (exactly ft2.universe.WIDE: the forty chosen by volume before F0 — eight of the twelve are in it,
    the other four are not, by the same rule), or the twelve."""
    u = getattr(args, "universe", None)
    if u == "wide":
        from .universe import WIDE
        return list(WIDE)
    if u == "screen":                                         # R18: every name that is a member of some block (never one of the twelve)
        from .universe import screen_symbols
        return screen_symbols()
    if u == "pre":                                            # R23: the members of the blocks before F1
        from .universe import PRE_MEMBERS_CSV, screen_symbols
        return screen_symbols(PRE_MEMBERS_CSV)
    if u == "f34":                                            # R25: the members of F3+F4's blocks
        from .universe import F34_MEMBERS_CSV, screen_symbols
        return screen_symbols(F34_MEMBERS_CSV)
    if u == "all":                                            # the archive slices are rewritten whole: ingest every name they have ever held
        from .universe import F34_MEMBERS_CSV, PRE_MEMBERS_CSV, WIDE, screen_symbols
        more = [x for f in (PRE_MEMBERS_CSV, F34_MEMBERS_CSV) if f.exists() for x in screen_symbols(f)]
        return list(dict.fromkeys([*PAIRS, *WIDE, *screen_symbols(), *more]))
    return args.symbols or PAIRS


def cmd_archive(args):
    from . import archive
    archive.main(args.kinds, _symbols(args), args.start, args.end, monthly=args.monthly)


def cmd_index(args):
    from . import index
    index.main(args.action, args.source, args.start, args.end, args.symbols, args.workers)


def cmd_etf(args):
    from . import etf
    etf.main(args.action, args.no_wayback, args.hours, args.per_hour, args.cached)


def cmd_events(args):
    from . import events
    events.main(args.action, PAIRS, args.source, args.cached)


def cmd_universe(args):
    from . import universe
    if args.screen:
        return universe.screen_select(args.folds, args.n or universe.SCREEN_K, pre=args.pre)
    if args.hindsight:
        return universe.hindsight_select()
    universe.select(args.n or universe.SELECT_N)


def cmd_screen(args):
    from . import screen
    from .universe import HINDSIGHT_CSV
    print(screen.read(args.run, args.reference, args.draws, hindsight=HINDSIGHT_CSV if args.hindsight else None))
    print(f"wrote {screen.OUT / (args.run + screen.HINDSIGHT_SUFFIX * args.hindsight)}/")


def cmd_audit(args):
    from . import audit
    if args.pool:                                             # R24: several `oibook` runs read as one book; --confirm (R25): the confirmation's gate
        print(audit.pool([args.run, *args.more], args.name, confirm=args.confirm, beside=args.beside))
        return print(f"wrote {audit.bt.OUT / args.name}/")
    if args.book:                                             # R21: the validity of an `oibook` run, read before its money
        v = audit.book_check(args.run)
        return print(f"book check {v['status']}: {v}")
    if args.family in ("index", "etf"):                       # R26 / R27: the US index / the ETF flows as per-name information, the shift null, the twelve beside the members
        from . import audit_index
        print(audit_index.run(args.run, pairs=PAIRS, twelve=args.twelve, jobs=args.jobs, family=args.family))
        return print(f"wrote {audit_index.OUT / (args.run + '_' + args.family)}/" + (f" and {audit_index.OUT / ('twelve_' + args.family)}/" if args.twelve else ""))
    print(audit.run(args.run, args.draws))
    print(f"wrote {audit.OUT / args.run}/")


def cmd_horizon(args):
    from . import horizon
    if args.pre:                                              # R23: the months before F1, cells from the frozen members
        print(horizon.run_pre(args.holds or horizon.PRE_HOLDS, name=args.name or horizon.PRE, reexecute=args.reexecute))
        return print(f"wrote {horizon.OUT / (args.name or horizon.PRE)}/")
    if not args.run:
        raise SystemExit("horizon: name the run, or --pre")
    print(horizon.run(args.run, args.holds or horizon.HOLDS, name=args.name))
    print(f"wrote {horizon.OUT / (args.name or args.run)}/")


def cmd_costwide(args):
    from . import cost
    import pandas as pd
    print(cost.wide([s for s in _symbols(args) if s not in PAIRS], pd.Timestamp(args.start, tz="UTC")))


def cmd_tape(args):
    from . import tape
    tape.run(args.symbols or PAIRS, args.start, args.end, workers=args.workers, keep_zip=args.keep_zip)


def cmd_cost(args):
    from . import cost
    print(cost.run(args.taker_bps, args.maker_bps, args.fee_source, args.symbols or PAIRS))


def cmd_costpre(args):
    from . import cost
    print(cost.prehistory(args.symbols or PAIRS))


def cmd_ceiling(args):
    from . import ceiling, market
    if args.target == "basket":
        market.run(args.taker_bps, args.maker_bps, args.fee_source, args.symbols or PAIRS, args.folds, args.draws)
        return print(f"wrote {market.OUT_MD} and {market.OUT_DIR}/")
    if args.folds:
        raise SystemExit("--folds is for --target basket; the pair audit reads F1+F2")
    ceiling.run(args.taker_bps, args.maker_bps, args.fee_source, args.symbols or PAIRS, args.items, args.draws)
    print(f"wrote {ceiling.OUT_MD if not args.items else 'output/ceiling*.md'} and {ceiling.OUT_DIR}/")


def cmd_serve(args):
    from . import serve
    serve.main(args)


def _param(s: str):
    k, v = s.split("=", 1)
    for cast in (int, float):
        try:
            return k, cast(v)
        except ValueError:
            pass
    return k, v


def cmd_backtest(args):
    from . import backtest
    syms = _symbols(args)
    if args.strategy == "transferbook":                       # the training names first, in their fixed order; then the names to score
        syms = [*PAIRS, *(s for s in syms if s not in PAIRS)]
    r = backtest.run(backtest.get_strategy(args.strategy, dict(args.param or [])), syms, args.folds, args.execs, args.draws,
                     args.taker_bps, args.maker_bps, args.latency, args.refit_days, args.registration, args.name, args.seed, args.cost_mult, args.reexecute)
    print((r["dir"] / "report.md").read_text())
    print(f"wrote {r['dir']}/")


def main(argv=None):
    p = argparse.ArgumentParser(prog="ft2")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("smoke", help="import every dependency and print versions")
    i = sub.add_parser("ingest", help="raw csv.gz -> parquet (all present collector slices, or the named ones; "
                                      "archive slices metrics/depth/funding_archive by name)")
    i.add_argument("slices", nargs="*")
    i.add_argument("--symbols", nargs="*", help="archive slices only: which pairs (default the twelve)")
    i.add_argument("--universe", choices=["wide", "screen", "pre", "f34", "all"], help="archive slices only: ft2.universe.WIDE (R10), the screener's members (R18), or all = the twelve + both")
    sub.add_parser("inventory", help="integrity report over data/*.parquet -> output/inventory.md")
    a = sub.add_parser("archive", help="fetch Binance public-archive files into data/raw/external/binance/")
    a.add_argument("kinds", nargs="+", help="bookDepth metrics aggTrades fundingRate klines/1m …")
    a.add_argument("--symbols", nargs="*")
    a.add_argument("--start", default="2023-01-01")
    a.add_argument("--end", default=None, help="inclusive; default: two days ago")
    a.add_argument("--monthly", action="store_true", help="klines/<interval>: the archive's monthly files for the months of [start, end] instead of daily ones")
    a.add_argument("--universe", choices=["wide", "screen", "pre", "f34", "all"])
    u = sub.add_parser("universe", help="R10: rank every USDT perpetual the archive lists by median daily quote volume over the four months before F0 → output/universe_wide.md; "
                                        "--screen (R18): the members per block and what a screener could rank them by → output/universe_screen.md")
    u.add_argument("--n", type=int, default=None, help="default 40; with --screen 60 a block")
    u.add_argument("--screen", action="store_true")
    u.add_argument("--pre", action="store_true", help="--screen only (R23): the 30-day blocks of 2021-12-10 → 2023-04-23 instead of the folds' → output/universe_screen_pre.md")
    u.add_argument("--hindsight", action="store_true", help="R19: each member's median daily quote volume over 2026-01 → 2026-08 → output/universe_hindsight.md")
    u.add_argument("--folds", nargs="*", default=["F1", "F2"], help="--screen: the folds whose blocks get a membership")
    cw = sub.add_parser("costwide", help="R10: spread + impact for pairs without a tape (one pooled candle proxy fitted on the twelve) → data/cost_daily_wide.parquet, output/cost_wide.md")
    cw.add_argument("--symbols", nargs="*")
    cw.add_argument("--universe", choices=["wide", "screen", "pre", "f34", "all"])
    cw.add_argument("--start", default="2023-01-01")
    t = sub.add_parser("tape", help="P1: stream archive aggTrades into data/tape/<symbol>.parquet (per-minute summary); zips are not kept")
    t.add_argument("--symbols", nargs="*")
    t.add_argument("--start", default="2023-01-01")
    t.add_argument("--end", default=None, help="inclusive; default: two days ago")
    t.add_argument("--workers", type=int, default=6)
    t.add_argument("--keep-zip", action="store_true", help="keep the raw zips (only for a short validation window)")
    c = sub.add_parser("cost", help="P1: price the trade → output/cost.md, data/cost_daily.parquet, data/cost_table.parquet "
                                    "(see ft2/cost.py)")
    c.add_argument("--taker-bps", type=float, default=5.0, help="per side; default: the account's measured rate (VIP 0)")
    c.add_argument("--maker-bps", type=float, default=2.0)
    c.add_argument("--fee-source", default="account read 2026-09-20 (GET /fapi/v1/commissionRate): VIP 0, 0.020 % maker / 0.050 % taker; "
                                           "BNB fee-burn on but no BNB in the futures wallet, so no discount")
    c.add_argument("--symbols", nargs="*")
    cp = sub.add_parser("costpre", help="P5: spread + impact for the days before the tape (candle proxy) → data/cost_daily_pre.parquet, output/cost_pre.md")
    cp.add_argument("--symbols", nargs="*")
    g = sub.add_parser("ceiling", help="P2: the ceiling audit on F1+F2 → output/ceiling.md, output/ceiling/ (see ft2/ceiling.py)")
    for a_ in c._actions:                      # the same fee inputs as `cost`, so both are priced alike
        if a_.dest in ("taker_bps", "maker_bps", "fee_source"):
            g.add_argument(*a_.option_strings, type=a_.type, default=a_.default)
    g.add_argument("--symbols", nargs="*")
    g.add_argument("--items", nargs="*", choices=["7", "1", "2", "3", "6", "4", "5"],
                   help="PLAN P2 item numbers; default all, → output/ceiling.md; a partial run → output/ceiling_items_<…>.md")
    g.add_argument("--draws", type=int, default=200, help="#4: label shuffles per scheme")
    g.add_argument("--target", choices=["pairs", "basket"], default="pairs",
                   help="basket: P5's audit of the market factor, per year → output/market.md (see ft2/market.py)")
    g.add_argument("--folds", nargs="*", help="--target basket only: exploration folds to read (default FP F0 F1 F2)")
    b = sub.add_parser("backtest", help="P3: a strategy through the harness → output/backtest/<name>/ (see ft2/backtest.py)")
    b.add_argument("strategy", help="a name in backtest.STRATEGIES / rules.STRATEGIES, e.g. coin")
    b.add_argument("--param", nargs="*", type=_param, metavar="K=V", help="the strategy's constructor arguments")
    b.add_argument("--folds", nargs="*", default=["F1", "F2"], help="a confirmation fold (F3–F5) needs --registration")
    b.add_argument("--registration", help="R<n>: the PLAN §8 block this read belongs to")
    b.add_argument("--execs", nargs="*", default=["taker", "maker", "maker_ev"], choices=["taker", "maker", "maker_ev"])
    b.add_argument("--draws", type=int, default=200, help="noise floor: label shuffles")
    b.add_argument("--latency", type=int, default=1, help="bars between the decision and the execution price")
    b.add_argument("--refit-days", type=int, default=30)
    b.add_argument("--seed", type=int, default=0)
    b.add_argument("--cost-mult", type=float, default=1.0, help="sensitivity: multiply spread + impact (not fees) by this")
    b.add_argument("--name", help="output directory under output/backtest/ (default: the strategy's name)")
    b.add_argument("--reexecute", metavar="TAG", help="a registered read made again after a defect in the measurement (PLAN §3): only of folds --registration "
                                                       "has read, logged as R<n>/TAG beside the first read")
    for a_ in c._actions:
        if a_.dest in ("taker_bps", "maker_bps"):
            b.add_argument(*a_.option_strings, type=a_.type, default=a_.default)
    b.add_argument("--symbols", nargs="*")
    b.add_argument("--universe", choices=["wide", "screen", "pre", "f34"], help="ft2.universe.WIDE, the forty of R10, or the screener's members (R18), instead of the twelve")
    sc = sub.add_parser("screen", help="P8 (R18): the screener read of a `transferbook` run → output/screen/<run>/screen.md (see ft2/screen.py)")
    sc.add_argument("run", help="the run's directory name under output/backtest/")
    sc.add_argument("--reference", default=None, help="the run whose forecasts the training names must reproduce (default: R13 B's)")
    sc.add_argument("--draws", type=int, default=200)
    sc.add_argument("--hindsight", action="store_true", help="R19: read the one hindsight screen (ft2/screen_hindsight.csv) instead of R18's four → output/screen/<run>_hindsight/")
    au = sub.add_parser("audit", help="P8 (R20): what funding, premium, open interest, long/short ratios and taker flow say about a member's next day, on the cells of a "
                                      "`transferbook` run → output/audit/<run>/audit.md (see ft2/audit.py)")
    au.add_argument("run", help="the run's directory name under output/backtest/")
    au.add_argument("more", nargs="*", help="--pool: the other runs")
    au.add_argument("--name", default="r24_pool", help="--pool: the output directory under output/backtest/")
    au.add_argument("--confirm", action="store_true", help="--pool (R25): the confirmation's gate, and R24's saved fills pooled beside it (described)")
    au.add_argument("--pool", action="store_true", help="R24: read the named `oibook` runs as one book → output/backtest/r24_pool/pool.md")
    au.add_argument("--beside", nargs="*", help="--pool --confirm: the exploration runs pooled beside the confirmation's (default: R24's two as first read)")
    au.add_argument("--draws", type=int, default=200)
    au.add_argument("--book", action="store_true", help="R21: check an `oibook` run's decisions (hourly grid, members only, whole dollar-neutral units) → <run>/book_check.json")
    au.add_argument("--family", choices=["exchange", "index", "etf"], default="exchange", help="R26: `index` — the US index family (beta, beta × the index's move) with R22's shift null → output/audit/<run>_index/; R27: `etf` — the ETF flows, F2 only → <run>_etf/")
    au.add_argument("--twelve", action="store_true", help="--family index: the twelve on the same grid as a second universe (one family of ten) → output/audit/twelve_index/")
    au.add_argument("--jobs", type=int, default=4)
    hz = sub.add_parser("horizon", help="P8 (R22): the longer hold — what a signal's top tenth earns against its bottom tenth over 3 and 7 days, on the cells of a "
                                        "`transferbook` run → output/horizon/<run>/horizon.md (see ft2/horizon.py)")
    hz.add_argument("run", nargs="?", help="the run's directory name under output/backtest/")
    hz.add_argument("--holds", nargs="*", type=int, default=None, help="in 5m bars (default 864 2016; with --pre 2016)")
    hz.add_argument("--pre", action="store_true", help="R23: the open-interest score on the months before F1 (ft2/screen_members_pre.csv) → output/horizon/pre/horizon.md")
    hz.add_argument("--name", help="output directory under output/horizon/ (default: the run's name; with --pre, pre)")
    hz.add_argument("--reexecute", metavar="TAG", help="--pre: R23's read made again after a defect in the measurement (PLAN §3), logged as R23/TAG")
    ix = sub.add_parser("index", help="P8 (B3, PLAN §9 #7): the US index CFDs from Dukascopy's public datafeed → data/raw/external/dukascopy/, data/index_1m.parquet, output/index_inventory.md (see ft2/index.py)")
    ix.add_argument("action", choices=["fetch", "ingest", "inventory"])
    ix.add_argument("--source", choices=["histdata", "dukascopy"], default="histdata", help="fetch/ingest: HistData (the parquet; default) or Dukascopy (the cross-check; throttled)")
    ix.add_argument("--start", default=None, help="fetch: first day (default FP's first day, 2020-05-01; histdata: its year)")
    ix.add_argument("--end", default=None, help="fetch --source dukascopy: last day inclusive (default yesterday UTC)")
    ix.add_argument("--symbols", nargs="*", default=None, help="US500 US100 (default both)")
    et = sub.add_parser("etf", help="P8 (B3′, PLAN §9 #7): the US spot-ETF net flows from Farside's tables → data/raw/external/farside/, data/etf_flows.parquet, output/etf_inventory.md (see ft2/etf.py)")
    et.add_argument("action", choices=["fetch", "ingest", "inventory"])
    et.add_argument("--no-wayback", action="store_true", help="inventory: skip the known-at measurement on the Wayback Machine's snapshots of the live page")
    et.add_argument("--hours", nargs="*", type=int, default=None, help="inventory: fetch only the snapshots taken at these UTC hours (default all)")
    et.add_argument("--cached", action="store_true", help="inventory: the known-at measurement on the snapshots already under data/raw/external/farside/wayback/, no fetch")
    et.add_argument("--per-hour", type=int, default=3, help="inventory: at most this many snapshots per UTC hour, spread over the archive (0 = all; the Wayback Machine throttles)")
    ix.add_argument("--workers", type=int, default=None, help="fetch --source dukascopy: concurrent requests (default 3; the feed throttles)")
    ev = sub.add_parser("events", help="P8 (PLAN §9 #8): token unlock schedules (DefiLlama, with the Wayback Machine's snapshots as the known-at) and Binance's listing / delisting announcements → data/unlock_events.parquet, data/unlock_asof.parquet, data/binance_events.parquet, output/events_inventory.md (see ft2/events.py)")
    ev.add_argument("action", choices=["fetch", "ingest", "inventory"])
    ev.add_argument("--source", nargs="*", choices=["llama", "binance", "wayback"], default=None, help="fetch: which sources (default all three; binance answers from the work VM, not from every network)")
    ev.add_argument("--cached", action="store_true", help="inventory: no network — the archive's first-month listing is read from its cached copy")
    sv =sub.add_parser("serve", help="P7: R14 paper-traded live on the serve host → output/serve/ (see ft2/serve.py, docs/SERVE.md)")
    sv.add_argument("action", choices=["seed", "fetch", "start", "decide", "mark", "status", "check", "replay", "ledger"])
    sv.add_argument("--src", default="data/candles_5m.parquet", help="seed: the collector's 5m candles (on the work VM)")
    sv.add_argument("--dst", default=None, help="seed: where to write (default data/serve/candles_seed.parquet)")
    sv.add_argument("--folds", nargs="*", default=["F3", "F4"], help="replay: the folds to replay hour by hour")
    sv.add_argument("--against", default="output/backtest/r16_ridgebook_1d_ho12_f34", help="replay: the harness run to reproduce")
    args = p.parse_args(argv)
    return {"smoke": cmd_smoke, "ingest": cmd_ingest, "inventory": cmd_inventory, "archive": cmd_archive, "tape": cmd_tape,
            "cost": cmd_cost, "costpre": cmd_costpre, "ceiling": cmd_ceiling, "backtest": cmd_backtest, "universe": cmd_universe,
            "costwide": cmd_costwide, "serve": cmd_serve, "index": cmd_index, "etf": cmd_etf, "events": cmd_events, "screen": cmd_screen, "audit": cmd_audit, "horizon": cmd_horizon}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
