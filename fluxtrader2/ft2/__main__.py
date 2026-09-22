"""Command entry point: `python -m ft2 <subcommand>` (always via scripts/ft2.sh).

Subcommands are added phase by phase (docs/PLAN.md §4). Only `smoke` exists at P-1.
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
                  "levels": "ingest_levels", "klines": "ingest_klines"}   # levels: the collector ladder, windowed export → data/ladder/


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
    """--symbols, or --universe wide (the twelve plus ft2.universe.WIDE, in that order, no duplicates), or the twelve."""
    if getattr(args, "universe", None) == "wide":
        from .universe import WIDE
        if not WIDE:
            raise SystemExit("ft2/universe.py::WIDE is empty: run `ft2 universe` and freeze its list there first")
        return list(dict.fromkeys([*PAIRS, *WIDE]))
    return args.symbols or PAIRS


def cmd_archive(args):
    from . import archive
    archive.main(args.kinds, _symbols(args), args.start, args.end, monthly=args.monthly)


def cmd_universe(args):
    from . import universe
    universe.select(args.n)


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
    r = backtest.run(backtest.get_strategy(args.strategy, dict(args.param or [])), _symbols(args), args.folds, args.execs, args.draws,
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
    i.add_argument("--universe", choices=["wide"], help="archive slices only: the twelve plus ft2.universe.WIDE")
    sub.add_parser("inventory", help="integrity report over data/*.parquet -> output/inventory.md")
    a = sub.add_parser("archive", help="fetch Binance public-archive files into data/raw/external/binance/")
    a.add_argument("kinds", nargs="+", help="bookDepth metrics aggTrades fundingRate klines/1m …")
    a.add_argument("--symbols", nargs="*")
    a.add_argument("--start", default="2023-01-01")
    a.add_argument("--end", default=None, help="inclusive; default: two days ago")
    a.add_argument("--monthly", action="store_true", help="klines/<interval>: the archive's monthly files for the months of [start, end] instead of daily ones")
    a.add_argument("--universe", choices=["wide"])
    u = sub.add_parser("universe", help="R10: rank every USDT perpetual the archive lists by median daily quote volume over the four months before F0 → output/universe_wide.md")
    u.add_argument("--n", type=int, default=40)
    cw = sub.add_parser("costwide", help="R10: spread + impact for pairs without a tape (one pooled candle proxy fitted on the twelve) → data/cost_daily_wide.parquet, output/cost_wide.md")
    cw.add_argument("--symbols", nargs="*")
    cw.add_argument("--universe", choices=["wide"])
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
    b.add_argument("--universe", choices=["wide"], help="the twelve plus ft2.universe.WIDE (R10)")
    args = p.parse_args(argv)
    return {"smoke": cmd_smoke, "ingest": cmd_ingest, "inventory": cmd_inventory, "archive": cmd_archive, "tape": cmd_tape,
            "cost": cmd_cost, "costpre": cmd_costpre, "ceiling": cmd_ceiling, "backtest": cmd_backtest, "universe": cmd_universe,
            "costwide": cmd_costwide}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
