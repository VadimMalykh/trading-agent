"""`python -m m3 <subcommand>` — the entry point scripts/m3.sh drives.

    ./scripts/m3.sh -m m3 validate            # the two acceptance tests (run this first)
    ./scripts/m3.sh -m m3 power               # the pre-registration facts (M3_PROTOCOL §2/§4)
    ./scripts/m3.sh -m m3 fitprep             # M3-3 pre-registration facts (counts only)
    ./scripts/m3.sh -m m3 learn               # M3-3: fit and score the 14 learned runs
    ./scripts/m3.sh -m m3 policy --help       # score one policy spec
"""
from __future__ import annotations

import argparse
import os

import numpy as np
import pandas as pd

from . import backtest, dumps, features, learn, metrics, regime, search, validate


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
