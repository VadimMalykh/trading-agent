#!/usr/bin/env bash
# Decision BP1 (docs/PLAN.md P8): Wikipedia's daily pageviews per name — the SOURCE AUDIT's fetch half, after the article list was checked
# by hand and frozen (ft2/wiki_articles.csv, committed). A second known-at probe at this hour, the daily views per frozen article from
# 2021-12-01 (one request each, resumable), the creation stamps, the ingest to data/wiki_views.parquet, the audit (the covered bases by set,
# the members with an article per block, the DEV form within and across names). Nothing registered, no fold read, no view joined to a price.
#   ./fluxtrader2/scripts/vm.sh bgsh bp1 'bash scripts/bp1_chain.sh'      # log: output/logs/bp1.log
# The steps are named wiki_<action>, not bp1. The chain's exit arms a poweroff 30 min later.
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
echo "md5 before: $(md5sum ft2/wiki_articles.csv ft2/screen_members.csv ft2/screen_members_f34.csv | tr '\n' ' ')"
step wiki_probe2 python -m ft2 wiki probe
step wiki_fetch  python -m ft2 wiki fetch
step wiki_ingest python -m ft2 wiki ingest
step wiki_audit  python -m ft2 wiki audit
echo "md5 after:  $(md5sum ft2/wiki_articles.csv ft2/screen_members.csv ft2/screen_members_f34.csv | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) BP1_CHAIN_DONE"
