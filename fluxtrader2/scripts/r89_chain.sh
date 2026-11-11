#!/usr/bin/env bash
# R89 (docs/PLAN.md §8): the frozen trees (R87's LightGBM as R88 fitted it on F1+F2's members), scored ONCE on F5's coin members
# (guarded; `ft2 allgbm confirm5`). Nothing fetched.
#   ./fluxtrader2/scripts/vm.sh bgsh conf89 'bash scripts/r89_chain.sh'      # log: output/logs/conf89.log (the job's name differs from the step's)
# The chain's exit (done or failed) arms a poweroff 30 minutes later; `vm.sh stop` before it is fine.
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
python -c "import lightgbm, sklearn; print('lightgbm', lightgbm.__version__, 'sklearn', sklearn.__version__)"
echo "$(date -u +%H:%M:%S) lists: $(md5sum ft2/screen_members_f5.csv ft2/screen_members_f5_coins.csv ft2/f5_contract_types.csv ft2/screen_members.csv | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) data: $(md5sum data/candles_5m_archive.parquet data/funding_archive.parquet data/metrics.parquet data/perp_mix_1h.parquet | cut -c1-32 | tr '\n' ' ')"
echo "$(date -u +%H:%M:%S) ledger R89 rows before: $(grep -c ',R89,' output/backtest/confirmation_reads.csv || true); R89 header in PLAN: $(grep -c '^### R89 ' docs/PLAN.md)"
step r89_read python -u -m ft2 allgbm confirm5
echo "$(date -u +%H:%M:%S) ledger R89 rows after: $(grep -c ',R89,' output/backtest/confirmation_reads.csv || true)"
echo "$(date -u +%H:%M:%S) R89_CHAIN_DONE"
