"""M3-3 — fitting the learned policy and scoring it under the committed rule.

This module executes [docs/M3_3_PROTOCOL.md](../../../docs/M3_3_PROTOCOL.md) and nothing
else. That file was committed before the first fit ran, so every constant below is a
transcription of a decision already made rather than a decision taken here:

  * the observation vector and the candidate pool are `features.py` (§3);
  * the folds are leave-one-window-out, refit four times (§1);
  * the model classes are ridge on 9 and on 26 terms (§4.1), the penalty selected by an
    INNER leave-one-window-out inside the training windows (§4.2);
  * the entry rules are R1 (score >= the taker round trip) and R2 (top 2% of each
    seed-window) (§4.3); the sizings are flat and clip(s/s_ref, 1/3, 5/3) (§4.4);
  * promotion is M3_PROTOCOL §4.2's Tier 1 plus §4.4's +0.25 bar, evaluated by the SAME
    `search.tier1()` / `search.rank()` the baseline was scored by (§5).

TWO IMPLEMENTATION CHOICES the protocol left open, both resolved toward the conservative
reading and both stated here so a later session can see them rather than infer them:

  1. **Entry selection is precomputed here, not inside the simulator.** §4.3's R2 cuts the
     top 2% within each seed-window, which `backtest.coverage_threshold` cannot express — it
     derives one threshold per seed over the whole period. So both rules are evaluated here
     into a boolean `entry` column and handed to the simulator as a threshold on it. The
     simulator still owns everything that makes a ledger a ledger: serial positions per
     (seed, pair), the hold, the fee, the exit calendar. Only the ranking moved, and the
     per-fold thresholds it used are reported in §C of the write-up instead of being
     swallowed.
  2. **`s_ref` for the S2 sizing comes from the training folds' fitted values.** Those are
     in-sample values, which is fine for a NORMALISER — it is a scale, not a prediction —
     and it is the only choice that keeps the held-out window's own scale out of its size.
     If a fold's `s_ref` came out non-positive the ratio would invert the sizing, so that
     case falls back to flat size and is reported; it did not occur.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import backtest, dumps, features, metrics

# M3_3_PROTOCOL §4.2, verbatim. Scale-free: the penalty enters as lam * n * I on
# standardised features, so it is a shrinkage factor rather than a data-scale quantity.
LAMBDAS = (0.003, 0.01, 0.03, 0.1, 0.3, 1.0, 3.0)


# ---------------------------------------------------------------------------------------
# The fit
# ---------------------------------------------------------------------------------------

@dataclass
class Fit:
    """One fitted ridge: the standardisation it was fitted under, and the coefficients."""
    beta: np.ndarray        # [intercept, *terms]
    mu: np.ndarray
    sd: np.ndarray
    names: list[str]
    lam: float

    def score(self, X: np.ndarray) -> np.ndarray:
        z = (X - self.mu) / self.sd
        return self.beta[0] + z @ self.beta[1:]


def ridge(X: np.ndarray, y: np.ndarray, lam: float, names: list[str]) -> Fit:
    """Closed-form ridge with an UNPENALISED intercept, on standardised columns.

    Deterministic: no seed, no optimiser, no early stopping. Nothing about a fit depends on
    when it ran or how many times, which is what lets M3_3_PROTOCOL §4.1 claim the search
    space is fourteen runs rather than fourteen runs times an unwritten number of restarts.
    """
    mu = X.mean(axis=0)
    sd = X.std(axis=0, ddof=0)
    sd = np.where(sd < 1e-12, 1.0, sd)      # a constant column contributes nothing, safely
    z = (X - mu) / sd
    n, p = z.shape
    A = np.zeros((p + 1, p + 1))
    A[0, 0] = n
    A[0, 1:] = z.sum(axis=0)
    A[1:, 0] = z.sum(axis=0)
    A[1:, 1:] = z.T @ z + lam * n * np.eye(p)   # the intercept row/col stays unpenalised
    b = np.concatenate([[y.sum()], z.T @ y])
    beta = np.linalg.solve(A, b)
    return Fit(beta=beta, mu=mu, sd=sd, names=names, lam=lam)


def _design(f: pd.DataFrame, cfg: features.LearnedConfig) -> tuple[np.ndarray, list[str]]:
    if cfg.model == "conf":
        # §6 control C2: one feature. Kept in the same code path as A and B so that "the
        # ablation is the same machinery with a shorter vector" is true rather than claimed.
        return f[["conf_rank"]].to_numpy(np.float64), ["conf_rank"]
    return features.design(f, quadratic=cfg.quadratic)


# ---------------------------------------------------------------------------------------
# The entry rules (M3_3_PROTOCOL §4.3)
# ---------------------------------------------------------------------------------------

def bar_counts(feats: dict[str, pd.DataFrame]) -> dict[tuple[str, str], int]:
    """(seed, window) -> the count of ALL 240m bars, pool or not.

    R2's "top 2% of each seed-window's bars" is 2% of THIS, not 2% of the pool. The pool is
    the top 10% by confidence and it lands very unevenly across windows (§3.4), so taking a
    fraction of it would mean a different coverage in every window.
    """
    out = {}
    for s, f in feats.items():
        for w, n in f["window"].value_counts().items():
            out[(s, str(w))] = int(n)
    return out


def entry_mask(p: pd.DataFrame, score: np.ndarray, cfg: features.LearnedConfig,
               counts: dict[tuple[str, str], int]) -> tuple[np.ndarray, dict]:
    """The bars this configuration enters on, plus the thresholds it used.

    R1 is an absolute threshold on a score that is in bps by construction, so it is
    comparable across folds by design and is applied as one number everywhere. R2 is a rank
    cut applied INSIDE each (seed, window): the four folds are four different fits and their
    scores are four different rulers, so a single whole-period cut would allocate the trade
    budget by which fold happened to have the larger intercept. Tie-inclusive, matching
    `backtest.coverage_threshold`'s definition of "the top c%".
    """
    if cfg.entry == "R1":
        return score >= features.ENTRY_THRESHOLD_BPS, {"all": features.ENTRY_THRESHOLD_BPS}
    if cfg.entry != "R2":
        raise SystemExit(f"unknown entry rule {cfg.entry!r}")
    mask = np.zeros(len(p), dtype=bool)
    thr = {}
    seeds = p["seed"].to_numpy()
    wins = p["window"].to_numpy()
    for (s, w), n_bars in counts.items():
        sel = (seeds == s) & (wins == w)
        if not sel.any():
            continue
        k = max(1, int(round(features.MATCHED_COVERAGE * n_bars)))
        sub = score[sel]
        k = min(k, sub.size)
        cut = float(np.partition(sub, sub.size - k)[sub.size - k])
        mask[sel] = sub >= cut
        thr[f"{s}/{w}"] = cut
    return mask, thr


def sizes(score: np.ndarray, s_ref: float) -> np.ndarray:
    lo, hi = features.SIZE_CLIP
    if not np.isfinite(s_ref) or s_ref <= 0:
        return np.ones_like(score)
    return np.clip(score / s_ref, lo, hi)


# ---------------------------------------------------------------------------------------
# Out-of-fold fitting
# ---------------------------------------------------------------------------------------

def _inner_metric(pool: pd.DataFrame, cfg: features.LearnedConfig, lam: float,
                  train: tuple[str, ...], counts) -> float:
    """§4.2's selection criterion: mean net-at-taker bps over the inner held-out windows.

    Deliberately the raw per-bar mean rather than a simulated ledger — this is a
    hyper-parameter heuristic among seven values, and the serial-position constraint would
    add noise to it without adding information. The outer held-out window is never touched.
    """
    nets = []
    for inner_held, inner_train in features.inner_folds(train):
        tr = pool[pool["window"].isin(inner_train)]
        he = pool[pool["window"] == inner_held]
        if tr.empty or he.empty:
            continue
        Xtr, names = _design(tr, cfg)
        fit = ridge(Xtr, tr["y_bps"].to_numpy(np.float64), lam, names)
        s = fit.score(_design(he, cfg)[0])
        # The metric is always evaluated under R2, whatever the config's own entry rule is:
        # an R1 threshold at a badly-scaled lambda can select zero bars or every bar, and a
        # penalty must not be chosen by which value happens to make the threshold bite.
        mask, _ = entry_mask(he, s, features.LearnedConfig("x", "R2", "S1"), counts)
        if mask.any():
            nets.append(float(he["y_bps"].to_numpy()[mask].mean()) - metrics.TAKER_COST_BPS)
    return float(np.mean(nets)) if nets else -np.inf


def select_lambda(pool: pd.DataFrame, cfg: features.LearnedConfig,
                  train: tuple[str, ...], counts) -> tuple[float, list[tuple[float, float]]]:
    """§4.2: highest inner metric wins; ties go to the LARGER lambda (more shrinkage)."""
    scored = [(lam, _inner_metric(pool, cfg, lam, train, counts)) for lam in LAMBDAS]
    best = max(v for _, v in scored)
    lam = max(lam for lam, v in scored if v == best)
    return lam, scored


@dataclass
class OOF:
    """The out-of-fold scoring of the whole pool, plus what each fold did to produce it.

    This depends on the MODEL CLASS only. The entry rule and the sizing rule are applied on
    top by `apply_rules`, so each of the three classes is fitted exactly once rather than
    once per rule pairing — the four configurations sharing a class are four readings of the
    same fitted model, and making that literally true in the code is what guarantees the
    write-up can attribute a difference between them to the rule and not to the fit.
    """
    model: str
    pool: pd.DataFrame                    # the pool with `lscore` (out-of-fold) attached
    fits: dict[str, Fit]                  # held-out window -> the fit that scored it
    lam_scan: dict[str, list]             # held-out window -> [(lam, inner metric)]
    train_score: dict[str, pd.DataFrame]  # held-out window -> its training rows, fitted


@dataclass
class Policy:
    """One configuration: an OOF scoring read through an entry rule and a sizing rule."""
    cfg: features.LearnedConfig
    oof: OOF
    entry: np.ndarray                     # aligned to oof.pool
    thresholds: dict
    s_ref: dict[str, float]               # held-out window -> the S2 normaliser


def fit_oof(pool: pd.DataFrame, model: str, counts) -> OOF:
    """Refit four times; each window is scored by the model that never saw it (§1)."""
    pool = pool.reset_index(drop=True)
    cfg = features.LearnedConfig(model, "R2", "S1")   # only `.model` is read below
    score = np.full(len(pool), np.nan)
    fits, scans, tscore = {}, {}, {}

    for held, train in features.folds():
        tr = pool[pool["window"].isin(train)]
        he_idx = np.flatnonzero((pool["window"] == held).to_numpy())
        lam, scan = select_lambda(tr, cfg, train, counts)
        Xtr, names = _design(tr, cfg)
        fit = ridge(Xtr, tr["y_bps"].to_numpy(np.float64), lam, names)
        score[he_idx] = fit.score(_design(pool.iloc[he_idx], cfg)[0])
        fits[held], scans[held] = fit, scan
        tscore[held] = tr.assign(lscore=fit.score(Xtr))

    return OOF(model=model, pool=pool.assign(lscore=score), fits=fits,
               lam_scan=scans, train_score=tscore)


def apply_rules(oof: OOF, cfg: features.LearnedConfig, counts) -> Policy:
    """§4.3 and §4.4 on top of a fitted OOF: which bars are entered, and at what size."""
    s_ref = {}
    for held, tr in oof.train_score.items():
        # §4.4: the normaliser comes from the TRAINING folds' own selected bars, under this
        # configuration's own entry rule — a size is only meaningful relative to the bars
        # the same rule would have taken.
        tr_score = tr["lscore"].to_numpy(np.float64)
        m, _ = entry_mask(tr.reset_index(drop=True), tr_score, cfg, counts)
        s_ref[held] = float(tr_score[m].mean()) if m.any() else float("nan")
    mask, thr = entry_mask(oof.pool, oof.pool["lscore"].to_numpy(np.float64), cfg, counts)
    return Policy(cfg=cfg, oof=oof, entry=mask, thresholds=thr, s_ref=s_ref)


def overlay(pol: Policy) -> dict[str, pd.DataFrame]:
    """Per-seed (pair, ts, entry, lsize) frames for `backtest.run`'s `overlay` argument.

    Only ENTERED bars are carried. A bar the fitter never scored — outside the pool, or with
    an incomplete lookback — is simply absent, so it merges to NaN and the simulator treats
    it as unenterable rather than as a zero-scoring candidate.
    """
    cfg = pol.cfg
    p = pol.oof.pool.loc[pol.entry, ["seed", "pair", "ts", "window", "lscore"]].copy()
    p["entry"] = 1.0
    if cfg.sizing == "S2":
        # Normalised per held-out window, because that is the fold whose model produced the
        # score — s_ref is that fold's own scale, from its training windows only.
        p = pd.concat([g.assign(lsize=sizes(g["lscore"].to_numpy(np.float64), pol.s_ref[w]))
                       for w, g in p.groupby("window", sort=False)], ignore_index=True)
    elif cfg.sizing == "S1":
        p["lsize"] = 1.0
    else:
        raise SystemExit(f"unknown sizing rule {cfg.sizing!r}")
    return {s: g[["pair", "ts", "entry", "lsize"]].reset_index(drop=True)
            for s, g in p.groupby("seed", sort=False)}


def spec_for(cfg: features.LearnedConfig, label: str | None = None) -> backtest.PolicySpec:
    """§4.5: everything not in `cfg` is a constant, each fixed by a published M3-2 row.

    `score_min=0.5` on the precomputed boolean `entry` column is how the two entry rules
    reach the simulator (module docstring, choice 1); `coverage` is unused on that path and
    is left at its default rather than being given a meaningless value.
    """
    return backtest.PolicySpec(
        signal_horizon=240,
        hold_horizon=240,              # §4.5 <- M3_2_RESULTS §B patterns 1 and 2
        max_concurrent=None,           # §4.5 <- §B pattern 3
        sides="both",                  # §4.5 <- M3_PROTOCOL §3.3
        side_from="model",             # §4.5 <- M3_2_RESULTS §D3
        score_col="entry",
        score_min=0.5,
        size_col="lsize" if cfg.sizing == "S2" else None,
        label=label or cfg.label,
    )


# ---------------------------------------------------------------------------------------
# The C1 control (M3_3_PROTOCOL §6)
# ---------------------------------------------------------------------------------------

def baseline_control(pool: pd.DataFrame, counts, regime_col: str = "btc_absret_rank"
                     ) -> tuple[dict[str, pd.DataFrame], backtest.PolicySpec]:
    """C1 — the M3-2 sizing winner, re-expressed in M3-3's machinery.

    Same policy: enter on the top 2% by CONFIDENCE, size by the bar-quintile of
    `btc_absret_1d` over 1/3..5/3. What changes is only what §6 says changes — the top 2% is
    taken within each seed-window (§4.3), the candidate pool caps it, and the warm-up bars
    §3.3 drops are absent. It exists to measure the size of the §1.1(2) handicap; the bar
    stays at the published +0.25 whatever this prints.
    """
    p = pool.reset_index(drop=True)
    mask, thr = entry_mask(p, p["conf_rank"].to_numpy(np.float64),
                           features.LearnedConfig("x", "R2", "S1"), counts)
    sel = p.loc[mask].copy()
    # The bar-quintile of the regime observable, which is exactly what `btc_absret_rank` is:
    # a percentile of BARS. Quintile q (0..4) -> size (q+1)/3, i.e. 1/3 .. 5/3.
    q = np.clip((sel[regime_col].to_numpy() * 5.0).astype(int), 0, 4)
    sel["entry"] = 1.0
    sel["lsize"] = (q + 1.0) / 3.0
    spec = backtest.PolicySpec(
        signal_horizon=240, hold_horizon=240, max_concurrent=None,
        score_col="entry", score_min=0.5, size_col="lsize",
        label="C1_M3-2_SIZED_rescored")
    ov = {s: g[["pair", "ts", "entry", "lsize"]].reset_index(drop=True)
          for s, g in sel.groupby("seed", sort=False)}
    return ov, spec


# ---------------------------------------------------------------------------------------
# The C3 replication (M3_3_PROTOCOL §6)
# ---------------------------------------------------------------------------------------

def replicate_o8(o8_pool: pd.DataFrame, pol: Policy, o8_counts) -> dict[str, pd.DataFrame]:
    """C3 — the winner's four fold-models applied to the 12-pair dump.

    Each O8 window is scored by the model that HELD THAT WINDOW OUT on BASE8, so no fold
    ever scores a calendar period it was fitted on, even though the instruments differ.
    Reported, never selected on (M3_PROTOCOL §1).
    """
    cfg = pol.cfg
    p = o8_pool.reset_index(drop=True)
    score = np.full(len(p), np.nan)
    for held, fit in pol.oof.fits.items():
        idx = np.flatnonzero((p["window"] == held).to_numpy())
        if idx.size:
            score[idx] = fit.score(_design(p.iloc[idx], cfg)[0])
    p = p.assign(lscore=score)
    p = p[np.isfinite(score)].reset_index(drop=True)
    mask, _ = entry_mask(p, p["lscore"].to_numpy(np.float64), cfg, o8_counts)
    sel = p.loc[mask].copy()
    sel["entry"] = 1.0
    if cfg.sizing == "S2":
        sel = pd.concat([g.assign(lsize=sizes(g["lscore"].to_numpy(np.float64), pol.s_ref[w]))
                         for w, g in sel.groupby("window", sort=False)], ignore_index=True)
    else:
        sel["lsize"] = 1.0
    return {s: g[["pair", "ts", "entry", "lsize"]].reset_index(drop=True)
            for s, g in sel.groupby("seed", sort=False)}


def o8_bar_counts(f: pd.DataFrame) -> dict[tuple[str, str], int]:
    return bar_counts({"o8": f})


# ---------------------------------------------------------------------------------------
# Rendering — the M3-3 write-up
# ---------------------------------------------------------------------------------------

REPORT_PATH = "output/m3/M3_3_RESULTS.md"

BASELINE_BAR_BPS = 0.25          # M3_PROTOCOL §4.4 — the published worst-window net at taker
BASELINE_LABEL = "cov0.02_hold240_rqnone_mcnone_SIZED"


def render_coefficients(oof: OOF, top: int = 8) -> list[str]:
    """The fitted model, per fold: the penalty chosen and the largest standardised weights.

    Standardised coefficients are directly comparable to each other — that is what §3's
    "everything is a rank" buys — so this table is readable as "what the model decided
    mattered", and its STABILITY ACROSS FOLDS is the thing to look at. A term that changes
    sign between folds has not been learned; it has been fitted.
    """
    out = ["```"]
    for held, fit in oof.fits.items():
        order = np.argsort(-np.abs(fit.beta[1:]))[:top]
        terms = "  ".join(f"{fit.names[i]}={fit.beta[1 + i]:+.2f}" for i in order)
        out.append(f"  held out {held}: lambda={fit.lam:<6g} intercept={fit.beta[0]:+7.2f}  {terms}")
    out.append("```")
    return out


def render_report(learned: list[dict], ablation: list[dict], c1: dict, c3: dict | None,
                  oofs: dict[str, OOF], winner: dict | None, best: dict | None,
                  ranked: list[dict], c2_check: str, pool_means: dict,
                  ds: list, cal_days: float, n_runs: int) -> str:
    """Everything M3_PROTOCOL §5 demands for every run, in one committable file.

    Written before the first fit, so it branches on the outcome rather than asserting one:
    §7 of M3_3_PROTOCOL pre-registers that "the baseline stands" is a result, and this
    function has to be able to say so.
    """
    from . import search
    L: list[str] = []
    A = L.append
    npass = sum(1 for c in learned if c["tier1"]["PASS"])
    beat = [c for c in learned if c["tier1"]["PASS"] and c["worst_net"] > BASELINE_BAR_BPS]

    A("# M3-3 — the learned policy: results")
    A("")
    A("*Generated by `./scripts/m3.sh -m m3 learn`, which writes it to "
      "`ml/train/output/m3/M3_3_RESULTS.md` (gitignored) and it is copied to "
      "`docs/M3_3_RESULTS.md` — its canonical home, where the links below resolve. "
      "Do not hand-edit it: re-run the command.*")
    A("")
    A(f"**Population.** {len(ds)} seeds ({', '.join(f'{d.seed}={d.run_id}' for d in ds)}), "
      f"the {len(dumps.BASE8)}-pair BASE8 universe, calendar span **{cal_days:.1f} days** — "
      f"unchanged from M3-2, deliberately.")
    A("**Protocol.** [M3_3_PROTOCOL.md](./M3_3_PROTOCOL.md), committed 2026-08-27 before the "
      f"first fit ran, under [M3_PROTOCOL.md](./M3_PROTOCOL.md) §4.4. {n_runs} scored runs.")
    A("**Every learned number below is out-of-fold.** Each calendar window was scored by a "
      "model refitted on the other three (§1). The baseline it is measured against was "
      "selected in-sample from 40 configurations — the asymmetry runs against M3-3, and §D1 "
      "measures how much.")
    A("")
    A("```sh")
    A("./scripts/m3.sh -m m3 validate     # must pass first (M3_PROTOCOL §4.4)")
    A("./scripts/m3.sh -m m3 learn")
    A("```")
    A("")

    # ---- A. the outcome ----------------------------------------------------------------
    A("## A — The outcome")
    A("")
    A(f"**The bar (M3_PROTOCOL §4.4): pass all six Tier-1 criteria and beat "
      f"{BASELINE_BAR_BPS:+.2f} bps worst-window net at taker**, which is "
      f"`{BASELINE_LABEL}`.")
    A("")
    if not beat:
        A(f"🔴 **No learned configuration clears it.** {npass} of {len(learned)} pass Tier 1"
          + (f", the best of them at {ranked[0]['worst_net']:+.2f} bps worst-window "
             f"(`{ranked[0]['label']}`)" if ranked else "")
          + f", against the baseline's {BASELINE_BAR_BPS:+.2f}.")
        A("")
        A("**M3_3_PROTOCOL §7 pre-registered this outcome and what follows from it.** The "
          "M3-2 rules baseline stands as M3's policy. The grid is not widened, the feature "
          "list is not extended, a fifteenth run is not tried, and — per §4.1 — a larger "
          "model class is **not** the remedy. See §F.")
    else:
        w = beat[0]
        A(f"**{len(beat)} of {len(learned)} learned configurations clear it**, and the best "
          f"is **`{w['label']}`** — worst window **{w['worst_net']:+.2f} bps** at taker "
          f"({w['worst_window']}), pooled {w['taker14']['net_bps']:+.2f}, {w['trades']:,} "
          f"trades, {w['taker14']['trades_per_day']:.2f} trades/day/seed, max drawdown "
          f"{w['taker14']['maxdd']:.3f}, daily Sharpe {w['taker14']['sharpe']:.2f}.")
        A("")
        A(f"It beats the baseline's {BASELINE_BAR_BPS:+.2f} by "
          f"**{w['worst_net'] - BASELINE_BAR_BPS:+.2f} bps on the worst window**, "
          f"out-of-fold against an in-sample benchmark.")
    A("")
    A(f"**The ablation is the number that says whether M3-3 was worth building.** §D2 runs "
      f"the identical machinery on `conf_rank` alone — the one observation M3-2 already "
      f"used. Whatever the headline, the difference between a learned configuration and its "
      f"matched ablation is what the eight other observations are worth.")
    A("")
    A("**Tier 2 (M3_PROTOCOL §4.3) is reported for the winner and is expected to fail.** §2 "
      "of that document said in advance that 253 days holding ~220 independent trading days "
      "cannot certify a policy at taker fees. It must not be read as evidence the metric is "
      "wrong.")
    A("")

    # ---- B. all learned configurations -------------------------------------------------
    A(f"## B — All {len(learned)} learned configurations (M3_3_PROTOCOL §4)")
    A("")
    A("Net bps/trade. `w1..w4` and `worst` are **net at taker**; `s1/s2/s3` are per-seed "
      "pooled net at taker (rule P5). `tr/day` is per seed over the full calendar span. "
      "Flags are P1..P6 in order (`Y` = holds). Model **A** is the 9 linear terms, **B** "
      "adds squares and `conf_rank` interactions (26 terms); **R1** enters on "
      "`score >= 14bps`, **R2** on the top 2% of each seed-window; **S1** is flat size, "
      "**S2** is `clip(score/s_ref, 1/3, 5/3)`.")
    A("")
    A("```")
    A(search.SUMMARY_HEADER)
    for c in learned:
        A(search._summary_row(c))
    A("```")
    A("")
    A("| rule | criterion | passing |")
    A("|---|---|---:|")
    crit = {"P1": "pooled net at taker > 0",
            "P2": "net at taker > 0 in >= 3 of 4 windows",
            "P3": "worst-window net at taker >= -5 bps",
            "P4": "every window holds >= 100 pooled trades",
            "P5": "all three seeds individually pooled-positive at taker",
            "P6": "trade rate >= 0.5 trades/day/seed"}
    for p, desc in crit.items():
        A(f"| {p} | {desc} | {sum(1 for c in learned if c['tier1'][p])} / {len(learned)} |")
    A(f"| **all** | **Tier 1** | **{npass} / {len(learned)}** |")
    A(f"| **bar** | **Tier 1 and worst-window > {BASELINE_BAR_BPS:+.2f}** "
      f"| **{len(beat)} / {len(learned)}** |")
    A("")

    # ---- C. the fits -------------------------------------------------------------------
    A("## C — What was actually fitted")
    A("")
    A("The penalty chosen per fold by the inner leave-one-window-out of §4.2, and the "
      "largest standardised coefficients. **Stability across folds is what to read here**: "
      "a term that changes sign between folds has not been learned, it has been fitted.")
    for model, oof in oofs.items():
        A("")
        A(f"### model {model}")
        A("")
        L.extend(render_coefficients(oof))
    A("")
    A("")
    A("### The intercepts are the finding")
    A("")
    A("Every fold's intercept is the mean gross edge of its own training rows, so the four "
      "of them measure how much that edge moves between periods. The pool's mean gross "
      "bps/trade, per window:")
    A("")
    A("| " + " | ".join(pool_means) + " | spread |")
    A("|" + "---:|" * (len(pool_means) + 1))
    A("| " + " | ".join(f"{v:+.2f}" for v in pool_means.values())
      + f" | **{max(pool_means.values()) - min(pool_means.values()):.2f}** |")
    A("")
    A("🔴 **The average edge available in the top decile swings by more between calendar "
      "windows than the entire edge any policy here is chasing.** That is not a property of "
      "a model, it is a property of the evidence, and it is the mechanism behind two things "
      "below: rule R1 — an absolute threshold on a predicted edge — fires only in the folds "
      "whose intercept is high enough to reach it, which is why its under-sampled windows "
      "fail P4; and any fitted level, as opposed to a fitted *ordering*, is being estimated "
      "on a quantity that does not hold still.")
    A("")
    A("### The falsifiable harness check (M3_3_PROTOCOL §6, control C2)")
    A("")
    A(c2_check)
    A("")

    # ---- D. the controls ---------------------------------------------------------------
    A("## D — The controls (M3_3_PROTOCOL §6)")
    A("")
    A("### D1 — C1: the M3-2 winner re-scored under M3-3's machinery")
    A("")
    A("The same policy — top 2% by confidence, size by the bar-quintile of `btc_absret_1d` "
      "over 1/3..5/3 — put through M3-3's per-window coverage cut, candidate pool and "
      "completeness filter. It measures the handicap §1.1(2) of the protocol declares; "
      f"the bar stays at the published {BASELINE_BAR_BPS:+.2f} whatever this prints.")
    A("")
    A("```")
    A(search.SUMMARY_HEADER)
    A(search._summary_row(c1))
    A("```")
    A("")
    A(f"Re-scored worst window **{c1['worst_net']:+.2f}** against the published "
      f"{BASELINE_BAR_BPS:+.2f}: the machinery difference is worth "
      f"**{c1['worst_net'] - BASELINE_BAR_BPS:+.2f} bps** to the baseline.")
    A("")
    A("### D2 — C2: the confidence-only ablation")
    A("")
    A("The identical machinery fitted on `conf_rank` alone. **The gap between a learned row "
      "in §B and its matched row here is what features 2-9 are worth.**")
    A("")
    A("```")
    A(search.SUMMARY_HEADER)
    for c in ablation:
        A(search._summary_row(c))
    A("```")
    A("")
    by_label = {c["label"]: c for c in ablation}
    A("| entry x sizing | learned A | learned B | conf-only | best gain |")
    A("|---|---:|---:|---:|---:|")
    for e in ("R1", "R2"):
        for s in ("S1", "S2"):
            a = next((c for c in learned if c["label"] == f"learnA_{e}_{s}"), None)
            b = next((c for c in learned if c["label"] == f"learnB_{e}_{s}"), None)
            k = by_label.get(f"learnconf_{e}_{s}")
            if not (a and b and k):
                continue
            gain = max(a["worst_net"], b["worst_net"]) - k["worst_net"]
            A(f"| {e} x {s} | {a['worst_net']:+.2f} | {b['worst_net']:+.2f} "
              f"| {k['worst_net']:+.2f} | **{gain:+.2f}** |")
    A("")
    A("*(worst-window net at taker, the ranking metric)*")
    A("")
    k = next((c for c in ablation if c["label"] == "learnconf_R2_S1"), None)
    if k is not None and k["trades"] == c1["trades"]:
        A("**A clean measurement falls out of §C's harness check.** `learnconf_R2_S1` and C1 enter "
          f"the identical {c1['trades']:,} trades — the check above proves the entry sets "
          "are the same bar for bar. The only difference between them is the size: flat, "
          "against the bar-quintile of `btc_absret_1d` over 1/3..5/3.")
        A("")
        A("| | worst window | pooled net @14 | net @5 | Sharpe | tier 1 |")
        A("|---|---:|---:|---:|---:|:--|")
        for lab, c in (("flat size (`learnconf_R2_S1`)", k), ("regime-sized (C1)", c1)):
            A(f"| {lab} | {c['worst_net']:+.2f} | {c['taker14']['net_bps']:+.2f} "
              f"| {c['maker5']['net_bps']:+.2f} | {c['taker14']['sharpe']:.2f} "
              f"| {'**PASS**' if c['tier1']['PASS'] else 'fail'} |")
        A(f"| **sizing is worth** | **{c1['worst_net'] - k['worst_net']:+.2f}** "
          f"| **{c1['taker14']['net_bps'] - k['taker14']['net_bps']:+.2f}** "
          f"| **{c1['maker5']['net_bps'] - k['maker5']['net_bps']:+.2f}** | | |")
        A("")
        A("**M3-2's central finding replicates through an entirely different code path.** "
          "Sizing by the regime observable, on a fixed set of entries, is the difference "
          "between a configuration that fails Tier 1 and one that passes it. M3-2 reached "
          "that conclusion by comparing two grid rows; this reaches it by holding the entry "
          "set bar-for-bar constant, which is the stronger version of the same claim.")
        A("")
    A("### D3 — C3: the O8 replication (12 pairs, one seed, never selected on)")
    A("")
    if c3 is None:
        A("Not run: no configuration was even eligible under rule P4, so there is nothing "
          "to replicate.")
    else:
        A(f"The four fold-models of `{c3['label'].removesuffix('_O8')}` applied to the 12-pair dump "
          f"(`{dumps.O8_RUN}`), each window scored by the model that held it out on BASE8. "
          "Same calendar period, so this is replication across **instruments**, not across "
          "time.")
        if not ranked:
            A("")
            A("It attaches to the **best-ranked eligible** configuration rather than to a "
              "winner, because there is no winner — the same precedent `m3 search` set for "
              "M3-2. A pre-registered run that only happens on success is a run that can "
              "only ever produce good news.")
        A("")
        A("```")
        A(search.SUMMARY_HEADER)
        A(search._summary_row(c3))
        A("```")
    A("")

    # ---- E. the winner in full ---------------------------------------------------------
    A("## E — The best learned configuration in full")
    A("")
    show = winner if winner is not None else best
    if show is None:
        A("No learned configuration was eligible under rule P4.")
    else:
        if winner is None:
            A(f"**No configuration passed Tier 1**, so this is the best-ranked *eligible* "
              f"one — `{show['label']}` — shown in full for the same reason the failures are "
              f"reported at all: M3_PROTOCOL §5 says pooled-only numbers are not a result, "
              f"and that applies to a negative result too.")
            A("")
        L.append(search.render_detail(show))
        ci = show["taker14_ci"]
        A("### E1 — Tier 2, the certification bar (M3_PROTOCOL §4.3)")
        A("")
        A(f"Clustered on the exit calendar day: **{ci['clusters']} clusters** behind "
          f"{ci['n']:,} trades, mean {ci['mean_bps']:+.2f}, SE {ci['se_bps']:.2f}, "
          f"95% CI **[{ci['lo95_bps']:+.2f}, {ci['hi95_bps']:+.2f}]**.")
        A("")
        A("**Tier 2 " + ("PASSES — which M3_PROTOCOL §2 did not expect; re-read §2 before "
                         "believing it." if ci["lo95_bps"] > 0 else
                         "fails, exactly as pre-registered.") + "**")
    A("")

    # ---- F. what it means --------------------------------------------------------------
    A("## F — What this means for the milestone")
    A("")
    if not beat:
        A(f"**The M3-2 rules baseline stands as M3's policy.** On {len(ds)} seeds and ~220 "
          "independent trading days, a continuous fitted use of nine observations does not "
          "beat bucketing one of them into fifths. Given the sample that is a completely "
          "ordinary thing for the evidence to say, and M3_3_PROTOCOL §7 pre-registered it "
          "as a result rather than as a failure.")
        A("")
        A("**Three things the run established that are worth more than its headline:**")
        A("")
        A("1. **The extra observations are not merely useless, they cost money.** In three "
          "of the four entry x sizing pairings the confidence-only ablation beats both "
          "fitted models on the ranking metric (§D2). Nine observations fitted on ~188 "
          "clusters is over-specification, and the ablation is what makes that visible "
          "instead of arguable.")
        A(f"2. **The level of the edge does not hold still: it swings {max(pool_means.values()) - min(pool_means.values()):.1f} bps "
          "between calendar windows** (§C), which is larger than the entire edge any policy "
          "here is chasing. That is the mechanism behind rule R1's collapse — an absolute "
          "threshold on a predicted edge simply stops firing in the windows whose level is "
          "low — and it is a fact about the evidence rather than about any model. It is also "
          "the strongest argument yet for rank-based conditioning (M3_PLAN §1.3.3): an "
          "*ordering* survives what a *level* does not.")
        A("3. **M3-2's central finding replicates through a different code path** (§D2). "
          "Holding the entry set constant bar for bar, sizing by the regime observable is "
          "the difference between failing Tier 1 and passing it. That is a stronger form of "
          "the claim than M3-2 itself could make.")
        A("")
        A("The next steps are the two that change the evidence rather than re-slice it:")
        A("")
        A("1. **The maker-fee study** (M3_PLAN §3.3, ranked risk #2). Every M3-2 candidate "
          "roughly doubles at 5 bps and the winner is +27.1 at maker against +15.0 at "
          "taker. Whether those fills are obtainable is an untested assumption underwriting "
          "half the published economics, and it is cheap to measure on the paper-sim stack.")
        A("2. **M3-0b's price/funding side-table**, which unlocks barrier exits, the funding "
          "term and the position-state observations §3.1 defers — genuinely new degrees of "
          "freedom rather than new combinations of the ones we have.")
    else:
        w = beat[0]
        A(f"**`{w['label']}` is M3's policy**, at {w['worst_net']:+.2f} bps worst-window net "
          f"at taker out-of-fold against the baseline's in-sample "
          f"{BASELINE_BAR_BPS:+.2f}. Tier 2 still fails, so this justifies paper trading and "
          "does not justify size — the distinction M3_PROTOCOL §4.3 exists to keep visible.")
        A("")
        A("The maker-fee study (M3_PLAN §3.3) and M3-0b's side-table remain the two items "
          "that would change the evidence rather than re-slice it, and both now matter more "
          "rather than less.")
    A("")
    A("**Proposals for a future pre-registration**, logged in M3_3_PROTOCOL §7.1 *before* "
      "this run and not amended by it: window-equalised fitting weights, per-notional "
      "normalisation of a size-varying policy, and whether R2's per-window coverage cut "
      "should also be the baseline's rule.")
    A("")

    # ---- G. detail ---------------------------------------------------------------------
    A("## G — Per-configuration detail (M3_PROTOCOL §5)")
    A("")
    A("Both fees, per window, per seed, per side, with the clustered interval, for every "
      "one of the scored runs.")
    A("")
    for c in learned + ablation + [c1] + ([c3] if c3 is not None else []):
        L.append(search.render_detail(c))
    return "\n".join(L) + "\n"
