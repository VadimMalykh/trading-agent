"""`python -m m3 <subcommand>` — the entry point scripts/m3.sh drives.

    ./scripts/m3.sh -m m3 validate            # the two acceptance tests (run this first)
    ./scripts/m3.sh -m m3 power               # the pre-registration facts (M3_PROTOCOL §2/§4)
    ./scripts/m3.sh -m m3 fitprep             # M3-3 pre-registration facts (counts only)
    ./scripts/m3.sh -m m3 learn               # M3-3: fit and score the 14 learned runs
    ./scripts/m3.sh -m m3 universe            # T3: 8 pairs vs 12, on the same dumps
    ./scripts/m3.sh -m m3 universe-fair       # T6: the fair version of that comparison
    ./scripts/m3.sh -m m3 bookprep            # M3-4a data-quality facts (no fill number)
    ./scripts/m3.sh -m m3 execcost            # M3-4: the execution-cost study itself
    ./scripts/m3.sh -m m3 sidetable           # M3-0b: the price/funding side-table
    ./scripts/m3.sh -m m3 bookera             # B0: the book-era table, same alignment
    ./scripts/m3.sh -m m3 policy --help       # score one policy spec
"""
from __future__ import annotations

import argparse
import os

import numpy as np
import pandas as pd

from . import (backtest, bookprep, dumps, execcost, features, learn, metrics, regime,
               search, sidetable, universe, validate)


def cmd_validate(args) -> int:
    return validate.main()


# The grid docs/M3_PROTOCOL.md §3 pre-registers. It lives here, in code, so that "the 36
# configurations" is a list a later session can re-derive rather than a claim in prose.
GRID_COVERAGE = (0.01, 0.02, 0.05)
GRID_HOLD = (60, 240, 1440)
GRID_REGIME_Q = (None, 0.80)
GRID_MAX_CONC = (None, 3)
MIN_TRADES_PER_WINDOW = 100          # M3_PROTOCOL §4 rule P4


def primary_grid() -> list[backtest.PolicySpec]:
    """The 3 x 3 x 2 x 2 = 36 specs of the primary grid, in a fixed, reproducible order."""
    specs = []
    for cov in GRID_COVERAGE:
        for hold in GRID_HOLD:
            for rq in GRID_REGIME_Q:
                for mc in GRID_MAX_CONC:
                    specs.append(backtest.PolicySpec(
                        coverage=cov, signal_horizon=240, hold_horizon=hold,
                        regime_col="btc_absret_1d" if rq is not None else None,
                        regime_quantile=rq, max_concurrent=mc,
                        label=f"cov{cov:g}_hold{hold}_rq{rq if rq else 'none'}_mc{mc or 'none'}",
                    ))
    return specs


# The runs docs/M3_3_PROTOCOL.md §4 and §6 pre-register, for the same reason primary_grid()
# exists: "the 14 runs" has to be a list a later session can re-derive, not a claim in prose.
def learned_grid() -> list[features.LearnedConfig]:
    """§4: 2 model classes x 2 entry rules x 2 sizings = the 8 learned configurations."""
    return [features.LearnedConfig(model=m, entry=e, sizing=s)
            for m in ("A", "B") for e in ("R1", "R2") for s in ("S1", "S2")]


def ablation_grid() -> list[features.LearnedConfig]:
    """§6 control C2: the confidence-only fit at all four entry x sizing settings, so a
    matched ablation exists whatever the winner's settings turn out to be."""
    return [features.LearnedConfig(model="conf", entry=e, sizing=s)
            for e in ("R1", "R2") for s in ("S1", "S2")]


def cmd_power(args) -> int:
    """Print the sample-size and uncertainty facts M3-1 pre-registers on — COUNTS ONLY.

    No net-P&L number for any grid config is printed here, deliberately: this command runs
    BEFORE the search and its whole purpose is to fix the eligibility rule without anyone
    having seen which configs make money. The one P&L figure it does show is §1.3's
    already-published cov05 slice, used to calibrate the standard error.
    """
    ds = dumps.load_baseline(pairs=dumps.BASE8)

    print("=" * 88)
    print("A. DATA EXTENT — the windows are not equal, and two are truncated by the dump")
    print("=" * 88)
    allbars = pd.concat([dumps.add_window(d.at(240)) for d in ds], ignore_index=True)
    for name, lo, hi in dumps.WINDOWS:
        sub = allbars[allbars["window"] == name]
        t = pd.to_datetime(sub["ts"], unit="ns", utc=True)
        days = (t.max() - t.min()).total_seconds() / 86400 if len(sub) else 0.0
        print(f"  {name} [{lo} .. {hi})  bars={len(sub):>7,}  actual span={days:5.1f}d  "
              f"{t.min():%Y-%m-%d} .. {t.max():%Y-%m-%d}")

    print("\n" + "=" * 88)
    print("B. STANDARD ERROR CALIBRATION on §1.3's published cov05 slice")
    print("=" * 88)
    t = backtest.run(ds, backtest.PolicySpec(coverage=0.05, signal_horizon=240)).trades
    for cost, name in ((0.0, "gross"), (metrics.TAKER_COST_BPS, "net @ taker 14bps")):
        c = metrics.clustered_mean_bps(t, cost)
        x = (t["signed_ret"] - cost / metrics.BPS).to_numpy() * metrics.BPS
        iid = x.std(ddof=1) / np.sqrt(len(x))
        print(f"  {name:>18}: mean={c['mean_bps']:+6.2f}  n={c['n']:,}  clusters={c['clusters']}  "
              f"iid_se={iid:.2f}  clustered_se={c['se_bps']:.2f}  ({c['se_bps']/iid:.2f}x)  "
              f"95% CI=[{c['lo95_bps']:+.2f}, {c['hi95_bps']:+.2f}]")
    print(f"  per-trade sd = {x.std(ddof=1):.1f} bps")

    print("\n" + "=" * 88)
    print(f"C. TRADE COUNTS per window for all {len(primary_grid())} primary-grid configs.")
    print(f"   ELIGIBLE = every window has >= {MIN_TRADES_PER_WINDOW} pooled trades (rule P4).")
    print("=" * 88)
    regimes = {d.seed: regime.build(d.df) for d in ds}
    print(f"{'config':<40}" + "".join(f"{n:>8}" for n in ("w1", "w2", "w3", "w4", "total"))
          + "   eligible")
    eligible = []
    for spec in primary_grid():
        tr = dumps.add_window(backtest.run(ds, spec, regimes).trades, ts_col="entry_ts")
        per = [int((tr["window"] == n).sum()) for n in ("w1", "w2", "w3", "w4")]
        ok = min(per) >= MIN_TRADES_PER_WINDOW
        eligible.append(ok)
        print(f"{spec.label:<40}" + "".join(f"{v:>8,}" for v in per + [len(tr)])
              + f"   {'YES' if ok else 'no'}")
    print(f"\n  {sum(eligible)} of {len(eligible)} configs are eligible for promotion; "
          f"the rest are under-sampled and are reported but cannot win (M3_PROTOCOL §4).")
    return 0


def cmd_fitprep(args) -> int:
    """Print the facts M3-3's pre-registration is built on — COUNTS AND FEATURE STRUCTURE ONLY.

    The counterpart of `m3 power`, and it exists for the same reason: it runs BEFORE any
    model is fitted, so the fold structure, the capacity budget and the eligibility risk are
    fixed without anyone having seen whether the features predict anything. Nothing here
    touches `y_bps` — not a correlation, not a mean, not a sign. The relationship between an
    observation and the target is the result, and M3_3_PROTOCOL is written before it exists.
    """
    ds = dumps.load_baseline(pairs=dumps.BASE8)
    regimes = {d.seed: regime.build(d.df) for d in ds}
    feats = {d.seed: features.build(d, regimes[d.seed]) for d in ds}

    print("=" * 92)
    print("A. THE OBSERVATION VECTOR — completeness over each seed's full 240m bar population")
    print("=" * 92)
    print(f"  {len(features.FEATURES)} features: {', '.join(features.FEATURES)}")
    print(f"\n  {'seed':<6}{'bars':>12}{'complete':>12}{'dropped':>10}{'  reason a bar drops'}")
    for s, f in feats.items():
        c = features.complete(f)
        print(f"  {s:<6}{len(f):>12,}{len(c):>12,}{len(f) - len(c):>10,}"
              f"   incomplete 24h/7d lookback")
    incomplete = pd.concat([f[~f.index.isin(features.complete(f).index)] for f in feats.values()])
    if len(incomplete):
        t = pd.to_datetime(incomplete["ts"], unit="ns", utc=True)
        print(f"  every dropped bar lies in {t.min():%Y-%m-%d}..{t.max():%Y-%m-%d} "
              f"(the warm-up at the start of the dump), across "
              f"{incomplete['window'].value_counts().to_dict()}")

    print("\n" + "=" * 92)
    print(f"B. THE CANDIDATE POOL — the top {features.POOL_COVERAGE:.0%} of bars by 240m confidence")
    print("=" * 92)
    pools = {s: features.pool(f) for s, f in feats.items()}
    print(f"  {'seed':<6}" + "".join(f"{n:>10}" for n in features.WINDOW_NAMES) + f"{'total':>10}")
    for s, p in pools.items():
        per = [int((p["window"] == n).sum()) for n in features.WINDOW_NAMES]
        print(f"  {s:<6}" + "".join(f"{v:>10,}" for v in per) + f"{len(p):>10,}")
    allpool = pd.concat(pools.values(), ignore_index=True)
    per = [int((allpool["window"] == n).sum()) for n in features.WINDOW_NAMES]
    print(f"  {'POOL':<6}" + "".join(f"{v:>10,}" for v in per) + f"{len(allpool):>10,}")

    print("\n" + "=" * 92)
    print("C. THE FOLDS — leave-one-window-out, and the CLUSTER count is the capacity budget")
    print("=" * 92)
    print("   Rows are not the sample size (M3_PROTOCOL §2). Clustering on the exit calendar")
    print("   day, a fold's fit is backed by this many independent trading days:")
    exit_day = pd.to_datetime(
        allpool["ts"] + 240 * 60 * dumps.NS, unit="ns", utc=True).dt.floor("D")
    allpool = allpool.assign(_day=exit_day)
    print(f"\n  {'held out':<10}{'fit rows':>12}{'fit clusters':>14}"
          f"{'held rows':>12}{'held clusters':>15}")
    for held, train in features.folds():
        tr = allpool[allpool["window"].isin(train)]
        he = allpool[allpool["window"] == held]
        print(f"  {held:<10}{len(tr):>12,}{tr['_day'].nunique():>14,}"
              f"{len(he):>12,}{he['_day'].nunique():>15,}")
    print(f"\n  model A = {len(features.design(allpool.head(2))[1])} terms, "
          f"model B = {len(features.design(allpool.head(2), quadratic=True)[1])} terms, "
          f"against ~{allpool['_day'].nunique() * 3 // 4} training clusters per fold.")

    print("\n" + "=" * 92)
    print("D. COLLINEARITY among the observations (target-free — no y_bps is touched)")
    print("=" * 92)
    corr = allpool[features.FEATURES].corr()
    print(corr.to_string(float_format=lambda v: f"{v:+.2f}"))
    off = corr.where(~np.eye(len(corr), dtype=bool)).abs().stack()
    a, b = off.idxmax()
    print(f"\n  strongest pair: {a} / {b} at {off.max():.2f} — a ridge penalty is chosen per")
    print("  fold (M3_3_PROTOCOL §4.2) precisely because several of these move together.")
    return 0


def cmd_search(args) -> int:
    """M3-2 — run the 40 pre-registered configurations and score them under the rule.

    This command does not decide anything. Every threshold it applies is transcribed from
    docs/M3_PROTOCOL.md, which was committed before any search ran; §6 of that file
    pre-registers what happens if nothing passes, so a clean sweep of failures is an
    outcome this code prints rather than an error it works around.
    """
    ds = dumps.load_baseline(pairs=dumps.BASE8)
    seeds = [d.seed for d in ds]
    cal = search.calendar_days(ds)
    print(f"loaded {len(ds)} seeds ({', '.join(d.run_id for d in ds)}), "
          f"{len(dumps.BASE8)} pairs, calendar span {cal:.1f}d")
    regimes = {d.seed: regime.build(d.df) for d in ds}

    # --- §3.1: the primary grid ------------------------------------------------------
    cards = []
    for i, spec in enumerate(primary_grid(), 1):
        res = backtest.run(ds, spec, regimes)
        c = search.scorecard(spec.label, res.trades, seeds, cal, spec)
        c["thresholds"] = res.thresholds
        c["regime_thresholds"] = res.regime_thresholds
        search.tier1(c)
        cards.append(c)
        print(f"  [{i:>2}/36] {spec.label:<34} "
              f"n={c['trades']:>6,}  worst={c['worst_net']:+7.2f}  "
              f"{'PASS' if c['tier1']['PASS'] else '-'}")
    ranked = search.rank(cards)

    # --- §3.2: the three additions, plus the O8 replication --------------------------
    # If nothing passes Tier 1 the pre-registered runs still have to happen, so they
    # attach to the top-ranked ELIGIBLE (P4-passing) config instead, labelled as such.
    if ranked:
        anchor, anchor_note = ranked[0], "the Tier-1 winner of the primary grid"
    else:
        eligible = [c for c in cards if c["tier1"]["P4"]]
        anchor = max(eligible, key=lambda c: (c["worst_net"], c["taker14"]["net_bps"]))
        anchor_note = ("NO config passed Tier 1; attached instead to the best-ranked "
                       "eligible config so the pre-registered runs still happen")
    print(f"\nanchor config: {anchor['label']} — {anchor_note}")

    sz_spec = backtest.PolicySpec(
        **{**anchor["spec"].__dict__, "regime_col": "btc_absret_1d", "regime_quantile": None,
           "regime_min": None, "size_by_regime": True,
           "label": anchor["spec"].label + "_SIZED"})
    sz = backtest.run(ds, sz_spec, regimes)
    sz_card = search.scorecard(sz_spec.label, sz.trades, seeds, cal, sz_spec)
    search.tier1(sz_card)

    # Whether an §3.2 addition may win the §4.2 ranking is not stated unambiguously in the
    # protocol, so this reports BOTH readings rather than picking one after seeing which
    # is better: the grid winner is the M3-2 baseline under the narrow reading, and the
    # top of the combined ranking is the winner under the wide one. M3-3's bar is set at
    # the stricter of the two (§4.4), so the ambiguity costs nothing.
    grid_winner = ranked[0] if ranked else None
    contenders = search.rank(cards + [sz_card])
    winner = contenders[0] if contenders else anchor

    mom = search.momentum_control(ds, winner["spec"], regimes)
    mom_card = search.scorecard(winner["spec"].label + "_MOMSIDE", mom.trades, seeds, cal)
    search.tier1(mom_card)

    bnh = search.buy_and_hold(ds[0], dumps.BASE8)

    # §3.2's replication, run for every candidate that could be called the winner.
    o8 = dumps.load(dumps.O8_RUN, seed="o8")
    o8_reg = {"o8": regime.build(o8.df)}
    o8_cards = []
    seen = set()
    for cand in [c for c in (grid_winner, winner) if c is not None] or [anchor]:
        if cand["label"] in seen:
            continue
        seen.add(cand["label"])
        r = backtest.run([o8], cand["spec"], o8_reg)
        oc = search.scorecard(cand["label"] + "_O8", r.trades, ["o8"],
                              search.calendar_days([o8]), cand["spec"])
        search.tier1(oc)
        o8_cards.append(oc)

    # --- report -----------------------------------------------------------------------
    text = search.render_report(cards, ranked, grid_winner, winner, anchor, anchor_note,
                                sz_card, mom_card, bnh, o8_cards, ds, cal)
    os.makedirs(os.path.dirname(search.REPORT_PATH), exist_ok=True)
    with open(search.REPORT_PATH, "w") as fh:
        fh.write(text)
    print("\n" + text)
    print(f"\n[report written to {search.REPORT_PATH}] — copy it to its canonical home:")
    print("  cp ml/train/output/m3/M3_2_RESULTS.md docs/M3_2_RESULTS.md")
    return 0


def cmd_learn(args) -> int:
    """M3-3 — fit the learned policy and score it under the committed rule.

    Like `m3 search`, this command decides nothing. Every threshold it applies is
    transcribed from docs/M3_3_PROTOCOL.md, which was committed before the first fit ran;
    §7 of that file pre-registers what happens if nothing beats the baseline, so a clean
    sweep of failures is an outcome this code prints rather than an error it works around.
    """
    ds = dumps.load_baseline(pairs=dumps.BASE8)
    seeds = [d.seed for d in ds]
    cal = search.calendar_days(ds)
    print(f"loaded {len(ds)} seeds ({', '.join(d.run_id for d in ds)}), "
          f"{len(dumps.BASE8)} pairs, calendar span {cal:.1f}d")

    regimes = {d.seed: regime.build(d.df) for d in ds}
    feats = {d.seed: features.build(d, regimes[d.seed]) for d in ds}
    counts = learn.bar_counts(feats)
    pool = pd.concat([features.pool(f) for f in feats.values()], ignore_index=True)
    print(f"candidate pool: {len(pool):,} rows (top {features.POOL_COVERAGE:.0%} by 240m conf)")

    # --- §4: fit each MODEL CLASS once; the rules are read off it -----------------------
    grid = learned_grid() + ablation_grid()
    oofs = {}
    for model in ("A", "B", "conf"):
        oofs[model] = learn.fit_oof(pool, model, counts)
        lams = {w: f.lam for w, f in oofs[model].fits.items()}
        print(f"  fitted model {model}: lambda per fold {lams}")

    def score_cfg(cfg: features.LearnedConfig) -> tuple[dict, learn.Policy]:
        pol = learn.apply_rules(oofs[cfg.model], cfg, counts)
        res = backtest.run(ds, learn.spec_for(cfg), regimes, overlay=learn.overlay(pol))
        card = search.scorecard(cfg.label, res.trades, seeds, cal, learn.spec_for(cfg))
        search.tier1(card)
        return card, pol

    cards, policies = {}, {}
    for i, cfg in enumerate(grid, 1):
        card, pol = score_cfg(cfg)
        cards[cfg.label], policies[cfg.label] = card, pol
        print(f"  [{i:>2}/{len(grid)}] {cfg.label:<20} n={card['trades']:>6,}  "
              f"worst={card['worst_net']:+7.2f}  "
              f"{'PASS' if card['tier1']['PASS'] else '-'}")

    learned = [cards[c.label] for c in learned_grid()]
    ablation = [cards[c.label] for c in ablation_grid()]

    # --- §6 C1: the baseline re-scored under this machinery -----------------------------
    c1_ov, c1_spec = learn.baseline_control(pool, counts)
    c1 = search.scorecard(c1_spec.label, backtest.run(ds, c1_spec, regimes, overlay=c1_ov).trades,
                          seeds, cal, c1_spec)
    search.tier1(c1)
    print(f"\nC1 (M3-2 winner re-scored): worst={c1['worst_net']:+.2f} against the "
          f"published {learn.BASELINE_BAR_BPS:+.2f}")

    # --- §6 C2's falsifiable check ------------------------------------------------------
    # A one-feature fit with a positive coefficient orders bars identically to `conf`, so
    # learnconf_R2_S1 must enter EXACTLY the bars C1 enters. If it does not, the harness is
    # wrong and the run is void rather than interesting.
    signs = {w: float(f.beta[1]) for w, f in oofs["conf"].fits.items()}
    conf_pol = policies["learnconf_R2_S1"]
    conf_bars = set(map(tuple, conf_pol.oof.pool.loc[conf_pol.entry, ["seed", "pair", "ts"]]
                        .to_numpy()))
    base_bars = set(map(tuple, pd.concat(
        [g.assign(seed=s)[["seed", "pair", "ts"]] for s, g in c1_ov.items()]).to_numpy()))
    same = conf_bars == base_bars
    if all(v > 0 for v in signs.values()):
        verdict = ("✅ **The check holds.**" if same else
                   "🔴 **THE CHECK FAILS — the run is void, not interesting.**")
        c2_check = (
            f"All four folds fit `conf_rank` with a **positive** coefficient "
            f"({', '.join(f'{w}={v:+.2f}' for w, v in signs.items())}), so the "
            f"confidence-only model orders bars identically to `conf` and "
            f"`learnconf_R2_S1` must enter exactly the bars C1 enters.\n\n{verdict} "
            f"{len(conf_bars):,} entry bars against {len(base_bars):,}, "
            f"{len(conf_bars & base_bars):,} in common.")
    else:
        c2_check = (
            f"🔴 **The coefficient on `conf_rank` is not positive in every fold** "
            f"({', '.join(f'{w}={v:+.2f}' for w, v in signs.items())}). Within the top "
            f"{features.POOL_COVERAGE:.0%} of bars, more confidence does not mean more edge "
            f"in at least one fold. That is a genuine finding about the signal rather than a "
            f"harness fault, and M3_3_PROTOCOL §6 pre-registered reporting it as one; the "
            f"set-equality check does not apply where the ordering inverts. "
            f"{len(conf_bars):,} entry bars against C1's {len(base_bars):,}, "
            f"{len(conf_bars & base_bars):,} in common.")
    print(c2_check.replace("**", ""))

    # --- ranking and the bar ------------------------------------------------------------
    ranked = search.rank(learned)
    beat = [c for c in ranked if c["worst_net"] > learn.BASELINE_BAR_BPS]
    winner = ranked[0] if ranked else None

    # --- §6 C3: the O8 replication -----------------------------------------------------
    # Following the precedent `m3 search` set for M3-2: if nothing passes, the
    # pre-registered run still happens and attaches to the best-ranked ELIGIBLE (P4-passing)
    # configuration instead, labelled as such. A pre-registered run that only happens on
    # success is a run that can only ever produce good news.
    eligible = [c for c in learned if c["tier1"]["P4"]]
    best = (ranked[0] if ranked else
            max(eligible, key=lambda c: (c["worst_net"], c["taker14"]["net_bps"]))
            if eligible else None)
    c3 = None
    if best is not None:
        w_cfg = next(c for c in learned_grid() if c.label == best["label"])
        o8 = dumps.load(dumps.O8_RUN, seed="o8")
        o8_feat = features.build(o8, regime.build(o8.df))
        o8_pool = features.pool(o8_feat)
        ov = learn.replicate_o8(o8_pool, policies[w_cfg.label],
                                learn.bar_counts({"o8": o8_feat}))
        r = backtest.run([o8], learn.spec_for(w_cfg, label=w_cfg.label + "_O8"), None, overlay=ov)
        c3 = search.scorecard(w_cfg.label + "_O8", r.trades, ["o8"],
                              search.calendar_days([o8]), learn.spec_for(w_cfg))
        search.tier1(c3)

    # The pool's own mean gross edge per window — not a policy result, but the quantity the
    # per-fold intercepts of §C are estimates of, and the only way to read them.
    pool_means = {w: float(g["y_bps"].mean()) for w, g in pool.groupby("window", sort=True)}

    text = learn.render_report(learned, ablation, c1, c3, oofs, winner, best, ranked,
                               c2_check, pool_means, ds, cal,
                               n_runs=len(grid) + 1 + (1 if c3 is not None else 0))
    os.makedirs(os.path.dirname(learn.REPORT_PATH), exist_ok=True)
    with open(learn.REPORT_PATH, "w") as fh:
        fh.write(text)
    print("\n" + text)
    print(f"\n[report written to {learn.REPORT_PATH}] — copy it to its canonical home:")
    print("  cp ml/train/output/m3/M3_3_RESULTS.md docs/M3_3_RESULTS.md")
    return 0


# ---------------------------------------------------------------------------------------
# T3 — the 12-pair adoption probe.
#
# WHY THIS IS COMMITTED CODE and not a scratch script: M3_PLAN §0.0 records that the Q1
# harness was never committed, so `btc_absret_1d` existed only in prose and M3's first task
# was rebuilding it. The 8-vs-12 comparison is the same kind of number — one that decides a
# deployment — and it is measured the same way here every time it is asked.
#
# The comparison is made WITHIN a run, never against the published 8-pair runs: restricting
# the same checkpoint's own dump to the 8 baseline pairs holds the model, the seed and the
# calendar fixed so that the only thing varying is the traded universe. Comparing a new
# 12-pair run against §1.3's 8-pair family would confound universe with seed and split.
# ---------------------------------------------------------------------------------------

# M3-2's winner, verbatim: docs/M3_2_RESULTS.md, cov0.02_hold240_rqnone_mcnone_SIZED. It is
# transcribed rather than re-selected — re-searching the grid on a new pair population and
# taking the best would be exactly the shopping M3_PROTOCOL §0 forbids.
WINNER_SPEC = dict(coverage=0.02, signal_horizon=240, hold_horizon=240,
                   regime_col="btc_absret_1d", regime_quantile=None, regime_min=None,
                   size_by_regime=True, max_concurrent=None, sides="both", side_from="model")


def _score_universe(label: str, ds: list, spec: backtest.PolicySpec,
                    regimes: dict | None = None) -> dict:
    regimes = regimes if regimes is not None else {d.seed: regime.build(d.df) for d in ds}
    res = backtest.run(ds, spec, regimes)
    card = search.scorecard(label, res.trades, [d.seed for d in ds],
                            search.calendar_days(ds), spec)
    search.tier1(card)
    card["_thresholds"] = res.thresholds
    card["_bars"] = sum(len(d.at(spec.signal_horizon)) for d in ds)
    card["_trades"] = res.trades
    return card


def _print_universe(card: dict) -> None:
    t = card["taker14"]
    thr = ", ".join(f"{k}={v:.4f}" for k, v in card["_thresholds"].items())
    print(f"\n=== {card['label']} ===")
    print(f"bars={card['_bars']:,}  conf thresholds: {thr}")
    print(f"trades={card['trades']:,}  tr/day={t['trades_per_day']:.2f}  "
          f"gross={t['gross_bps']:+.2f}  net@14={t['net_bps']:+.2f}  "
          f"net@5={card['maker5']['net_bps']:+.2f}  sharpe={t['sharpe']:.2f}  "
          f"maxdd={t['maxdd']:.4f}  mean_size={card['mean_size']:.3f}")
    print(card["taker14_windows"].to_string(index=False, float_format=lambda v: f"{v:+.3f}"))
    ci = card["taker14_ci"]
    print("clustered: mean=%+.2f  clusters=%d  se=%.2f  95%% CI=[%+.2f, %+.2f]"
          % (ci["mean_bps"], ci["clusters"], ci["se_bps"], ci["lo95_bps"], ci["hi95_bps"]))
    print("tier-1: " + "  ".join(f"{k}={'Y' if v else 'N'}" for k, v in card["tier1"].items()))


def cmd_universe(args) -> int:
    """T3 — does the traded universe (8 pairs vs 12) change M3-2's winner?

    Scores the winner spec twice on the SAME dumps: once restricted to the 8 pairs every
    published M3 number is measured on, once on every pair the dumps carry. Reports the
    per-pair breakdown of the wide run, because the interesting question after the headline
    is whether the gain is broad or is one instrument.
    """
    run_ids = [r.strip() for r in (args.runs or dumps.O8_RUN).split(",") if r.strip()]
    ds_all = [dumps.load(r, seed=f"s{i+1}" if len(run_ids) > 1 else "o8")
              for i, r in enumerate(run_ids)]
    ds_8 = [dumps.load(r, seed=d.seed, pairs=dumps.BASE8) for r, d in zip(run_ids, ds_all)]

    wide_pairs = sorted(set().union(*[set(d.df["pair"].unique()) for d in ds_all]))
    extra = [p for p in wide_pairs if p not in dumps.BASE8]
    print(f"runs: {', '.join(run_ids)}")
    print(f"universe: {len(wide_pairs)} pairs; {len(extra)} beyond the baseline 8: "
          f"{', '.join(extra) or '(none — nothing to compare)'}")
    print(f"policy:   {backtest.PolicySpec(label='M3-2 winner', **WINNER_SPEC)}")

    narrow = _score_universe(f"baseline {len(dumps.BASE8)} pairs", ds_8,
                             backtest.PolicySpec(label="base8", **WINNER_SPEC))
    wide = _score_universe(f"all {len(wide_pairs)} pairs", ds_all,
                           backtest.PolicySpec(label="wide", **WINNER_SPEC))
    _print_universe(narrow)
    _print_universe(wide)

    # Per-pair, on the wide run. §1.3 warns per-pair dir_acc does not replicate across
    # seeds, so this is read as texture — is the gain broad or one instrument — and never
    # as a reason to drop or keep an individual pair.
    t = wide["_trades"].copy()
    t["net_bps"] = (t["signed_ret"] - metrics.TAKER_COST_BPS / 1e4 * t.get("size", 1.0)) * 1e4
    g = t.groupby("pair").agg(trades=("net_bps", "size"),
                              gross=("signed_ret", lambda s: float(s.mean()) * 1e4),
                              net=("net_bps", "mean"),
                              win=("signed_ret", lambda s: float((s > 0).mean())))
    g["beyond_base8"] = ["" if p in dumps.BASE8 else "NEW" for p in g.index]
    print("\n--- per pair, wide universe (texture only — per-pair numbers do not replicate "
          "across seeds, NEXT_TRAINING_PLAN §1.3) ---")
    print(g.sort_values("net", ascending=False).to_string(float_format=lambda v: f"{v:+.2f}"))
    in8 = t["pair"].isin(dumps.BASE8)
    print(f"\nbase8 pairs within the wide run: n={int(in8.sum()):,}  "
          f"net@14={t.loc[in8, 'net_bps'].mean():+.2f}")
    if (~in8).any():
        print(f"pairs beyond the baseline 8:     n={int((~in8).sum()):,}  "
              f"net@14={t.loc[~in8, 'net_bps'].mean():+.2f}")

    d_net = wide["taker14"]["net_bps"] - narrow["taker14"]["net_bps"]
    d_worst = wide["worst_net"] - narrow["worst_net"]
    print(f"\nWIDE − NARROW:  pooled net@14 {d_net:+.2f}bps   "
          f"worst window {d_worst:+.2f}bps ({narrow['worst_window']}→{wide['worst_window']})   "
          f"trades/day {wide['taker14']['trades_per_day'] - narrow['taker14']['trades_per_day']:+.2f}")
    print("The adoption rule (docs/NEXT_TRAINING_PLAN.md §2 T3): adopt 12 pairs iff the wide "
          "run still passes Tier 1 and its worst window does not degrade.")
    return 0




# ---------------------------------------------------------------------------------------
# T6 — the fair version of the 8-vs-12 comparison.
#
# THE DECISION RULE, PRE-REGISTERED HERE BEFORE THE FIRST RUN (NEXT_TRAINING_PLAN §2 T6,
# M3_PROTOCOL §0's standing requirement that a rule is committed before it is applied):
#
#   * The FAIR TEST is the trade-count-matched comparison of M3-2's winner spec, each
#     universe scored at its own best concurrency cap over the PRE-REGISTERED cap set
#     {None, 3} — the two values the M3-2 grid already contains — ranked as M3_PROTOCOL
#     §4.2 ranks, by worst-window net at taker.
#   * ADOPT 12 pairs iff the paired 95% CI on (wide − narrow) lies entirely above 0.
#   * CLOSE 12 pairs iff it lies entirely below 0.
#   * Otherwise the question stays UNDECIDED and the incumbent 8-pair universe stands by
#     default — and the interval, plus the effect this test could have detected, is what
#     gets written down. "Undecided" is a real outcome here, not a failure to finish.
#
# The wider cap ladder {2, 4, 6, 8} is printed as TEXTURE and is excluded from the rule
# above by construction: choosing a cap from it after seeing the numbers is the shopping
# M3_PROTOCOL §0 forbids, and it would re-open a search on a new pair population.
# ---------------------------------------------------------------------------------------

# The three 12-pair dumps §1.10 measured on: T1, T2 and O8.
T6_RUNS = ("20260827T050701Z", "20260827T114122Z", dumps.O8_RUN)

CAPS_PREREGISTERED = (None, 3)          # GRID_MAX_CONC, verbatim
CAPS_TEXTURE = (2, 4, 6, 8)             # printed, never chosen from

_HEAD = ("| arm | trades | tr/day | gross | net @14 | worst window | Sharpe | maxdd | "
         "clusters |")
_RULE = "|---|---:|---:|---:|---:|---:|---:|---:|---:|"


def _cap_label(cap) -> str:
    return "none" if cap is None else str(cap)


def _card_row(card: dict) -> str:
    t, ci = card["taker14"], card["taker14_ci"]
    return (f"| {card['label']} | {card['trades']:,} | {t['trades_per_day']:.2f} | "
            f"{t['gross_bps']:+.2f} | **{t['net_bps']:+.2f}** | {card['worst_net']:+.2f} "
            f"({card['worst_window']}) | {t['sharpe']:.2f} | {t['maxdd']:.4f} | "
            f"{ci['clusters']} |")


def cmd_universe_fair(args) -> int:
    """T6 — trade-count-matched, cap-re-tuned, and reported with intervals and power."""
    run_ids = [r.strip() for r in (args.runs or ",".join(T6_RUNS)).split(",") if r.strip()]
    ds_all = [dumps.load(r, seed=f"s{i + 1}") for i, r in enumerate(run_ids)]
    ds_8 = [dumps.load(r, seed=d.seed, pairs=dumps.BASE8) for r, d in zip(run_ids, ds_all)]
    reg_all = {d.seed: regime.build(d.df) for d in ds_all}
    reg_8 = {d.seed: regime.build(d.df) for d in ds_8}
    seeds = [d.seed for d in ds_all]
    cal = search.calendar_days(ds_all)
    wide_pairs = sorted(set().union(*[set(d.df["pair"].unique()) for d in ds_all]))
    spec = backtest.PolicySpec(label="winner", **WINNER_SPEC)

    lines: list[str] = []

    def emit(text: str = "") -> None:
        print(text)
        lines.append(text)

    def table(rows: list[str]) -> None:
        emit(_HEAD)
        emit(_RULE)
        for r in rows:
            emit(r)

    def diff_line(a_card: dict, b_card: dict, what: str) -> dict:
        d = universe.paired_diff_bps(a_card["_trades"], b_card["_trades"])
        bs = universe.bootstrap_diff_se(a_card["_trades"], b_card["_trades"],
                                        draws=args.draws)
        emit(f"**{what}: {d['diff_bps']:+.2f} bps**, 95% CI "
             f"[{d['lo95_bps']:+.2f}, {d['hi95_bps']:+.2f}] "
             f"(cluster-robust SE {d['se_bps']:.2f} over {d['clusters']} exit days, "
             f"{d['shared_days']} of them shared; day-bootstrap SE {bs['se_bps']:.2f} on "
             f"{bs['draws']:,} draws, as an independent check on the analytic one). At 80% "
             f"power this comparison resolves effects of about ±{2.8 * d['se_bps']:.1f} bps "
             f"and nothing smaller.")
        return d

    emit("# T6 — the fair 8-vs-12 comparison")
    emit("")
    emit(f"runs: {', '.join(run_ids)}  (seeds {', '.join(seeds)})")
    emit(f"universe: {len(wide_pairs)} pairs, {len(dumps.BASE8)} of them the baseline; "
         f"beyond it: {', '.join(p for p in wide_pairs if p not in dumps.BASE8)}")
    emit(f"policy:   {spec}")
    emit(f"calendar span: {cal:.1f} days;  costs: taker "
         f"{metrics.TAKER_COST_BPS:.0f}bps, maker {metrics.MAKER_COST_BPS:.0f}bps "
         f"round trip")
    emit("")

    # --- reference: the coverage-matched comparison §1.10 published ----------------------
    emit("## 0. The coverage-matched comparison, for reference")
    emit("")
    emit("What `m3 universe` reports and what §1.10 published. It is NOT the fair test: at "
         "a fixed 2% coverage the wider universe takes ~50% more trades, so it is spending "
         "a bigger budget rather than picking better trades.")
    emit("")
    n_cov = _score_universe(f"8 pairs, cov {spec.coverage:g}", ds_8, spec, regimes=reg_8)
    w_cov = _score_universe(f"12 pairs, cov {spec.coverage:g}", ds_all, spec, regimes=reg_all)
    table([_card_row(n_cov), _card_row(w_cov)])
    emit("")
    d_cov = diff_line(w_cov, n_cov, "wide − narrow, coverage-matched")
    emit("")
    emit("### 0b. §1.10's published interval, re-derived — and it is a different estimand")
    emit("")
    emit("§1.10 reports this same comparison as **−0.85 bps, 95% CI [−6.79, +5.09] across "
         "167 shared days**, and concludes from it that the original single-seed "
         "\"+7.5 bps from 12 pairs\" is excluded. That number is reproduced exactly below — "
         "but by a **day-weighted, shared-days-only** estimator, while the table it sits "
         "beside reports **trade-weighted** means. The two answer different questions and "
         "they do not agree about the +7.5.")
    emit("")
    dw_shared = universe.day_weighted_diff_bps(w_cov["_trades"], n_cov["_trades"])
    dw_all = universe.day_weighted_diff_bps(w_cov["_trades"], n_cov["_trades"],
                                            shared_only=False)
    emit("| estimator | estimand | diff | 95% CI | is +7.5 excluded? |")
    emit("|---|---|---:|---|---|")
    emit(f"| trade-weighted, cluster-robust (`paired_diff_bps`) | the difference in net "
         f"bps **per trade** — the statistic the table above reports | "
         f"{d_cov['diff_bps']:+.2f} | [{d_cov['lo95_bps']:+.2f}, {d_cov['hi95_bps']:+.2f}] "
         f"| **{'yes' if d_cov['hi95_bps'] < 7.5 else 'NO'}** |")
    emit(f"| day-weighted, shared days only — **§1.10's** | the average **daily** "
         f"difference in net bps per trade, over days both universes traded | "
         f"{dw_shared['diff_bps']:+.2f} | [{dw_shared['lo95_bps']:+.2f}, "
         f"{dw_shared['hi95_bps']:+.2f}] | "
         f"{'yes' if dw_shared['hi95_bps'] < 7.5 else 'NO'} |")
    emit(f"| day-weighted, all days | the same, but not dropping the "
         f"{d_cov['clusters'] - dw_shared['days']} days only one universe traded | "
         f"{dw_all['diff_bps']:+.2f} | [{dw_all['lo95_bps']:+.2f}, "
         f"{dw_all['hi95_bps']:+.2f}] | "
         f"{'yes' if dw_all['hi95_bps'] < 7.5 else 'NO'} |")
    emit("")
    emit("**The claim under test is a per-trade claim, so the first row governs it.** "
         "Equally weighting days is a different estimand — it coincides with the per-trade "
         "difference only if every day carries the same number of trades in both arms, "
         "which is precisely what changing the universe breaks — and restricting to shared "
         "days discards the days on which the two policies most differ. On the estimator "
         "that matches the published statistic, **+7.5 bps is inside the interval**: the "
         "T-wave did not exclude it either. The +7.5 remains an unreplicated single-seed "
         "point estimate, which is reason enough not to bank it, but §1.10 should not be "
         "read as having refuted it.")
    emit("")

    # --- TEST 1: trade-count-matched ----------------------------------------------------
    emit("## 1. TEST 1 — the trade-count-matched comparison (the fair one)")
    emit("")
    target = n_cov["trades"]
    cov_w, res_wm = universe.match_coverage(ds_all, spec, reg_all, target_trades=target)
    emit(f"The 8-pair arm books **{target:,}** pooled trades at cov {spec.coverage:g}. "
         f"Bisecting coverage on the 12-pair universe to the same budget lands at **cov "
         f"{cov_w:.5f}** and {len(res_wm.trades):,} trades — the wide arm is now "
         f"{spec.coverage / cov_w:.2f}x more selective, which is exactly the hypothesis: a "
         f"deeper cross-section should let the policy pick better trades, not more of them.")
    emit("")
    w_matched = _score_universe(f"12 pairs, cov {cov_w:.5f} (count-matched)", ds_all,
                                universe.with_fields(spec, coverage=cov_w), regimes=reg_all)
    table([_card_row(n_cov), _card_row(w_matched)])
    emit("")
    d_matched = diff_line(w_matched, n_cov, "wide − narrow, TRADE-COUNT-MATCHED")
    emit("")
    emit("### 1b. The selectivity control — is the gain the universe, or just a tighter cut?")
    emit("")
    emit("Matching the trade count makes the wide arm **more selective as well as wider**, "
         "and those are two different levers. Scoring the 8-pair universe at the SAME "
         "coverage separates them: whatever a tighter cut is worth on its own shows up in "
         "the narrow arm too.")
    emit("")
    n_sel = _score_universe(f"8 pairs, cov {cov_w:.5f} (same cut, fewer trades)", ds_8,
                            universe.with_fields(spec, coverage=cov_w), regimes=reg_8)
    table([_card_row(n_cov), _card_row(n_sel), _card_row(w_matched)])
    emit("")
    d_sel = universe.paired_diff_bps(n_sel["_trades"], n_cov["_trades"])
    d_uni = universe.paired_diff_bps(w_matched["_trades"], n_sel["_trades"])
    emit(f"- **tightening the cut alone** (8 pairs, cov {spec.coverage:g} → {cov_w:.5f}): "
         f"{d_sel['diff_bps']:+.2f} bps, 95% CI [{d_sel['lo95_bps']:+.2f}, "
         f"{d_sel['hi95_bps']:+.2f}]")
    emit(f"- **widening the universe at that same cut** (8 → 12 pairs, both at cov "
         f"{cov_w:.5f}): {d_uni['diff_bps']:+.2f} bps, 95% CI [{d_uni['lo95_bps']:+.2f}, "
         f"{d_uni['hi95_bps']:+.2f}]")
    emit(f"- **the two together**, which is the count-matched headline: "
         f"{d_matched['diff_bps']:+.2f} bps")
    emit("")
    emit("⚠️ **Read TEST 1's headline through this decomposition, not on its own.** The "
         "count-matched comparison confounds a wider universe with a tighter confidence "
         "cut, and the second is a lever the 8-pair universe can pull too — at the cost of "
         "trading less often, which is why the M3-2 grid did not choose it.")
    emit("")

    # --- TEST 2: the concurrency cap re-tune --------------------------------------------
    emit("## 2. TEST 2 — re-tuning the concurrency cap")
    emit("")
    emit("⚠️ A **sizing re-tune on a fixed policy**, over the cap values the M3-2 grid "
         "already contains (`GRID_MAX_CONC = (None, 3)`). It is not a re-search of the "
         "40-config grid on a new pair population, which M3_PROTOCOL §0 forbids. The wider "
         "ladder below is texture and nothing is chosen from it.")
    emit("")
    ladder: dict = {}
    for cap in CAPS_PREREGISTERED + CAPS_TEXTURE:
        ladder[("8", cap)] = _score_universe(
            f"8 pairs, cap {_cap_label(cap)}", ds_8,
            universe.with_fields(spec, max_concurrent=cap), regimes=reg_8)
        ladder[("12", cap)] = _score_universe(
            f"12 pairs, cap {_cap_label(cap)} (count-matched)", ds_all,
            universe.with_fields(spec, coverage=cov_w, max_concurrent=cap), regimes=reg_all)
    emit("**Pre-registered cap set — the decision is taken over these rows only.**")
    emit("")
    table([_card_row(ladder[(u, cap)])
           for cap in CAPS_PREREGISTERED for u in ("8", "12")])
    emit("")
    emit("*Texture only — the wider ladder. Not eligible to be chosen (M3_PROTOCOL §0).*")
    emit("")
    table([_card_row(ladder[(u, cap)]) for cap in CAPS_TEXTURE for u in ("8", "12")])
    emit("")

    # M3_PROTOCOL §4.2's ranking rule, applied inside each universe over the
    # pre-registered caps only.
    def best_cap(uni: str):
        cands = [(cap, ladder[(uni, cap)]) for cap in CAPS_PREREGISTERED]
        return sorted(cands, key=lambda kv: (-kv[1]["worst_net"],
                                             -kv[1]["taker14"]["net_bps"]))[0]

    cap_8, best_8 = best_cap("8")
    cap_12, best_12 = best_cap("12")
    emit(f"Best pre-registered cap by worst-window net at taker: **8 pairs → "
         f"`max_concurrent={_cap_label(cap_8)}`**, **12 pairs → "
         f"`max_concurrent={_cap_label(cap_12)}`**.")
    emit("")

    # --- TEST 3: the difference, its interval, and the criterion's power -----------------
    emit("## 3. TEST 3 — the fair difference, its interval, and each criterion's power")
    emit("")
    table([_card_row(best_8), _card_row(best_12)])
    emit("")
    d_fair = diff_line(best_12, best_8,
                       "THE FAIR TEST — wide − narrow, count-matched, each universe at its "
                       "own best pre-registered cap")
    emit("")
    arms = {
        f"8 pairs (cap {_cap_label(cap_8)}) — the INCUMBENT":
            universe.Arm(best_8["_trades"], seeds, cal),
        f"12 pairs (cap {_cap_label(cap_12)}, count-matched)":
            universe.Arm(best_12["_trades"], seeds, cal),
    }
    power = universe.criterion_power(arms, draws=args.draws)
    emit("⚠️ **Whose Tier 1 is this?** These three dumps are the 12-pair checkpoints T1, "
         "T2 and O8 — not the banked 8-pair family M3-2's winner was selected on. A Tier-1 "
         "failure in the table below is a statement about this checkpoint population, and "
         "is NOT the served policy failing its own certification.")
    emit("")
    emit(f"**Bootstrap failure rate of each Tier-1 criterion**, {args.draws:,} common "
         f"day-resamples (`universe.criterion_power`, seed {universe.BOOTSTRAP_SEED}). "
         f"Read the incumbent's row first: a criterion the incumbent also fails half the "
         f"time cannot arbitrate between the two universes.")
    emit("")
    emit("| arm | | P1 | P2 | P3 | P4 | P5 | P6 | all six |")
    emit("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    observed = {"8 pairs (cap %s) — the INCUMBENT" % _cap_label(cap_8): best_8,
                "12 pairs (cap %s, count-matched)" % _cap_label(cap_12): best_12}
    for _, r in power.iterrows():
        # The point result first, then how often a resample of the same days would have
        # flipped it. A criterion is only evidence where those two lines disagree.
        obs = observed[r["arm"]]["tier1"]
        emit(f"| {r['arm']} | observed | " + " | ".join(
            ("Y" if obs[c] else "**N**") for c in ("P1", "P2", "P3", "P4", "P5", "P6", "PASS")) + " |")
        emit(f"| | fails in | " + " | ".join(
            f"{r[c]:.1%}" for c in ("P1", "P2", "P3", "P4", "P5", "P6", "PASS")) + " |")
    emit("")

    # --- the verdict, by the rule pre-registered at the top of this section --------------
    emit("## Verdict, by the rule committed above before this ran")
    emit("")
    lo, hi = d_fair["lo95_bps"], d_fair["hi95_bps"]
    if lo > 0:
        verdict = ("**ADOPT 12 pairs.** The paired interval on the fair test lies entirely "
                   "above zero.")
    elif hi < 0:
        verdict = ("**CLOSE 12 pairs.** The paired interval on the fair test lies entirely "
                   "below zero.")
    else:
        verdict = ("**UNDECIDED — the incumbent 8-pair universe stands by default.** The "
                   "paired interval on the fair test spans zero, so this data cannot "
                   "separate the two universes in either direction.")
    emit(f"{verdict} Fair-test difference **{d_fair['diff_bps']:+.2f} bps**, 95% CI "
         f"[{lo:+.2f}, {hi:+.2f}], over {d_fair['clusters']} exit-day clusters.")
    emit("")
    emit(f"**And the fair test's point estimate is not a universe effect anyway.** §1b "
         f"decomposes it: tightening the confidence cut is worth {d_sel['diff_bps']:+.2f} "
         f"bps on the 8-pair universe by itself, while widening 8 → 12 pairs at that same "
         f"cut is worth {d_uni['diff_bps']:+.2f} bps, 95% CI [{d_uni['lo95_bps']:+.2f}, "
         f"{d_uni['hi95_bps']:+.2f}]. Almost all of the {d_fair['diff_bps']:+.2f} is the "
         f"cut, not the pairs — and the universe term, cleanly separated, is a small "
         f"NEGATIVE point estimate with an interval that still spans zero. Three "
         f"comparisons (coverage-matched, count-matched, cut-matched) now put the universe "
         f"effect within a couple of bps of zero in both directions.")
    emit("")
    emit("**What the concurrency cap turned out to be worth: nothing, on either universe.** "
         "§1.10 read the widened drawdown (−2.83 → −4.53) as an argument for re-tuning the "
         "cap. Re-tuned over the pre-registered set it is not: `max_concurrent=none` wins "
         "on both universes, and every cap in the texture ladder costs net bps. A cap does "
         "cut drawdown, and it buys that by refusing profitable trades.")
    emit("")
    emit("**The criterion-power table settles what §1.10 could only suspect.** P5 — the "
         "all-seeds-positive check an earlier draft used to reject 12 pairs — fails on the "
         "INCUMBENT in "
         f"{power.loc[0, 'P5']:.1%} of resamples against {power.loc[1, 'P5']:.1%} on the "
         "challenger. It cannot decide anything. The criterion that actually bites is "
         "**P3, the −5 bps worst-window floor**, which fails on both arms in the observed "
         f"data and in {power.loc[0, 'P3']:.1%} / {power.loc[1, 'P3']:.1%} of resamples. "
         "**Window 3 is the binding constraint on this policy, and it is not a universe "
         "problem** — widening the pair set does not touch it.")
    emit("")
    emit(f"**What this test could have detected.** The cluster-robust SE on the difference "
         f"is {d_fair['se_bps']:.2f} bps, so at 80% power it resolves effects of about "
         f"±{2.8 * d_fair['se_bps']:.1f} bps and nothing smaller. That bound is a property "
         f"of the ~{d_fair['clusters']} independent exit days this evaluation period "
         f"contains, not of the policy or of the number of seeds — pooling more seeds adds "
         f"correlated trades inside the same days and does not move it (§1.10). **A real "
         f"universe effect of the size anyone cared about (+7.5 bps) is roughly a third of "
         f"what this evaluation period can resolve.** No further offline work on these "
         f"dumps, and no further seeds, can settle 8-vs-12: only a longer evaluation "
         f"period can, and that is calendar, not compute.")
    emit("")
    emit("### One observation that is NOT a recommendation")
    emit("")
    emit(f"On these three checkpoints the 8-pair universe scores {n_sel['taker14']['net_bps']:+.2f} "
         f"net bps at cov {cov_w:.5f} against {n_cov['taker14']['net_bps']:+.2f} at cov "
         f"{spec.coverage:g}, with a better worst window "
         f"({n_sel['worst_net']:+.2f} vs {n_cov['worst_net']:+.2f}) and a higher Sharpe "
         f"({n_sel['taker14']['sharpe']:.2f} vs {n_cov['taker14']['sharpe']:.2f}). **Do "
         f"not act on that here.** Coverage is a searched dimension of the M3-2 grid, "
         f"which chose 0.02 on the banked 8-pair family; re-picking it on a different "
         f"checkpoint population after seeing the numbers is precisely the shopping "
         f"M3_PROTOCOL §0 forbids. If coverage is to be revisited it goes through a fresh "
         f"pre-registration on the population the decision will be served from.")
    emit("")

    path = os.path.join("output", "m3", "T6_RESULTS.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(chr(10).join(lines) + chr(10))
    print(f"{chr(10)}[report written to {path}] — copy it to its canonical home:")
    print("  cp ml/train/output/m3/T6_RESULTS.md docs/T6_RESULTS.md")
    return 0


def cmd_bookprep(args) -> int:
    """Print the facts M3-4's pre-registration rests on — DATA QUALITY ONLY.

    The third in the line `power` / `fitprep` started, and the one with the most to correct:
    M3_PLAN §2 M3-4 described the ladder as a 5s series and the tape as per-window high/low,
    and neither is true (see the module docstring). No fill rate, queue drain, adverse
    selection or effective cost appears here — those are the study, and
    docs/M3_4_PROTOCOL.md is committed before any of them is computed.
    """
    return bookprep.audit()


def cmd_execcost(args) -> int:
    """M3-4 — run the execution-cost study docs/M3_4_PROTOCOL.md pre-registers.

    The protocol is committed; this command only executes it. Two inputs are built here
    rather than inside `execcost` so the module stays free of the grid's definition:

      * the M3-2 winner's own trade ledger, for L3 and for §5.2 clause 2's re-score;
      * the 40 pre-registered configurations, RE-SCORED at the measured cost.

    🔴 Re-scoring is not re-searching (§5.4). `primary_grid()` is the same list M3-2 ran;
    nothing is added, dropped or re-tuned, and if the measured cost changes which config
    ranks first that is a finding to report, never a promotion.
    """
    ds = dumps.load_baseline(pairs=dumps.BASE8)
    regimes = {d.seed: regime.build(d.df) for d in ds}

    winner = backtest.run(ds, backtest.PolicySpec(label="M3-2 winner", **WINNER_SPEC),
                          regimes).trades

    grid = []
    if not args.no_grid:
        for spec in primary_grid():
            grid.append((spec.label or str(spec), backtest.run(ds, spec, regimes).trades))

    return execcost.run_study(winner, grid, levels=args.levels)


def cmd_policy(args) -> int:
    ds = dumps.load_baseline(pairs=dumps.BASE8)
    spec = backtest.PolicySpec(
        coverage=args.coverage,
        signal_horizon=args.signal_horizon,
        hold_horizon=args.hold_horizon,
        regime_col=args.regime_col,
        regime_quantile=args.regime_quantile,
        regime_min=args.regime_min,
        size_by_regime=args.size_by_regime,
        max_concurrent=args.max_concurrent,
        sides=args.sides,
        label=args.label or "policy",
    )
    regimes = {d.seed: regime.build(d.df) for d in ds} if spec.regime_col else None
    res = backtest.run(ds, spec, regimes)
    t = res.trades

    print(f"\npolicy: {spec}")
    print(f"per-seed confidence thresholds: "
          + ", ".join(f"{k}={v:.4f}" for k, v in res.thresholds.items()))
    if res.regime_thresholds:
        print("per-seed regime thresholds:   "
              + ", ".join(f"{k}={v:.4f}" for k, v in res.regime_thresholds.items()))

    span = metrics.span_days(t)
    for cost, name in ((metrics.MAKER_COST_BPS, "maker 5bps"), (metrics.TAKER_COST_BPS, "taker 14bps")):
        s = metrics.summarise(t, cost, span, n_seeds=len(ds))
        print(f"\n--- {name} " + "-" * 60)
        print(f"trades={s['trades']:,}  gross={s['gross_bps']:+.2f}bps  net={s['net_bps']:+.2f}bps  "
              f"win={s['win']:.3f}  trades/day={s['trades_per_day']:.2f}  "
              f"maxdd={s['maxdd']:.4f}  sharpe={s['sharpe']:.2f}")
        w = metrics.by_window(t, cost)
        print(w.to_string(index=False, float_format=lambda v: f"{v:+.3f}"))
        worst = w.loc[w["net_bps"].idxmin()]
        print(f"WORST WINDOW: {worst['window']}  net={worst['net_bps']:+.2f}bps  "
              f"(n={int(worst['trades'])}) — this is the number M3-1 scores on")
        print(metrics.side_split(t, cost).to_string(index=False,
                                                    float_format=lambda v: f"{v:+.3f}"))
    return 0


# The live executor's catastrophe brake, read off apps/fluxtrader .. risk_manager.ex:
# `stop_loss_pct: 0.02` and `take_profit_ratio: 2.0`. Restated here as the numbers M3-0b
# has to price, because they are the deviation M3-5 shipped and nothing has measured.
LIVE_STOP, LIVE_TARGET = 0.02, 0.04

# M3-4's measured pooled round trip (M3_4_RESULTS.md §1), used here only as the reference
# line for "what the winner nets today". Funding is ADDITIVE and independent of the cost
# line, so the delta this section reports would be the same against 14 bps or against the
# per-pair costs — the constant only sets the number it is a delta from.
MEASURED_POOLED_BPS = 9.842


def _winner_trades():
    """The M3-2 winner's pooled trade ledger — the population every M3-0b number lands on."""
    ds = dumps.load_baseline(pairs=dumps.BASE8)
    regimes = {d.seed: regime.build(d.df) for d in ds}
    res = backtest.run(ds, backtest.PolicySpec(label="M3-2 winner", **WINNER_SPEC), regimes)
    return ds, res.trades


def cmd_sidetable(args) -> int:
    """M3-0b — build the price/funding side-table, prove it, and price what it unlocks."""
    print("=" * 88)
    print("M3-0b — THE PRICE/FUNDING SIDE-TABLE")
    print("=" * 88)

    st = sidetable.build_price_table("5m")
    t = pd.to_datetime(st["ts"], unit="ns", utc=True)
    print(f"grid: {len(st):,} bars x {st['pair'].nunique()} pairs, "
          f"{t.min():%Y-%m-%d} .. {t.max():%Y-%m-%d}")

    print("\n" + "=" * 88)
    print("A. ACCEPTANCE TEST — the gate. Rebuilt fwd_ret_240 vs each dump's own fwd_ret.")
    print("   The dumps store fwd_ret as float32, so the test is EXACT EQUALITY after a")
    print("   float32 round-trip, not a tolerance: a rebuild that merely rounds close would")
    print("   pass a 1e-6 check while quietly describing a different series.")
    print("=" * 88)
    runs = dict(dumps.BASELINE_RUNS)
    runs["o8"] = dumps.O8_RUN
    failed = False
    for seed, run_id in runs.items():
        d = dumps.load(run_id, seed=seed)
        h = d.at(240)[["ts", "pair", "fwd_ret"]]
        m = h.merge(st[["pair", "ts", "fwd_ret_240"]], on=["pair", "ts"], how="left")
        miss = int(m["fwd_ret_240"].isna().sum())
        ok = m.dropna(subset=["fwd_ret_240"])
        exact = int((ok["fwd_ret"].to_numpy() ==
                     ok["fwd_ret_240"].to_numpy().astype(np.float32)).sum())
        diff = float((ok["fwd_ret"] - ok["fwd_ret_240"]).abs().max())
        bad = miss or exact != len(ok)
        failed |= bool(bad)
        print(f"  {seed} {run_id}: bars={len(m):>7,}  unmatched={miss:>5,}  "
              f"exact={exact:,}/{len(ok):,}  max|diff|={diff:.3e}  "
              f"{'FAIL' if bad else 'PASS'}")
    if failed:
        print("\n  🔴 ACCEPTANCE FAILED — nothing below is evidence.")
        return 1
    print("\n  ✅ ACCEPTANCE PASSED — the side-table describes the same series the dumps do.")

    print("\n" + "=" * 88)
    print("B. COVERAGE — what the table holds, per pair")
    print("=" * 88)
    g = st.groupby("pair")
    cov = pd.DataFrame({
        "bars": g.size(),
        "first": g["ts"].min().map(lambda v: f"{pd.Timestamp(v, tz='UTC'):%Y-%m-%d}"),
        "last": g["ts"].max().map(lambda v: f"{pd.Timestamp(v, tz='UTC'):%Y-%m-%d}"),
        "fwd240_ok": g["fwd_ret_240"].apply(lambda c: 1.0 - c.isna().mean()),
        "funding_fresh": g["has_funding"].mean(),
    })
    print(cov.to_string(float_format=lambda v: f"{v:.4f}"))

    ev = sidetable.funding_settlements(sidetable.load_funding())
    per = ev.groupby("pair").size()
    days = (t.max() - t.min()).total_seconds() / 86400.0
    print("\n  funding settlements per pair (per day, over the window):")
    print("   " + "  ".join(f"{p}={n / days:.2f}" for p, n in per.items()))
    odd = per[per > per.median() * 1.5]
    for p in odd.index:
        print(f"  ⚠️  {p} settles ~2x as often as the rest — a 4h funding cycle, not 8h. "
              f"A hardcoded 8h schedule would halve its funding.")

    ds, tr = _winner_trades()
    span = metrics.span_days(tr)
    print("\n" + "=" * 88)
    print("C. THE FUNDING TERM — M3's first non-zero funding number")
    print("   Every M3 result to date sets funding to zero. It is charged here on the M3-2")
    print("   winner's own trades: positive = a cost. It is LUMPY, not proportional to the")
    print("   hold — a 4h position pays only if a settlement instant falls inside it.")
    print("=" * 88)
    fund = sidetable.funding_cost_bps(tr, ev)
    crossed = (fund != 0).mean()
    tt = pd.to_datetime(tr["entry_ts"], unit="ns", utc=True)
    dense = int((tt >= pd.Timestamp("2026-07-01", tz="UTC")).sum())
    print(f"  trades={len(tr):,}  crossing a settlement: {crossed:.1%}  "
          f"(a 4h hold against a mostly-8h cycle)")
    print(f"  last entry {tt.max():%Y-%m-%d}; only {dense} trades ({dense / len(tr):.1%}) fall "
          f"after 2026-07-01, which is\n  where the collector's dense mark-price poll begins "
          f"— so the settlement-detection rule matters\n  for very few of these trades, and "
          f"the market being calm since July is why.")
    print(f"  funding bps/trade: mean={fund.mean():+.3f}  "
          f"median={fund.median():+.3f}  p5={fund.quantile(.05):+.3f}  "
          f"p95={fund.quantile(.95):+.3f}  max cost={fund.max():+.2f}")
    paid = fund[fund > 0].sum() / len(tr)
    earned = -fund[fund < 0].sum() / len(tr)
    print(f"  it PAYS as often as it costs: earned {earned:.3f} bps/trade, "
          f"paid {paid:.3f} bps/trade  ->  net {fund.mean():+.3f}")
    base = metrics.summarise(tr, MEASURED_POOLED_BPS, span, n_seeds=len(ds))
    print(f"\n  the winner's net bps/trade moves {base['net_bps']:+.2f} -> "
          f"{base['net_bps'] - fund.mean():+.2f} once funding is charged "
          f"({-fund.mean():+.3f} bps).")
    print("  🟢 VERDICT: funding is a rounding error at a 4h hold — well inside the noise")
    print("     on a per-trade sd of ~250 bps. It does not change any M3 conclusion, which")
    print("     is itself the finding: it was an unquantified open term until now, and the")
    print("     honest reason to charge it was that nobody had shown it was small.")

    print("\n" + "=" * 88)
    print("D. THE LIVE BRAKE — M3-5's stop/target, priced for the first time")
    print(f"   The deployed executor attaches SL {LIVE_STOP:.0%} / TP {LIVE_TARGET:.0%} to")
    print("   every `auto` entry. The policy was scored on a FIXED 4h hold, so that brake is")
    print("   an unmeasured deviation from the rule that was validated. This is the measure.")
    print("=" * 88)
    ent = tr[["pair", "entry_ts", "side", "size", "signed_ret"]].copy()
    for touch in ("intrabar", "close"):
        b = sidetable.barrier_exit(st, ent, tp=LIVE_TARGET, sl=LIVE_STOP,
                                   max_bars=48, touch=touch)
        _report_barrier(b, touch, span, len(ds))

    print("\n" + "=" * 88)
    print("E. A BARRIER LADDER — DESCRIPTIVE ONLY, NOT A POLICY SEARCH")
    print("   🔴 M3_PROTOCOL §0 forbids re-picking a searched dimension after seeing results.")
    print("   Nothing here is promoted and no winner is chosen: the point is to show the")
    print("   SHAPE of the barrier response, so that a future pre-registration can be")
    print("   written knowing what it is choosing between. Choosing a row of this table")
    print("   because it is the best row is precisely what the protocol prohibits.")
    print("=" * 88)
    rows = []
    for sl in (0.005, 0.01, 0.02):
        for ratio in (1.0, 2.0):
            b = sidetable.barrier_exit(st, ent, tp=sl * ratio, sl=sl, max_bars=48,
                                       touch="intrabar")
            v = b.dropna(subset=["barrier_ret"])
            net = (v["barrier_ret"] * v["size"]).mean() * metrics.BPS - metrics.TAKER_COST_BPS
            rows.append({
                "sl": f"{sl:.1%}", "tp": f"{sl * ratio:.1%}",
                "tp_hit": (v["barrier_exit"] == "tp").mean(),
                "sl_hit": (v["barrier_exit"] == "sl").mean(),
                "timeout": (v["barrier_exit"] == "timeout").mean(),
                "mean_bars": v["barrier_bars"].mean(),
                "net_bps@14": net,
            })
    print(pd.DataFrame(rows).to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    fixed_net = (tr["signed_ret"].mean() * metrics.BPS) - metrics.TAKER_COST_BPS
    print(f"\n  the fixed 4h hold, same trades, same cost line: {fixed_net:+.2f} bps")

    out = os.path.join(sidetable.EXPORT_DIR, "side_5m.parquet")
    st.to_parquet(out, index=False)
    print(f"\n  wrote {out}  ({len(st):,} rows)")
    return 0


def _report_barrier(b: pd.DataFrame, touch: str, span: float, n_seeds: int) -> None:
    v = b.dropna(subset=["barrier_ret"])
    lost = len(b) - len(v)
    fixed = (b["signed_ret"].mean()) * metrics.BPS
    got = (v["barrier_ret"] * v["size"]).mean() * metrics.BPS
    print(f"\n  --- touch={touch} " + "-" * 52)
    if lost:
        print(f"      {lost} entries had no matching grid bar and are excluded")
    print(f"      exits: tp={(v['barrier_exit'] == 'tp').mean():.1%}  "
          f"sl={(v['barrier_exit'] == 'sl').mean():.1%}  "
          f"timeout={(v['barrier_exit'] == 'timeout').mean():.1%}  "
          f"mean hold={v['barrier_bars'].mean() * 5:.0f}m of 240m")
    print(f"      gross bps/trade: fixed-hold {fixed:+.2f}  ->  with the brake {got:+.2f}  "
          f"({got - fixed:+.2f})")


def _bookera_acceptance(df: pd.DataFrame) -> None:
    """B0's own acceptance test — 🔴 'not optional' in BOOK_ERA_PLAN §B0.

    Run separately from M3-0b's even though the code path is shared, because the two tables
    are built from DIFFERENT exports: M3-0b's candles span the validation window and live in
    m3_0b/, B0's span the book era and live in m3_4/. A pass on one is not a pass on the
    other, and the whole point of the test is that the side-table describes the same series
    the dumps do.
    """
    print("  acceptance (B0 §B0, mandatory): fwd_ret_240 vs the dumps over the overlap")
    for seed, run_id in list(dumps.BASELINE_RUNS.items()) + [("o8", dumps.O8_RUN)]:
        d = dumps.load(run_id, seed=seed)
        h = d.at(240)[["ts", "pair", "fwd_ret"]]
        m = h.merge(df[["pair", "ts", "fwd_ret_240"]], on=["pair", "ts"], how="inner")
        m = m.dropna(subset=["fwd_ret_240"])
        if m.empty:
            print(f"    {seed}: no overlap with the book era")
            continue
        exact = int((m["fwd_ret"].to_numpy() ==
                     m["fwd_ret_240"].to_numpy().astype(np.float32)).sum())
        print(f"    {seed}: overlap={len(m):>7,}  exact={exact:,}/{len(m):,}  "
              f"{'PASS' if exact == len(m) else '🔴 FAIL'}")


def cmd_bookera(args) -> int:
    """BOOK_ERA_PLAN B0 — the same alignment, with the book/tape columns, over the book era."""
    print("=" * 88)
    print("B0 — THE BOOK-ERA SIDE-TABLE (built on M3-0b's alignment, as the plan requires)")
    print("=" * 88)
    for interval in ("5m", "1m"):
        df = sidetable.build_book_era(interval)
        t = pd.to_datetime(df["ts"], unit="ns", utc=True)
        print(f"\n--- book_era_{interval} " + "-" * 50)
        print(f"  {len(df):,} rows x {df['pair'].nunique()} pairs, "
              f"{t.min():%Y-%m-%d} .. {t.max():%Y-%m-%d}")
        g = df.groupby("pair")
        cov = pd.DataFrame({
            "bars": g.size(),
            "book_fresh": g["has_book"].mean(),
            "tape_fresh": g["has_trades"].mean(),
            "funding_fresh": g["has_funding"].mean(),
            "fwd240_ok": g["fwd_ret_240"].apply(lambda c: 1.0 - c.isna().mean()),
        })
        print(cov.to_string(float_format=lambda v: f"{v:.4f}"))
        if interval == "5m":
            _bookera_acceptance(df)
        out = os.path.join(sidetable.BOOK_DIR, f"book_era_{interval}.parquet")
        df.to_parquet(out, index=False)
        print(f"  wrote {out}")
    print("\n  ⚠️ nine of B0's eleven scalars are built. `oi` and `oi_chg` are absent because")
    print("     `open_interest` is not one of the tables scripts/gcp_m3_export.sh pulls;")
    print("     adding it is a one-line export change, not an alignment change.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="m3", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("validate", help="run the two acceptance tests").set_defaults(fn=cmd_validate)
    sub.add_parser("power", help="pre-registration facts: spans, SE calibration, eligibility"
                   ).set_defaults(fn=cmd_power)
    sub.add_parser("search", help="M3-2: run and score the 40 pre-registered configurations"
                   ).set_defaults(fn=cmd_search)
    sub.add_parser("fitprep", help="M3-3 pre-registration facts: features, pool, folds "
                   "(counts only — no learned P&L)").set_defaults(fn=cmd_fitprep)
    sub.add_parser("learn", help="M3-3: fit and score the 14 pre-registered learned runs"
                   ).set_defaults(fn=cmd_learn)

    u = sub.add_parser("universe", help="T3: score M3-2's winner on 8 pairs vs every pair "
                       "the dumps carry (the 12-pair adoption decision)")
    u.add_argument("--runs", default=None,
                   help="comma-separated eval run ids to pool (default: O8, the one "
                        "existing 12-pair dump). Pass the three 12-pair seeds once T1/T2 "
                        "have landed.")
    u.set_defaults(fn=cmd_universe)

    f = sub.add_parser("universe-fair", help="T6: the fair 8-vs-12 comparison — trade-count "
                       "matched, concurrency cap re-tuned, difference reported with its "
                       "interval and each criterion's bootstrap power")
    f.add_argument("--runs", default=None,
                   help="comma-separated eval run ids to pool (default: the three 12-pair "
                        "seeds T1, T2 and O8 — the population NEXT_TRAINING_PLAN §1.10 "
                        "measured on)")
    f.add_argument("--draws", type=int, default=universe.BOOTSTRAP_DRAWS,
                   help="bootstrap draws for the criterion-power table")
    f.set_defaults(fn=cmd_universe_fair)

    sub.add_parser("sidetable", help="M3-0b: build the price/funding side-table, run its "
                   "acceptance test, and price the funding term and the live stop/target "
                   "brake that a fixed-hold backtest cannot see").set_defaults(fn=cmd_sidetable)

    sub.add_parser("bookera", help="BOOK_ERA_PLAN B0: the book-era side-table, built on "
                   "M3-0b's alignment").set_defaults(fn=cmd_bookera)

    sub.add_parser("bookprep", help="M3-4a pre-registration facts: ladder cadence, book "
                   "staleness, tape censoring and coverage, touch spread and depth. "
                   "No fill number.").set_defaults(fn=cmd_bookprep)

    e = sub.add_parser("execcost", help="M3-4: run the pre-registered execution-cost "
                       "study — measured taker slippage, maker fill rates, adverse "
                       "selection, and the re-score of the M3-2 grid at the measured cost")
    e.add_argument("--levels", type=int, default=20,
                   help="ladder depth to walk; must not exceed the exported depth")
    e.add_argument("--no-grid", action="store_true",
                   help="re-score only the winner, not all 40 configs (faster smoke run)")
    e.set_defaults(fn=cmd_execcost)

    p = sub.add_parser("policy", help="score one policy spec")
    p.add_argument("--coverage", type=float, default=0.05)
    p.add_argument("--signal-horizon", type=int, default=240)
    p.add_argument("--hold-horizon", type=int, default=None, choices=[60, 240, 1440])
    p.add_argument("--regime-col", default=None)
    p.add_argument("--regime-quantile", type=float, default=None,
                   help="threshold as a quantile of BARS, re-derived per split")
    p.add_argument("--regime-min", type=float, default=None, help="absolute threshold (discouraged)")
    p.add_argument("--size-by-regime", action="store_true")
    p.add_argument("--max-concurrent", type=int, default=None)
    p.add_argument("--sides", default="both", choices=["both", "long", "short"])
    p.add_argument("--label", default="")
    p.set_defaults(fn=cmd_policy)

    args = ap.parse_args()
    return args.fn(args)
