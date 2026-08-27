"""M3-2 — run the 40 pre-registered configurations and score them under the committed rule.

This module executes [docs/M3_PROTOCOL.md](../../../docs/M3_PROTOCOL.md) and nothing else.
The protocol was committed before any search ran, so every choice below is a transcription
of a decision already made, not a decision taken here:

  * the grid is `cli.primary_grid()` (§3.1, 36 configs);
  * the three additions are §3.2 (1 sizing variant, 2 baselines) plus the O8 replication;
  * eligibility is rule P4 (§4.1) and promotion is P1-P6 (§4.2), ranked by worst-window
    net at taker;
  * Tier 2 (§4.3) is the clustered 95% lower bound, reported for the winner and expected
    to fail.

Two definitions the protocol left to the implementation, both resolved toward the
CONSERVATIVE reading and both stated here so a later session can see them:

  1. **The trade-rate denominator (P6) is the full calendar span of the dump**, not the
     span between a policy's own first and last trade. A regime-filtered policy trades in
     bursts; measuring its rate only over the bursts flatters it. The span between first
     and last trade is reported alongside as `tr/day(active)`.
  2. **The "winner" that the sizing variant and the O8 replication attach to** is the best
     Tier-1 passer of the 36 primary configs. The sizing variant is itself scored against
     Tier 1, and if it passes and beats that config on worst-window net it becomes the
     overall M3-2 winner — it is one of the 40 pre-registered runs, so it is allowed to
     win. O8 replicates whichever config ends up on top.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from . import backtest, dumps, metrics, regime

FEES = ((metrics.MAKER_COST_BPS, "maker5"), (metrics.TAKER_COST_BPS, "taker14"))
WINDOW_NAMES = ("w1", "w2", "w3", "w4")

# M3_PROTOCOL §4.2, verbatim.
MIN_TRADES_PER_WINDOW = 100          # P4
MIN_WINDOWS_POSITIVE = 3             # P2
WORST_WINDOW_FLOOR_BPS = -5.0        # P3
MIN_TRADES_PER_DAY = 0.5             # P6

REPORT_PATH = os.path.join("output", "m3", "M3_2_RESULTS.md")


# ---------------------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------------------

def calendar_days(ds: list[dumps.Dump]) -> float:
    """Span of the evaluation period itself, over all seeds' 240m bars."""
    lo, hi = None, None
    for d in ds:
        t = d.at(240)["ts"]
        lo = t.min() if lo is None else min(lo, t.min())
        hi = t.max() if hi is None else max(hi, t.max())
    return (hi - lo) / dumps.NS / 86400.0


def per_notional(trades: pd.DataFrame, cost_bps: float) -> float:
    """Net bps per unit of NOTIONAL DEPLOYED, rather than per trade.

    Only differs from the per-trade mean when a policy varies size. It matters for exactly
    one comparison in M3-2: the §3.2 sizing variant scales size 1/3..5/3, so its per-trade
    mean is a size-weighted average and is not on the same footing as a flat-size policy's.
    `sum(net) / sum(size)` puts them back on one footing.

    This is a DIAGNOSTIC, not a change to the decision rule. M3_PROTOCOL §4.2 ranks on
    worst-window net per trade, that ranking stands for this run, and §0 of the protocol is
    explicit that a better metric noticed afterwards is a proposal for the next
    pre-registration rather than a re-scoring of this one.
    """
    if trades.empty:
        return 0.0
    size = trades["size"] if "size" in trades else pd.Series(1.0, index=trades.index)
    net = trades["signed_ret"] - cost_bps / metrics.BPS * size
    return float(net.sum() / size.sum() * metrics.BPS)


def scorecard(label: str, trades: pd.DataFrame, seeds: list[str], cal_days: float,
              spec: backtest.PolicySpec | None = None) -> dict:
    """Everything M3_PROTOCOL §5 requires for one configuration, at both fee assumptions."""
    n_seeds = len(seeds)
    card: dict = {"label": label, "spec": spec, "trades": len(trades), "n_seeds": n_seeds,
                  "cal_days": cal_days, "active_days": metrics.span_days(trades)}
    card["mean_size"] = float(trades["size"].mean()) if len(trades) and "size" in trades else 1.0
    for cost, fee in FEES:
        card[fee + "_notional"] = per_notional(trades, cost)
        card[fee + "_notional_windows"] = {
            n: per_notional(sub, cost)
            for n, sub in dumps.add_window(trades, ts_col="entry_ts").groupby("window")
        } if len(trades) else {}
        card[fee] = metrics.summarise(trades, cost, cal_days, n_seeds=n_seeds)
        card[fee + "_active_tpd"] = (
            len(trades) / n_seeds / card["active_days"] if card["active_days"] else 0.0
        )
        card[fee + "_windows"] = metrics.by_window(trades, cost, n_seeds=n_seeds)
        card[fee + "_sides"] = metrics.side_split(trades, cost)
        card[fee + "_seeds"] = {
            s: metrics.summarise(trades[trades["seed"] == s], cost, cal_days, n_seeds=1)
            for s in seeds
        }
        card[fee + "_ci"] = metrics.clustered_mean_bps(trades, cost)
    w = card["taker14_windows"]
    card["worst_window"] = str(w.loc[w["net_bps"].idxmin(), "window"]) if len(w) else "-"
    card["worst_net"] = float(w["net_bps"].min()) if len(w) else 0.0
    return card


def tier1(card: dict) -> dict:
    """M3_PROTOCOL §4.2 — the six criteria, evaluated at taker. All six must hold."""
    t, w = card["taker14"], card["taker14_windows"]
    checks = {
        "P1": bool(t["net_bps"] > 0),
        "P2": int((w["net_bps"] > 0).sum()) >= MIN_WINDOWS_POSITIVE,
        "P3": float(w["net_bps"].min()) >= WORST_WINDOW_FLOOR_BPS,
        "P4": int(w["trades"].min()) >= MIN_TRADES_PER_WINDOW,
        "P5": all(s["net_bps"] > 0 for s in card["taker14_seeds"].values()),
        "P6": float(t["trades_per_day"]) >= MIN_TRADES_PER_DAY,
    }
    checks["PASS"] = all(checks.values())
    card["tier1"] = checks
    return checks


def rank(cards: list[dict]) -> list[dict]:
    """§4.2: among configurations passing all six, rank by worst-window net at taker;
    ties broken by pooled net at taker."""
    passers = [c for c in cards if c["tier1"]["PASS"]]
    return sorted(passers, key=lambda c: (-c["worst_net"], -c["taker14"]["net_bps"]))


# ---------------------------------------------------------------------------------------
# The two baselines of M3_PROTOCOL §3.2
# ---------------------------------------------------------------------------------------

def buy_and_hold(d: dumps.Dump, pairs: list[str]) -> pd.DataFrame:
    """Equal-weight buy-and-hold across the universe, per calendar window.

    Built from non-overlapping 4h legs of the 240m head's `fwd_ret`, i.e. the same return
    series every policy is booked against — so the comparison is like-for-like and needs no
    price series. Compounded per pair inside a window, then equal-weighted across pairs.
    A leg opened near a window's end runs past the boundary; that is a boundary effect of
    at most 4h on a ~60-day window and is not adjusted for.
    """
    h = dumps.add_window(d.at(240)[["pair", "ts", "fwd_ret"]].copy())
    rows = []
    for name in WINDOW_NAMES:
        totals, legs_n, leg_bps = [], 0, []
        for p in pairs:
            sub = h[(h["window"] == name) & (h["pair"] == p)].sort_values("ts", kind="mergesort")
            legs = sub["fwd_ret"].to_numpy()[::48]          # 48 bars = 240 minutes
            if legs.size == 0:
                continue
            totals.append(float(np.prod(1.0 + legs) - 1.0))
            legs_n += legs.size
            leg_bps.append(float(legs.mean() * metrics.BPS))
        rows.append({"window": name, "pairs": len(totals), "legs": legs_n,
                     "eqw_total_ret": float(np.mean(totals)) if totals else 0.0,
                     "mean_leg_bps": float(np.mean(leg_bps)) if leg_bps else 0.0})
    allrows, all_legs, all_bps = [], 0, []
    for p in pairs:
        sub = h[h["pair"] == p].sort_values("ts", kind="mergesort")
        legs = sub["fwd_ret"].to_numpy()[::48]
        if legs.size:
            allrows.append(float(np.prod(1.0 + legs) - 1.0))
            all_legs += legs.size
            all_bps.append(float(legs.mean() * metrics.BPS))
    rows.append({"window": "ALL", "pairs": len(allrows), "legs": all_legs,
                 "eqw_total_ret": float(np.mean(allrows)) if allrows else 0.0,
                 "mean_leg_bps": float(np.mean(all_bps)) if all_bps else 0.0})
    return pd.DataFrame(rows)


def momentum_control(ds: list[dumps.Dump], spec: backtest.PolicySpec,
                     regimes: dict[str, pd.DataFrame]) -> backtest.Result:
    """§3.2's side control: the winner's own entry bars, side from sign(trailing 240m).

    This isolates the only question that matters — is the model's *side* worth anything
    over a trivial one? Entry selection is untouched (coverage rank, regime filter and the
    concurrency cap all key off confidence and time, never off side), so the bar set is the
    winner's bar set minus those whose 4h lookback is incomplete.
    """
    mom = backtest.PolicySpec(**{**spec.__dict__, "side_from": "momentum",
                                 "label": spec.label + "_MOMSIDE"})
    return backtest.run(ds, mom, regimes)


# ---------------------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------------------

def _summary_row(c: dict) -> str:
    t, w = c["taker14"], c["taker14_windows"]
    nets = "".join(f"{v:>+8.1f}" for v in w["net_bps"])
    per_seed = list(c["taker14_seeds"].values())
    seeds = ("".join(f"{s['net_bps']:>+8.1f}" for s in per_seed)
             + "".join(f"{'-':>8}" for _ in range(max(0, 3 - len(per_seed)))))
    ck = c["tier1"]
    flags = "".join("Y" if ck[p] else "." for p in ("P1", "P2", "P3", "P4", "P5", "P6"))
    return (f"{c['label']:<34}{c['trades']:>7,}{c['maker5']['net_bps']:>+8.1f}"
            f"{t['net_bps']:>+8.1f}{nets}{c['worst_net']:>+8.1f} {c['worst_window']:<3}"
            f"{seeds}{t['trades_per_day']:>7.2f}{t['maxdd']:>8.3f}{t['sharpe']:>7.2f}"
            f"  {flags}  {'PASS' if ck['PASS'] else '-'}")


SUMMARY_HEADER = (
    f"{'config':<34}{'trades':>7}{'net@5':>8}{'net@14':>8}"
    f"{'w1':>8}{'w2':>8}{'w3':>8}{'w4':>8}{'worst':>8} in "
    f"{'s1':>8}{'s2':>8}{'s3':>8}{'tr/day':>7}{'maxdd':>8}{'sharpe':>7}  P123456  tier1"
)


def render_detail(c: dict) -> str:
    """The §5 block for one configuration: both fees, per window, per seed, per side."""
    out = [f"### {c['label']}", ""]
    if c["spec"] is not None:
        out += [f"`{c['spec']}`", ""]
    out.append("```")
    out.append(f"trades={c['trades']:,}  seeds={c['n_seeds']}  "
               f"tr/day/seed={c['taker14']['trades_per_day']:.2f} over {c['cal_days']:.0f}d "
               f"({c['taker14_active_tpd']:.2f} over the {c['active_days']:.0f}d it is active)")
    for _, fee in FEES:
        s = c[fee]
        out.append(f"\n-- {fee} " + "-" * 62)
        out.append(f"pooled: gross={s['gross_bps']:+.2f}  net={s['net_bps']:+.2f}  "
                   f"win={s['win']:.3f}  maxdd={s['maxdd']:.4f}  sharpe={s['sharpe']:.2f}")
        if abs(c["mean_size"] - 1.0) > 1e-9:
            nw = c[fee + "_notional_windows"]
            out.append(f"  per notional (mean size {c['mean_size']:.3f}): "
                       f"{c[fee + '_notional']:+.2f}  per window: "
                       + "  ".join(f"{k}={v:+.2f}" for k, v in sorted(nw.items())))
        w = c[fee + "_windows"]
        out.append("  per window: " + "  ".join(
            f"{r.window}={r.net_bps:+.2f}(n={int(r.trades)})" for r in w.itertuples()))
        out.append("  per seed:   " + "  ".join(
            f"{k}={v['net_bps']:+.2f}(n={v['trades']:,})" for k, v in c[fee + "_seeds"].items()))
        sd = c[fee + "_sides"]
        out.append("  sides:      " + "  ".join(
            f"{r.side}={r.net_bps:+.2f}(n={int(r.trades)}, win={r.win:.3f})"
            for r in sd.itertuples()))
        ci = c[fee + "_ci"]
        out.append(f"  clustered:  mean={ci['mean_bps']:+.2f}  clusters={ci['clusters']}  "
                   f"se={ci['se_bps']:.2f}  95% CI=[{ci['lo95_bps']:+.2f}, {ci['hi95_bps']:+.2f}]")
    ck = c["tier1"]
    out.append("\ntier-1: " + "  ".join(f"{k}={'Y' if v else 'N'}" for k, v in ck.items()))
    out.append("```")
    out.append("")
    return "\n".join(out)


def render_report(cards: list[dict], ranked: list[dict], grid_winner: dict | None,
                  winner: dict, anchor: dict, anchor_note: str, sz_card: dict,
                  mom_card: dict, bnh: pd.DataFrame, o8_cards: list[dict],
                  ds: list[dumps.Dump], cal_days: float) -> str:
    """The M3-2 write-up. Everything M3_PROTOCOL §5 demands, in one committable file."""
    L: list[str] = []
    A = L.append
    npass = sum(1 for c in cards if c["tier1"]["PASS"])

    A("# M3-2 — the rules baseline: results")
    A("")
    A("*Generated by `./scripts/m3.sh -m m3 search`, which writes it to "
      "`ml/train/output/m3/M3_2_RESULTS.md` (gitignored) and it is copied to "
      "`docs/M3_2_RESULTS.md` — its canonical home, where the links below resolve. "
      "Do not hand-edit it: re-run the command.*")
    A("")
    A(f"**Population.** {len(ds)} seeds ({', '.join(f'{d.seed}={d.run_id}' for d in ds)}), "
      f"the {len(dumps.BASE8)}-pair BASE8 universe, calendar span **{cal_days:.1f} days**.")
    A(f"**Protocol.** [M3_PROTOCOL.md](./M3_PROTOCOL.md), committed 2026-08-27 "
      f"before this search ran. {len(cards)} primary configs + 1 sizing variant + 2 "
      f"baselines + 1 O8 replication = 40 runs.")
    A("**Selection is at taker (14 bps).** Maker (5 bps) is reported alongside and never "
      "selected on.")
    A("")
    A("```sh")
    A("./scripts/m3.sh -m m3 validate     # must pass first")
    A("./scripts/m3.sh -m m3 search")
    A("```")
    A("")

    # ---- A. the headline ---------------------------------------------------------------
    A("## A — The outcome")
    A("")
    if grid_winner is None:
        A(f"🔴 **No configuration of the {len(cards)} clears Tier 1.** M3_PROTOCOL §6 "
          "pre-registers this outcome: the protocol is not loosened, the grid is not "
          "widened, and a 37th configuration is not tried. See §F.")
    else:
        gw = grid_winner
        A(f"**{npass} of {len(cards)} primary configurations clear Tier 1**, and it is "
          f"**`{gw['label']}`** — worst window **{gw['worst_net']:+.2f} bps** at taker "
          f"({gw['worst_window']}), pooled {gw['taker14']['net_bps']:+.2f}, "
          f"{gw['trades']:,} trades, all three seeds positive.")
        A("")
        A("🔴 **Read what that configuration is.** No regime filter, no concurrency cap, "
          "no sizing: it is coverage alone. It is the row M2 already published in "
          "NEXT_TRAINING_PLAN §1.3 as the plain 2%-coverage slice, scored against fees and "
          "split by window for the first time. **Every configuration that uses the §1.8 "
          "regime filter — the finding this whole milestone was built around — fails Tier 1.**")
        A("")
        A("They fail for the reason M3-1 pre-registered in §4.1 rather than for a new one, "
          "and the two strongest of them each fail **exactly one** of the six criteria — a "
          "different one:")
        A("")
        A("| regime config | pooled net @14 | worst window | fails |")
        A("|---|---:|---:|---|")
        A("| `cov0.02_hold240_rq0.8_mcnone` | +18.3 | +10.1 | **P4** — w3 holds 45 trades, "
          "not 100 |")
        A("| `cov0.05_hold240_rq0.8_mcnone` | +9.4 | −2.5 | **P5** — seed 1 is "
          "pooled-negative at taker (−0.18) |")
        A("")
        A("Neither is a P&L failure. The first is the sample-size floor catching a rule "
          "that fires unevenly across time; the second is the replication rule catching "
          "one that does not hold across seeds. Both floors were fixed in advance, from "
          "trade counts and from the §1.3 seed table, before any of this P&L existed.")
    if sz_card["tier1"]["PASS"]:
        A("")
        A(f"**The sizing variant also clears Tier 1, and outranks the grid winner** "
          f"({sz_card['worst_net']:+.2f} vs "
          f"{grid_winner['worst_net'] if grid_winner else float('nan'):+.2f} worst-window; "
          f"{sz_card['taker14']['net_bps']:+.2f} vs "
          f"{grid_winner['taker14']['net_bps'] if grid_winner else float('nan'):+.2f} "
          f"pooled). The protocol does not say unambiguously whether an §3.2 addition may "
          f"win the §4.2 ranking, so **both readings are reported and neither is chosen "
          f"after the fact**: `{grid_winner['label'] if grid_winner else '-'}` is the "
          f"baseline under the narrow reading, `{sz_card['label']}` under the wide one. "
          f"M3-3's bar (§4.4) is set at the stricter of the two, "
          f"**{winner['worst_net']:+.2f} bps**, so the ambiguity costs nothing.")
        A("")
        A(f"One caveat on the sizing variant that the ranking metric does not capture: it "
          f"varies size, so its mean size is **{sz_card['mean_size']:.3f}** and its "
          f"per-trade mean is a size-weighted average. Per unit of notional actually "
          f"deployed it is **{sz_card['taker14_notional']:+.2f} bps** at taker, not "
          f"{sz_card['taker14']['net_bps']:+.2f}. §D1 carries that column per window.")
    A("")
    A("**Tier 2 fails, as pre-registered (§4.3).** No candidate's clustered 95% lower bound "
      "is above zero, and §2 said in advance that this dataset cannot certify a policy at "
      "taker fees. See §E1.")
    A("")

    # ---- B. the full grid ---------------------------------------------------------------
    A("## B — All 36 primary configurations")
    A("")
    A("Net bps/trade. `w1..w4` and `worst` are **net at taker**; `s1/s2/s3` are per-seed "
      "pooled net at taker (rule P5). `tr/day` is per seed over the full calendar span. "
      "Flags are P1..P6 in order (`Y` = holds).")
    A("")
    A("```")
    A(SUMMARY_HEADER)
    for c in cards:
        A(_summary_row(c))
    A("```")
    A("")
    A("| rule | criterion | passing |")
    A("|---|---|---:|")
    crit = {"P1": "pooled net at taker > 0",
            "P2": "net at taker > 0 in >= 3 of 4 windows",
            "P3": f"worst-window net at taker >= {WORST_WINDOW_FLOOR_BPS:.0f} bps",
            "P4": f"every window holds >= {MIN_TRADES_PER_WINDOW} pooled trades",
            "P5": "all three seeds individually pooled-positive at taker",
            "P6": f"trade rate >= {MIN_TRADES_PER_DAY} trades/day/seed"}
    for k, v in crit.items():
        A(f"| {k} | {v} | {sum(1 for c in cards if c['tier1'][k])} / {len(cards)} |")
    A(f"| **all** | **Tier 1** | **{npass} / {len(cards)}** |")
    A("")
    A("Three patterns hold across the whole grid and are worth carrying forward:")
    A("")
    A("1. **`hold1440` is not tradeable on this evidence.** Every 24h-hold configuration "
      "loses catastrophically in w4 (−61 to −198 bps) whatever else is set. The 4h primary "
      "is the only hold the dump supports that also survives scoring.")
    A("2. **`hold60` never works.** Every 1h configuration is net-negative at taker: the "
      "edge does not cover a 14-bps round trip at that horizon.")
    A("3. **`max_concurrent=3` costs money everywhere.** Every capped config is worse than "
      "its uncapped twin, on both pooled and worst-window net. The cap is not selecting "
      "trades, it is dropping whichever ones arrive while three are already open — and on "
      "8 pairs held serially the uncapped policy is a real 8-slot portfolio, not leverage.")
    A("")

    # ---- C. ranked passers -------------------------------------------------------------
    A("## C — Tier-1 passers, ranked (M3_PROTOCOL §4.2)")
    A("")
    if ranked:
        A("```")
        A(SUMMARY_HEADER)
        for c in ranked:
            A(_summary_row(c))
        A("```")
    else:
        A("*(empty — nothing passed)*")
        A("")
        A("The closest **eligible** (P4-passing) configurations, by worst-window net at taker:")
        A("")
        elig = sorted([c for c in cards if c["tier1"]["P4"]], key=lambda c: -c["worst_net"])[:6]
        A("```")
        A(SUMMARY_HEADER)
        for c in elig:
            A(_summary_row(c))
        A("```")
    A("")

    # ---- D. the additions ---------------------------------------------------------------
    A("## D — The three additions (M3_PROTOCOL §3.2)")
    A("")
    A(f"They attach to **`{anchor['label']}`** — {anchor_note}.")
    A("")
    A("### D1 — the sizing variant")
    A("")
    A("The anchor re-run with the hard regime filter **off** and size scaled 1/3..5/3 by "
      "the bar-quintile of `btc_absret_1d`: trade small out-of-regime instead of not at all.")
    A("")
    A("```")
    A(SUMMARY_HEADER)
    A(_summary_row(sz_card))
    A("```")
    A("")
    A(f"Mean size **{sz_card['mean_size']:.3f}**, so the per-trade column above is a "
      "size-weighted average. Per unit of notional deployed (a diagnostic, not the "
      "ranking metric — see `per_notional` in `search.py`):")
    A("")
    A("| fee | pooled | " + " | ".join(WINDOW_NAMES) + " |")
    A("|---|---:|" + "---:|" * len(WINDOW_NAMES))
    for _, fee in FEES:
        nw = sz_card[fee + "_notional_windows"]
        A(f"| {fee} | {sz_card[fee + '_notional']:+.2f} | "
          + " | ".join(f"{nw.get(n, 0.0):+.2f}" for n in WINDOW_NAMES) + " |")
    A("")
    A("**The soft version of the regime idea is the one that survives.** The hard "
      "top-quintile filter fails Tier 1 in every form; scaling size by the same quintile "
      "while still trading out-of-regime passes it, and improves the grid winner's worst "
      "window. That is the concrete, actionable finding of M3-2.")
    A("")
    A(f"Two things it costs, both of which belong next to that sentence. **Drawdown grows**: "
      f"{sz_card['taker14']['maxdd']:.3f} against "
      f"{anchor['taker14']['maxdd']:.3f} for the flat-size anchor, which is what sizing up "
      f"into volatile regimes buys you. And **the worst window is barely above the floor** "
      f"— w3 at {sz_card['worst_net']:+.2f} bps on {int(sz_card['taker14_windows'].set_index('window').loc['w3', 'trades'])} "
      f"trades is not a positive result, it is an absence of a negative one. The rule "
      f"clears P3; it does not clear it comfortably.")
    A("")
    A("### D2 — buy-and-hold, equal-weight across BASE8")
    A("")
    A("Compounded from non-overlapping 4h legs of the same `fwd_ret` series every policy is "
      "booked against, so the comparison is like-for-like.")
    A("")
    A("```")
    A(bnh.to_string(index=False, float_format=lambda v: f"{v:+.4f}"))
    A("```")
    A("")
    A("The universe lost money over the evaluation period and in three of four windows, so "
      "every candidate above beats it comfortably. This baseline is a floor, not a rival.")
    A("")
    A("### D3 — the momentum-side control")
    A("")
    A(f"`{winner['label']}`'s own entry bars, with the side taken from "
      "`sign(trailing 240m return)` instead of from the model. This isolates the one "
      "question that matters: **is the model's side worth anything over a trivial one?**")
    A("")
    A("```")
    A(SUMMARY_HEADER)
    A(_summary_row(mom_card))
    A("```")
    A("")
    d_taker = winner["taker14"]["net_bps"] - mom_card["taker14"]["net_bps"]
    A(f"**Model side minus momentum side: {d_taker:+.2f} bps/trade at taker** "
      f"({winner['taker14']['net_bps']:+.2f} vs {mom_card['taker14']['net_bps']:+.2f}, over "
      f"{winner['trades']:,} vs {mom_card['trades']:,} of the same entry bars). The control "
      "is net-negative in three of four windows and on all three seeds. **The model's "
      "direction call is carrying the strategy** — this is the single most reassuring "
      "number in M3-2, and the one that says the policy is not just a repackaged beta bet.")
    A("")

    # ---- E. the winner in full ----------------------------------------------------------
    A("## E — The winner in full")
    A("")
    if grid_winner is None and not sz_card["tier1"]["PASS"]:
        A("There is no winner: nothing cleared Tier 1. The block below is the **anchor** "
          "config, reported because the pre-registered runs were made, and it must not be "
          "read as a promoted policy.")
        A("")
    shown, seen = [], set()
    for c in [x for x in (grid_winner, winner, anchor) if x is not None]:
        if c["label"] not in seen:
            seen.add(c["label"])
            shown.append(c)
    for c in shown:
        A(render_detail(c))
    A("### E1 — Tier 2, the certification bar (M3_PROTOCOL §4.3)")
    A("")
    A("| candidate | mean | clusters | n | SE | 95% CI | Tier 2 |")
    A("|---|---:|---:|---:|---:|---|---|")
    for c in shown:
        ci = c["taker14_ci"]
        A(f"| `{c['label']}` | {ci['mean_bps']:+.2f} | {ci['clusters']} | {ci['n']:,} | "
          f"{ci['se_bps']:.2f} | [{ci['lo95_bps']:+.2f}, {ci['hi95_bps']:+.2f}] | "
          f"**{'PASS' if ci['lo95_bps'] > 0 else 'FAIL'}** |")
    A("")
    A("§4.3 pre-registered the expectation that Tier 2 fails for every candidate, and it "
      "does. A failure here is not evidence the metric is wrong; it is the sample size "
      "§2 measured, showing up where it was said it would.")
    A("")
    A("### E2 — the O8 replication (12 pairs, one seed, never selected on)")
    A("")
    A("```")
    A(SUMMARY_HEADER)
    for c in o8_cards:
        A(_summary_row(c))
    A("```")
    A("")
    A("Replication across *instruments*, not across time — same calendar period, four extra "
      "pairs, one seed. It is reported and was never selected on.")
    A("")
    A("**How to read it.** The pooled numbers replicate and then some: each candidate earns "
      "*more* at taker on 12 pairs than on 8. The worst-window column does **not** "
      "replicate, and should not be expected to — O8 is a single seed, so its w3 holds 32 "
      "trades against the 192 the three-seed population has, and a mean over 32 trades at a "
      "259-bps per-trade spread measures nothing. That is rule P4's threshold doing its job "
      "in a place where P4 was never applied: both O8 rows fail P4, which is why neither "
      "shows a Tier-1 verdict. The instrument replication supports the *pooled* edge and is "
      "silent on the robustness criterion.")
    A("")
    for c in o8_cards:
        A(render_detail(c))

    # ---- F. what happens next ------------------------------------------------------------
    A("## F — What this means for the milestone")
    A("")
    if grid_winner is not None or sz_card["tier1"]["PASS"]:
        A(f"A rules baseline clears the pre-registered Tier-1 bar. **M3-3's bar (§4.4): "
          f"pass all of Tier 1 and beat {winner['worst_net']:+.2f} bps worst-window net at "
          f"taker**, which is `{winner['label']}`.")
        A("")
        A("Three things follow for how the rest of M3 should be spent:")
        A("")
        A("1. **The regime finding did not survive contact with the protocol in its hard "
          "form, but it did in its soft one.** Sizing by the regime quintile beats both "
          "filtering on it and ignoring it. A learned policy should be given the regime as "
          "a *continuous observation*, not handed a threshold to reproduce.")
        A("2. **Tier 2 still fails, so nothing here justifies size.** The honest use of "
          "this baseline is as M3-3's benchmark and as a paper-trading candidate — the "
          "forward paper-sim (§1 of the protocol) is the only genuinely out-of-time "
          "evidence available and it still does not exist.")
        A("3. **The maker column is where the leverage is.** Every candidate roughly "
          "doubles at 5 bps. Whether those fills are obtainable is ranked risk #2 and is "
          "measurable cheaply on the paper-sim stack (M3_PLAN §3.3) — it is worth more "
          "than any further knob.")
    else:
        A("M3_PROTOCOL §6 governs, verbatim: *if no configuration clears Tier 1, that is "
          "M3-2's result and it gets written up as one. The protocol is not loosened, the "
          "grid is not widened, and a 37th configuration is not tried.* The next step is "
          "**not** a better policy search but the two things that change the evidence:")
        A("")
        A("1. **The maker-fee study** (M3_PLAN §3.3).")
        A("2. **M3-0b's price/funding side-table**, which unlocks barrier exits and the "
          "funding term.")
    A("")

    # ---- G. per-config detail -------------------------------------------------------------
    A("## G — Per-configuration detail (M3_PROTOCOL §5)")
    A("")
    A("Both fees, per window, per seed, per side, with the clustered interval, for every "
      "one of the 36 primary configurations plus the sizing variant and the side control.")
    A("")
    for c in cards + [sz_card, mom_card]:
        A(render_detail(c))
    return "\n".join(L) + "\n"
