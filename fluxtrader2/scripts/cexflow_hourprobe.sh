#!/usr/bin/env bash
# The hour probe of decision CK1 (iii): WHEN does a day's 00:00 UTC point appear in DefiLlama's Binance adapter?
# Fetches the file to a sibling folder (so `ft2 cexflow knownat`'s "two newest" glob never sees it), prints the fetch hour,
# the newest 00:00 stamp and the live stamp, and appends one row to output/cexflow/hourprobe.csv. Keyless, ≈ 6 s, from the laptop.
# Run at the hours the registration asks (06:00 and 12:00 UTC on one day; the first rows are the audit's and this session's fetches).
set -euo pipefail
cd "$(dirname "$0")/.."
NOW=$(date -u +%Y%m%dT%H%MZ)
DIR=data/raw/external/defillama_cex_hourprobe; mkdir -p "$DIR" output/cexflow
F="$DIR/binance-cex_${NOW}.json"
curl -sS -A ft2-probe/0.1 -o "$F" https://api.llama.fi/protocol/binance-cex
python3 - "$F" "$NOW" <<'PY'
import json, sys, datetime as dt, pathlib
f, now = sys.argv[1], sys.argv[2]
d = json.load(open(f))
stamps = set()
for ch, v in d["chainTvls"].items():
    if ch.endswith("-staking") or ch.endswith("-borrowed"): continue
    for r in v.get("tokens", []): stamps.add(int(r["date"]))
daily = max(s for s in stamps if s % 86400 == 0); live = max(stamps)
u = lambda s: dt.datetime.fromtimestamp(s, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
row = f"{now},{u(daily)},{u(live) if live != daily else ''},{pathlib.Path(f).name}"
p = pathlib.Path("output/cexflow/hourprobe.csv")
if not p.exists(): p.write_text("fetch_utc,newest_daily_stamp,live_stamp,file\n")
p.open("a").write(row + "\n"); print(row)
PY
