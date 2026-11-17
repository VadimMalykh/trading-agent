#!/usr/bin/env bash
# Decision CW1 (2026-11-17), step (i) + (ii): the Data line for the NEXT SIXTY (ft2/screen_next60_*.csv; F5's PERPETUAL rows), the
# features-only cover of the four lists, then the candle-proxy cost rows. No label, no forecast, no IC anywhere in this chain
# (ft2/next60data.py; `allgbm.cover` with a list as the members; `ft2 costwide`).
#   ./fluxtrader2/scripts/vm.sh bgsh cw1line 'bash scripts/cw1_data.sh'      # log: output/logs/cw1line.log (the job's name differs from the steps')
# The chain's exit (done or failed) arms a poweroff 30 minutes later; kill the `sudo poweroff` wrapper first if another chain follows.
set -euo pipefail
mkdir -p output/logs
trap 'nohup bash -c "sleep 1800; sudo poweroff" > /dev/null 2>&1 &' EXIT
step() {
  local name="$1"; shift
  if [[ -e "output/logs/$name.done" ]]; then echo "$(date -u +%H:%M:%S) skip  $name (done)"; return; fi
  echo "$(date -u +%H:%M:%S) start $name: $*"
  "$@" > "output/logs/$name.log" 2>&1
  touch "output/logs/$name.done"
  echo "$(date -u +%H:%M:%S) done  $name"
}
FILES="data/candles_5m_archive.parquet data/funding_archive.parquet data/metrics.parquet data/perp_mix_1h.parquet data/cost_daily_wide.parquet"
echo "$(date -u +%H:%M:%S) lists: $(md5sum ft2/screen_next60_pre.csv ft2/screen_next60_f12.csv ft2/screen_next60_f34.csv ft2/screen_next60_f5.csv ft2/screen_next60_f5_coins.csv | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) md5 before: $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
df -h --output=avail . | tail -1
step n60_plan    python -u -m ft2 next60data plan
step n60_klines  python -u -m ft2 next60data klines
step n60_funding python -u -m ft2 next60data funding
step n60_metrics python -u -m ft2 next60data metrics
step n60_mix     python -u -m ft2 next60data mix
echo "$(date -u +%H:%M:%S) md5 after:  $(md5sum $FILES | cut -c1-32 | tr '\n' ' ')"
df -h --output=avail . | tail -1
step n60_cover_pre python -u -m ft2 next60data cover --seg pre
step n60_cover_f5  python -u -m ft2 next60data cover --seg f5
step n60_cover_f12 python -u -m ft2 next60data cover --seg f12
step n60_cover_f34 python -u -m ft2 next60data cover --seg f34
# the cost rows: `costwide` writes its parquet whole for the names given; merged into the table it replaced (overlapping rows identical or VOID)
NAMES=$(python -c 'from ft2 import next60data as n; print(" ".join(n.names()))')
echo "$(date -u +%H:%M:%S) cost names: $(echo $NAMES | wc -w); cost file before: $(md5sum data/cost_daily_wide.parquet | cut -c1-32)"
cp -n data/cost_daily_wide.parquet data/cost_daily_wide_before_cw1.parquet || true
step n60_costwide python -u -m ft2 costwide --symbols $NAMES --start 2021-12-01
step n60_costmerge python scripts/costwide_merge.py data/cost_daily_wide_before_cw1.parquet data/cost_daily_wide.parquet data/cost_daily_wide.parquet
python - <<'PY'
import pandas as pd
from ft2 import next60data as n
d = pd.read_parquet("data/cost_daily_wide.parquet", columns=["symbol", "day"]); d["symbol"] = d["symbol"].astype(str); d["day"] = pd.to_datetime(d["day"], utc=True)
R = n.rows()
days = {s: set(g) for s, g in d[d["symbol"].isin(set(R["symbol"]))].groupby("symbol")["day"]}
R["share"] = [sum(x in days.get(r.symbol, ()) for x in pd.date_range(r.a.floor("D"), r.b - pd.Timedelta(seconds=1), freq="D")) / max(len(pd.date_range(r.a.floor("D"), r.b - pd.Timedelta(seconds=1), freq="D")), 1) for r in R.itertuples(index=False)]
for seg, g in R.groupby("seg"):
    print(f"cost rows, {seg}: {len(g)} list rows, {(g['share'] >= 0.95).sum()} with ≥ 95 % of the block's days priced, {(g['share'] == 0).sum()} with none; names without any: {sorted(set(g.loc[g['share'] == 0, 'symbol']))[:30]}")
PY
echo "$(date -u +%H:%M:%S) cost file after: $(md5sum data/cost_daily_wide.parquet | cut -c1-32)"
echo "$(date -u +%H:%M:%S) CW1_DATA_DONE"
