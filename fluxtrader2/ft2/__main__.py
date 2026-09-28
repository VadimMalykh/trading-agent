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
    if u == "all":                                            # the archive slices are rewritten whole: ingest every name they have ever held
        from .universe import WIDE, screen_symbols
        return list(dict.fromkeys([*PAIRS, *WIDE, *screen_symbols()]))
    return args.symbols or PAIRS


def cmd_archive(args):
    from . import archive
    archive.main(args.kinds, _symbols(args), args.start, args.end, monthly=args.monthly)


def cmd_universe(args):
    from . import universe
    if args.screen:
        return universe.screen_select(args.folds, args.n or universe.SCREEN_K)
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
    if args.book:                                             # R21: the validity of an `oibook` run, read before its money
        v = audit.book_check(args.run)
        return print(f"book check {v['status']}: {v}")
    print(audit.run(args.run, args.draws))
    print(f"wrote {audit.OUT / args.run}/")


def cmd_horizon(args):
    from . import horizon
    print(horizon.run(args.run, args.holds))
    print(f"wrote {horizon.OUT / args.run}/")


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
                     args.taker_bps, args.maker_bps, args.latency, args.refit_days, args.registration, args.name, args.seed, args.cost_mult)
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
    i.add_argument("--universe", choices=["wide", "screen", "all"], help="archive slices only: ft2.universe.WIDE (R10), the screener's members (R18), or all = the twelve + both")
    sub.add_parser("inventory", help="integrity report over data/*.parquet -> output/inventory.md")
    a = sub.add_parser("archive", help="fetch Binance public-archive files into data/raw/external/binance/")
    a.add_argument("kinds", nargs="+", help="bookDepth metrics aggTrades fundingRate klines/1m …")
    a.add_argument("--symbols", nargs="*")
    a.add_argument("--start", default="2023-01-01")
    a.add_argument("--end", default=None, help="inclusive; default: two days ago")
    a.add_argument("--monthly", action="store_true", help="klines/<interval>: the archive's monthly files for the months of [start, end] instead of daily ones")
    a.add_argument("--universe", choices=["wide", "screen", "all"])
    u = sub.add_parser("universe", help="R10: rank every USDT perpetual the archive lists by median daily quote volume over the four months before F0 → output/universe_wide.md; "
                                        "--screen (R18): the members per block and what a screener could rank them by → output/universe_screen.md")
    u.add_argument("--n", type=int, default=None, help="default 40; with --screen 60 a block")
    u.add_argument("--screen", action="store_true")
    u.add_argument("--hindsight", action="store_true", help="R19: each member's median daily quote volume over 2026-01 → 2026-08 → output/universe_hindsight.md")
    u.add_argument("--folds", nargs="*", default=["F1", "F2"], help="--screen: the folds whose blocks get a membership")
    cw = sub.add_parser("costwide", help="R10: spread + impact for pairs without a tape (one pooled candle proxy fitted on the twelve) → data/cost_daily_wide.parquet, output/cost_wide.md")
    cw.add_argument("--symbols", nargs="*")
    cw.add_argument("--universe", choices=["wide", "screen", "all"])
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
    for a_ in c._actions:
        if a_.dest in ("taker_bps", "maker_bps"):
            b.add_argument(*a_.option_strings, type=a_.type, default=a_.default)
    b.add_argument("--symbols", nargs="*")
    b.add_argument("--universe", choices=["wide", "screen"], help="ft2.universe.WIDE, the forty of R10, or the screener's members (R18), instead of the twelve")
    sc = sub.add_parser("screen", help="P8 (R18): the screener read of a `transferbook` run → output/screen/<run>/screen.md (see ft2/screen.py)")
    sc.add_argument("run", help="the run's directory name under output/backtest/")
    sc.add_argument("--reference", default=None, help="the run whose forecasts the training names must reproduce (default: R13 B's)")
    sc.add_argument("--draws", type=int, default=200)
    sc.add_argument("--hindsight", action="store_true", help="R19: read the one hindsight screen (ft2/screen_hindsight.csv) instead of R18's four → output/screen/<run>_hindsight/")
    au = sub.add_parser("audit", help="P8 (R20): what funding, premium, open interest, long/short ratios and taker flow say about a member's next day, on the cells of a "
                                      "`transferbook` run → output/audit/<run>/audit.md (see ft2/audit.py)")
    au.add_argument("run", help="the run's directory name under output/backtest/")
    au.add_argument("--draws", type=int, default=200)
    au.add_argument("--book", action="store_true", help="R21: check an `oibook` run's decisions (hourly grid, members only, whole dollar-neutral units) → <run>/book_check.json")
    hz = sub.add_parser("horizon", help="P8 (R22): the longer hold — what a signal's top tenth earns against its bottom tenth over 3 and 7 days, on the cells of a "
                                        "`transferbook` run → output/horizon/<run>/horizon.md (see ft2/horizon.py)")
    hz.add_argument("run", help="the run's directory name under output/backtest/")
    hz.add_argument("--holds", nargs="*", type=int, default=[864, 2016], help="in 5m bars")
    sv =sub.add_parser("serve", help="P7: R14 paper-traded live on the serve host → output/serve/ (see ft2/serve.py, docs/SERVE.md)")
    sv.add_argument("action", choices=["seed", "fetch", "start", "decide", "mark", "status", "check", "replay", "ledger"])
    sv.add_argument("--src", default="data/candles_5m.parquet", help="seed: the collector's 5m candles (on the work VM)")
    sv.add_argument("--dst", default=None, help="seed: where to write (default data/serve/candles_seed.parquet)")
    sv.add_argument("--folds", nargs="*", default=["F3", "F4"], help="replay: the folds to replay hour by hour")
    sv.add_argument("--against", default="output/backtest/r16_ridgebook_1d_ho12_f34", help="replay: the harness run to reproduce")
    args = p.parse_args(argv)
    return {"smoke": cmd_smoke, "ingest": cmd_ingest, "inventory": cmd_inventory, "archive": cmd_archive, "tape": cmd_tape,
            "cost": cmd_cost, "costpre": cmd_costpre, "ceiling": cmd_ceiling, "backtest": cmd_backtest, "universe": cmd_universe,
            "costwide": cmd_costwide, "serve": cmd_serve, "screen": cmd_screen, "audit": cmd_audit, "horizon": cmd_horizon}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
