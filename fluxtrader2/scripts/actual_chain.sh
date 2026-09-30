#!/usr/bin/env bash
# The re-execution `actual` (docs/PLAN.md §3): R22, R23, R24 and R25 made again by their registered commands, on the
# corrected unit of money. Runs on the work VM, in the venv, from ~/fluxtrader2:
#   ./fluxtrader2/scripts/vm.sh bgsh actual 'bash scripts/actual_chain.sh'      # log: output/logs/actual.log
# Each step writes output/logs/actual_<step>.log and, when it ends well, output/logs/actual_<step>.done; a step that is
# done is not made again (a guarded fold is read once per tag), so the chain can be started again after a failure.
set -euo pipefail
mkdir -p output/logs
step() {
  local name="$1"; shift
  if [[ -e "output/logs/actual_$name.done" ]]; then echo "$(date -u +%H:%M:%S) skip  $name (done)"; return; fi
  echo "$(date -u +%H:%M:%S) start $name: $*"
  "$@" > "output/logs/actual_$name.log" 2>&1
  touch "output/logs/actual_$name.done"
  echo "$(date -u +%H:%M:%S) done  $name"
}
ft2() { python -m ft2 "$@"; }
OIBOOK="hold=2016 k=6"

# R22 — the longer hold on R18's cells (F1+F2, exploration)
step r22 ft2 horizon r18_transferbook_1d --holds 864 2016 --name r18_transferbook_1d_actual
step r22_check python scripts/actual_check.py cells r18_transferbook_1d r18_transferbook_1d_actual

# R23 — the score at 7 days on 2021-12 → 2023-04 (FP+F0, guarded)
step r23 ft2 horizon --pre --holds 2016 --name pre_actual --reexecute actual
step r23_check python scripts/actual_check.py cells pre pre_actual

# R24 — the score as a priced book on both samples (FP+F0 guarded; F1+F2 exploration), pooled
step r24_pre ft2 backtest oibook --universe pre --folds FP F0 --registration R24 --reexecute actual --param $OIBOOK members=ft2/screen_members_pre.csv --execs taker maker --name r24_oibook_7d_pre_actual
step r24_pre_book ft2 audit r24_oibook_7d_pre_actual --book
step r24_pre_check python scripts/actual_check.py trades r24_oibook_7d_pre r24_oibook_7d_pre_actual
step r24_f12 ft2 backtest oibook --universe screen --param $OIBOOK --execs taker maker --name r24_oibook_7d_f12_actual
step r24_f12_book ft2 audit r24_oibook_7d_f12_actual --book
step r24_f12_check python scripts/actual_check.py trades r24_oibook_7d_f12 r24_oibook_7d_f12_actual
step r24_pool ft2 audit --pool r24_oibook_7d_pre_actual r24_oibook_7d_f12_actual --name r24_pool_actual
step r24_described python scripts/actual_describe.py r24_pool_actual r24_oibook_7d_pre_actual r24_oibook_7d_f12_actual

# R25 — the confirmation read of that book on F3+F4 (guarded)
step r25 ft2 backtest oibook --universe f34 --folds F3 F4 --registration R25 --reexecute actual --param $OIBOOK members=ft2/screen_members_f34.csv --execs taker maker --name r25_oibook_7d_f34_actual
step r25_book ft2 audit r25_oibook_7d_f34_actual --book
step r25_check python scripts/actual_check.py trades r25_oibook_7d_f34 r25_oibook_7d_f34_actual
step r25_read ft2 audit --pool r25_oibook_7d_f34_actual --confirm --beside r24_oibook_7d_pre_actual r24_oibook_7d_f12_actual --name r25_read_actual
step r25_described python scripts/actual_describe.py r25_read_actual r25_oibook_7d_f34_actual
echo "$(date -u +%H:%M:%S) the chain ended: every step done"
