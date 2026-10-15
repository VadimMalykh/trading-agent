"""R41 validity (5): `premium.parquet` is rewritten whole by the ingest that adds the twelve, so the members' rows must come back identical.
  python scripts/r41_premium_check.py before   → output/logs/r41_premium_fingerprint.json (per symbol: rows, the premium's sum, first, last)
  python scripts/r41_premium_check.py after    → compares every symbol of the `before` file; prints the symbols added; exit 2 on any difference."""
import json
import sys
from pathlib import Path

import pandas as pd

FP = Path("output/logs/r41_premium_fingerprint.json")
OUT = Path("output/logs/r41_premium_check.json")


def fingerprint() -> dict:
    df = pd.read_parquet("data/premium.parquet")
    df["symbol"] = df["symbol"].astype(str)
    g = df.groupby("symbol").agg(rows=("premium", "size"), total=("premium", "sum"), first=("open_time", "min"), last=("open_time", "max"))
    return {s: {"rows": int(r.rows), "total": float(r.total), "first": str(r.first), "last": str(r.last)} for s, r in g.iterrows()}


def main(mode: str) -> int:
    fp = fingerprint()
    if mode == "before":
        FP.parent.mkdir(parents=True, exist_ok=True)
        FP.write_text(json.dumps(fp, indent=1))
        print(f"before: {len(fp)} symbols, {sum(v['rows'] for v in fp.values()):,} rows → {FP}")
        return 0
    before = json.loads(FP.read_text())
    bad = {s: (before[s], fp.get(s)) for s in before if fp.get(s) is None or fp[s]["rows"] != before[s]["rows"] or abs(fp[s]["total"] - before[s]["total"]) > 1e-9 * max(1.0, abs(before[s]["total"]))
           or fp[s]["first"] != before[s]["first"] or fp[s]["last"] != before[s]["last"]}
    added = sorted(set(fp) - set(before))
    res = {"status": "PASS" if not bad else "FAIL", "symbols_before": len(before), "symbols_after": len(fp), "added": {s: fp[s] for s in added},
           "differences": {s: {"before": a, "after": b} for s, (a, b) in bad.items()}}
    OUT.write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))
    return 0 if not bad else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
