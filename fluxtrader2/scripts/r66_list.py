"""R66's frozen list (docs/PLAN.md §8 R66, decision BE1, 2026-10-22): the audit's rows (`output/coinbase_members_audit.json`, DATA.md
`coinbase_1h_members` — one `stats` row per name with a Coinbase series, the ADJUSTED premium's sd over the audit's window 2023-05-01 →
2026-09-15) RESTRICTED to the F3+F4 members (`ft2/screen_members_f34.csv`), kept (`r66` = True) at sd ≤ 48 bps. R62's recipe on R62's
numbers — a cut on the feature's noise over the whole window, never on a label; every row equals R62's row for the same name.
`--check-r62` regenerates `ft2/cb_members_r62.csv` (every name with a series, unrestricted) the same way and diffs it against the
committed file — the recipe proven on the list R62 and R65 ran on.

    python scripts/r66_list.py [--check-r62] [--write]
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "output" / "coinbase_members_audit.json"
F34 = ROOT / "ft2" / "screen_members_f34.csv"
R62 = ROOT / "ft2" / "cb_members_r62.csv"
R66 = ROOT / "ft2" / "cb_members_r66.csv"
SD_CUT = 48.0


def build(flag: str, members_csv: Path | None = None, audit: Path = AUDIT, cut: float = SD_CUT) -> pd.DataFrame:
    a = json.loads(audit.read_text())
    sd = {r["symbol"]: r["sd"] for r in a["stats"] if r["premium"] == "adj"}
    names = sorted(sd)
    if members_csv is not None:
        keep = set(pd.read_csv(members_csv, usecols=["symbol"])["symbol"].astype(str))
        names = [s for s in names if s in keep]
    df = pd.DataFrame({"symbol": names, "sd_adj_bps": [round(float(sd[s]), 2) if sd[s] is not None else float("nan") for s in names]})
    df[flag] = (df["sd_adj_bps"] <= cut).fillna(False)
    return df


def text(df: pd.DataFrame) -> str:
    return df.to_csv(index=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-r62", action="store_true", help="regenerate R62's list (every name with a series) and diff it against the committed file")
    ap.add_argument("--write", action="store_true", help="write ft2/cb_members_r66.csv (refused if it exists)")
    args = ap.parse_args()
    if args.check_r62:
        got, want = text(build("r62")), R62.read_text()
        print(f"R62's list regenerated: {'IDENTICAL' if got == want else 'DIFFERS'} ({len(got.splitlines()) - 1} rows against {len(want.splitlines()) - 1})")
        if got != want:
            import difflib
            print("".join(list(difflib.unified_diff(want.splitlines(True), got.splitlines(True), "committed", "regenerated"))[:40]))
            raise SystemExit(1)
    df = build("r66", F34)
    s = text(df)
    r62 = pd.read_csv(R62).set_index("symbol")
    same = all(((r62.loc[r.symbol, "sd_adj_bps"] == r.sd_adj_bps) or (pd.isna(r62.loc[r.symbol, "sd_adj_bps"]) and pd.isna(r.sd_adj_bps)))
               and bool(r62.loc[r.symbol, "r62"]) == bool(r.r66) for r in df.itertuples())
    f34 = set(pd.read_csv(F34, usecols=["symbol"])["symbol"].astype(str))
    print(f"R66: {len(df)} of the {len(f34)} F3+F4 members have a Coinbase series; {int(df['r66'].sum())} kept at sd ≤ {SD_CUT:g}, {int((~df['r66']).sum())} thin; "
          f"every row equal to R62's row for the name: {same}; md5 {hashlib.md5(s.encode()).hexdigest()}")
    if args.write:
        if R66.exists():
            raise SystemExit(f"{R66} exists: the list is frozen with the registration — not rewritten")
        R66.write_text(s)
        print(f"wrote {R66}")


if __name__ == "__main__":
    main()
