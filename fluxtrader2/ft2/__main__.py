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
                  "levels": "ingest_levels"}   # levels: the collector ladder, windowed export → data/ladder/


def cmd_ingest(args):
    from . import data
    slices = args.slices or [s for s in data.SLICES if (data.RAW / f"{s}.csv.gz").exists()]
    for s in slices:
        r = getattr(data, ARCHIVE_INGEST[s])(PAIRS) if s in ARCHIVE_INGEST else data.ingest(s)
        print(f"{r['slice']:<15} rows_in={r['rows_in']:>11,} dups={r['dups_dropped']:>6,} "
              f"rows_out={r['rows_out']:>11,}  {r['first']} .. {r['last']}", flush=True)


def cmd_inventory(args):
    from . import inventory
    print(inventory.run())


PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT",
         "DOGEUSDT", "ZECUSDT", "1000PEPEUSDT", "WLDUSDT", "HYPEUSDT"]


def cmd_archive(args):
    from . import archive
    archive.main(args.kinds, args.symbols or PAIRS, args.start, args.end)


def cmd_tape(args):
    from . import tape
    tape.run(args.symbols or PAIRS, args.start, args.end, workers=args.workers, keep_zip=args.keep_zip)


def cmd_cost(args):
    from . import cost
    print(cost.run(args.taker_bps, args.maker_bps, args.fee_source, args.symbols or PAIRS))


def main(argv=None):
    p = argparse.ArgumentParser(prog="ft2")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("smoke", help="import every dependency and print versions")
    i = sub.add_parser("ingest", help="raw csv.gz -> parquet (all present collector slices, or the named ones; "
                                      "archive slices metrics/depth/funding_archive by name)")
    i.add_argument("slices", nargs="*")
    sub.add_parser("inventory", help="integrity report over data/*.parquet -> output/inventory.md")
    a = sub.add_parser("archive", help="fetch Binance public-archive files into data/raw/external/binance/")
    a.add_argument("kinds", nargs="+", help="bookDepth metrics aggTrades fundingRate klines/1m …")
    a.add_argument("--symbols", nargs="*")
    a.add_argument("--start", default="2023-01-01")
    a.add_argument("--end", default=None, help="inclusive; default: two days ago")
    t = sub.add_parser("tape", help="P1: stream archive aggTrades into data/tape/<symbol>.parquet (per-minute summary); zips are not kept")
    t.add_argument("--symbols", nargs="*")
    t.add_argument("--start", default="2023-01-01")
    t.add_argument("--end", default=None, help="inclusive; default: two days ago")
    t.add_argument("--workers", type=int, default=6)
    t.add_argument("--keep-zip", action="store_true", help="keep the raw zips (only for a short validation window)")
    c = sub.add_parser("cost", help="P1: price the trade → output/cost.md, data/cost_daily.parquet, data/cost_table.parquet "
                                    "(see ft2/cost.py)")
    c.add_argument("--taker-bps", type=float, default=5.0, help="per side; default: the published VIP 0 schedule")
    c.add_argument("--maker-bps", type=float, default=2.0)
    c.add_argument("--fee-source", default="Binance USDⓈ-M published VIP 0 schedule (0.020 % maker / 0.050 % taker), "
                                           "no BNB discount — PENDING the account's tier from Vadim")
    c.add_argument("--symbols", nargs="*")
    args = p.parse_args(argv)
    return {"smoke": cmd_smoke, "ingest": cmd_ingest, "inventory": cmd_inventory,
            "archive": cmd_archive, "tape": cmd_tape, "cost": cmd_cost}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
