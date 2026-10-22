#!/usr/bin/env bash
# R66 (docs/PLAN.md §8, decision BE1, registered 2026-10-22): R65's two-rank score — cbprem_dev's rank everywhere, −bx_1h's rank added on
# the bars where BTC's last hour fell — confirmed ONCE on F3+F4's members, the sign POSITIVE, R65's gate against 0.0159. The run checks
# the lists, reproduces R65's saved F1+F2 rows through the fold-parameterised frame and R50's reference rows FIRST (a mismatch voids before
# any F3+F4 bar), appends the guard rows (R66, F3) and (R66, F4) to output/backtest/confirmation_reads.csv, then loads F3+F4 once.
#   ./fluxtrader2/scripts/vm.sh bgsh r66 'bash scripts/r66_chain.sh'      # log: output/logs/r66.log
# The step is named r66_run, not r66 (a step named like the bgsh job clobbers the chain log). The chain's exit arms a poweroff 30 min later.
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
echo "$(date -u +%H:%M:%S) R66's list md5: $(md5sum ft2/cb_members_r66.csv)"
echo "$(date -u +%H:%M:%S) F3+F4 members md5: $(md5sum ft2/screen_members_f34.csv)"
echo "$(date -u +%H:%M:%S) R62's list md5: $(md5sum ft2/cb_members_r62.csv)"
echo "$(date -u +%H:%M:%S) members md5: $(md5sum ft2/screen_members.csv)"
echo "$(date -u +%H:%M:%S) R65's saved screen: $(md5sum output/ceiling_score_members/screen.parquet)"
echo "$(date -u +%H:%M:%S) R50's reference: $(md5sum output/audit/r50_btchour/reference.csv)"
echo "$(date -u +%H:%M:%S) source: $(md5sum data/coinbase_1h_members.parquet | cut -c1-32)"
echo "$(date -u +%H:%M:%S) reads before: $(grep -c . output/backtest/confirmation_reads.csv) rows, R66 rows: $(grep -c ',R66,' output/backtest/confirmation_reads.csv || true)"
FT2_JOBS=2 step r66_run python -m ft2 ceiling --target pairs --family score --universe members_f34 --draws 200
echo "$(date -u +%H:%M:%S) reads after:  $(grep -c . output/backtest/confirmation_reads.csv) rows, R66 rows: $(grep -c ',R66,' output/backtest/confirmation_reads.csv || true)"
echo "$(date -u +%H:%M:%S) R65's saved screen after: $(md5sum output/ceiling_score_members/screen.parquet)"
echo "$(date -u +%H:%M:%S) R50's reference after: $(md5sum output/audit/r50_btchour/reference.csv)"
echo "$(date -u +%H:%M:%S) R66_CHAIN_DONE"
