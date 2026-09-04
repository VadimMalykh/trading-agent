"""M3 — the trading policy: offline backtesting over M2's prediction dumps.

Everything here runs in the torch-free `ml_analysis` container (see scripts/m3.sh); it
reads `eval_preds.parquet` and never touches the DB, a checkpoint or a GPU. The plan this
implements is docs/M3_PLAN.md; §0.0 of that file is the live status block.

Layout:
    dumps.py     load and pool the per-seed prediction dumps
    regime.py    rebuild the Q1 regime observables from the dumps themselves
    backtest.py  the event-driven policy simulator
    metrics.py   P&L / drawdown / Sharpe / calendar-window reporting
    features.py  the M3-3 observation vector, the candidate pool and the LOWO folds
    learn.py     M3-3's ridge fits, the out-of-fold scoring and the write-up
    walkforward.py  the walk-forward folds: WALKFORWARD_PROTOCOL §3's five criteria
    validate.py  the acceptance tests — run these before believing any policy number
    cli.py       `python -m m3 <subcommand>`
"""
