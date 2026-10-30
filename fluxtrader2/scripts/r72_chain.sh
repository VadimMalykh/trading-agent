#!/usr/bin/env bash
# R72 (docs/PLAN.md §8, registered 2026-10-30 on Vadim's "BQ1"): the attention screen — R62's screen on the deviation of the article's
# Wikipedia pageviews from their trailing month, on the screener's F1+F2 members with a STRICT article (38 names from the two frozen
# files), ONE cell (relative, 1d), the sign NEGATIVE, both nulls at 200 draws; validity (1)–(6) first. The stamp (36 h / 48 h) was set by
# the two UTC-morning probes and written into DATA.md BEFORE this chain; the parquet is NOT re-fetched.
#   ./fluxtrader2/scripts/vm.sh bgsh r72 'bash scripts/r72_chain.sh'      # log: output/logs/r72.log
# The step is named r72_run, not r72 (a step named like the bgsh job clobbers the chain log). The chain's exit arms a poweroff 30 min later.
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
fingerprint() { python - <<'EOF'
import pandas as pd
d = pd.read_parquet("data/wiki_views.parquet")
lag = sorted({float(x) for x in ((pd.DatetimeIndex(d["ts_known"]) - pd.DatetimeIndex(d["day"])) / pd.Timedelta("1h")).unique()})
print(f"rows {len(d)} symbols {d['symbol'].nunique()} articles {d['article'].nunique()} days {d['day'].min().date()} → {d['day'].max().date()} views_sum {int(d['views'].sum())} stamp_h {lag}")
EOF
}
echo "$(date -u +%H:%M:%S) lists: $(md5sum ft2/wiki_articles.csv ft2/screen_members.csv ft2/screen_members_f34.csv ft2/cb_members_r62.csv | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) parquet before: $(fingerprint)"
echo "$(date -u +%H:%M:%S) R62's saved screen: $(md5sum output/ceiling_coinbase_members/screen.parquet)"
echo "$(date -u +%H:%M:%S) R60's saved bars: $(md5sum output/ceiling_coinbase/move_vs_cost.parquet)"
echo "$(date -u +%H:%M:%S) sources: $(md5sum data/wiki_views.parquet data/coinbase_1h_members.parquet | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) code: $(md5sum ft2/wiki_ext.py ft2/wiki.py ft2/cb_ext.py ft2/hold_ext.py | cut -c1-32 | tr '\n' ' ') KNOWN_AT_H=$(grep -o '^KNOWN_AT_H = [0-9]*' ft2/wiki.py)"
echo "$(date -u +%H:%M:%S) probes: $(ls data/raw/external/wikipedia/probe_*.json | tr '\n' ' ')"
FT2_JOBS=2 step r72_run python -m ft2 ceiling --target pairs --family wiki --universe members --draws 200
echo "$(date -u +%H:%M:%S) lists after: $(md5sum ft2/wiki_articles.csv ft2/screen_members.csv ft2/screen_members_f34.csv | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) parquet after: $(fingerprint)"
echo "$(date -u +%H:%M:%S) after: $(md5sum output/ceiling_coinbase_members/screen.parquet output/ceiling_coinbase/move_vs_cost.parquet data/wiki_views.parquet | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) R72_CHAIN_DONE"
