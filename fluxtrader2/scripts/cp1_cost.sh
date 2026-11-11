#!/usr/bin/env bash
# Decision CP1 (2026-11-11), the Data line: the candle-proxy cost rows (`ft2 costwide`) of F5's 137 coin members from 2025-07-01, MERGED
# into data/cost_daily_wide.parquet (every old row kept, overlapping rows identical or VOID — scripts/costwide_merge.py). No fill, no
# forecast, no priced trade.
#   ./fluxtrader2/scripts/vm.sh bgsh cp1line 'bash scripts/cp1_cost.sh'      # log: output/logs/cp1line.log
# The chain's exit arms a poweroff 30 minutes later.
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
NAMES=$(python - <<'PY'
import pandas as pd
print(" ".join(sorted(set(pd.read_csv("ft2/screen_members_f5_coins.csv")["symbol"]))))
PY
)
echo "$(date -u +%H:%M:%S) names: $(echo $NAMES | wc -w); cost file before: $(md5sum data/cost_daily_wide.parquet | cut -c1-32)"
cp -n data/cost_daily_wide.parquet data/cost_daily_wide_before_cp1.parquet || true
step cp1_costwide python -u -m ft2 costwide --symbols $NAMES --start 2025-07-01
step cp1_merge    python scripts/costwide_merge.py data/cost_daily_wide_before_cp1.parquet data/cost_daily_wide.parquet data/cost_daily_wide.parquet
python - <<'PY'
import pandas as pd
d = pd.read_parquet("data/cost_daily_wide.parquet"); d["symbol"] = d["symbol"].astype(str)
n = set(pd.read_csv("ft2/screen_members_f5_coins.csv")["symbol"])
x = d[d["symbol"].isin(n) & (d["day"] >= "2026-01-01") & (d["day"] < "2026-09-15")]
print(f"F5 coin names with 2026 cost rows: {x['symbol'].nunique()} of {len(n)}; rows {len(x)}; without: {sorted(n - set(x['symbol']))}")
PY
echo "$(date -u +%H:%M:%S) cost file after: $(md5sum data/cost_daily_wide.parquet | cut -c1-32)"
echo "$(date -u +%H:%M:%S) CP1_COST_DONE"
