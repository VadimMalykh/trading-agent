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


def cmd_ingest(args):
    from . import data
    slices = args.slices or [s for s in data.SLICES if (data.RAW / f"{s}.csv.gz").exists()]
    for s in slices:
        r = data.ingest_metrics(PAIRS) if s == "metrics" else data.ingest(s)
        print(f"{r['slice']:<12} rows_in={r['rows_in']:>10,} dups={r['dups_dropped']:>6,} "
              f"rows_out={r['rows_out']:>10,}  {r['first']} .. {r['last']}")


def cmd_inventory(args):
    from . import inventory
    print(inventory.run())


PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT",
         "DOGEUSDT", "ZECUSDT", "1000PEPEUSDT", "WLDUSDT", "HYPEUSDT"]


def cmd_archive(args):
    from . import archive
    archive.main(args.kinds, args.symbols or PAIRS, args.start, args.end)


def main(argv=None):
    p = argparse.ArgumentParser(prog="ft2")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("smoke", help="import every dependency and print versions")
    i = sub.add_parser("ingest", help="raw csv.gz -> parquet (all present slices, or the named ones)")
    i.add_argument("slices", nargs="*")
    sub.add_parser("inventory", help="integrity report over data/*.parquet -> output/inventory.md")
    a = sub.add_parser("archive", help="fetch Binance public-archive files into data/raw/external/binance/")
    a.add_argument("kinds", nargs="+", help="bookDepth metrics aggTrades fundingRate klines/1m …")
    a.add_argument("--symbols", nargs="*")
    a.add_argument("--start", default="2023-01-01")
    a.add_argument("--end", default=None, help="inclusive; default: two days ago")
    args = p.parse_args(argv)
    return {"smoke": cmd_smoke, "ingest": cmd_ingest, "inventory": cmd_inventory,
            "archive": cmd_archive}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
