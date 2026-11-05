"""BOOK_WAVE2_PLAN §S1 — X23: the own-pair order-book state at the decision as a FILTER on the
policy's own 240m entries.

WHY THIS EXISTS. The B-wave tested book features at horizons that cannot clear costs and used
240m only as a negative control (BACKLOG, "the tradeable horizon has never been tested with
book features", 2026-09-01). X7 asked whether a MARKET-WIDE book observable is a better size
key; E1 asked whether the 1m book can time the entry; D1 asked about dynamics at <= 60m. None
asked the plain question this module asks: at the moment the served rule decides, does the
pair's OWN book — how tight its spread is, which way its top-20 volume leans, which way its
near depth leans, relative to the side about to be taken — separate the cov-0.02 entries into
a subset worth taking and one not?

THE SHAPE. A subset reading of the incumbent's own trades (R1/R3's form in forward.py): every
arm splits the SAME trades into IN and OUT by one scalar read at the decision instant, and the
contrast is IN − OUT in net bps per unit of notional, day-bootstrapped on UTC entry days —
exactly `forward.bootstrap_contrast`, so the explore and the forward confirmation are the same
statistic on two populations. No trade is added, moved or re-priced.

TWO STAGES, X7's design.
  * explore — the X8″ seeds' trades on the book era (NOT clean evidence: B1/B2/X7/E1/D1 read
    these bars). Chooses ONE arm by a mechanical rule; the gate can close the question, never
    establish it.
  * confirm — the chosen arm on the forward paper ledger's `policy` arm, read at the 200th
    closed policy trade of the fifth start (a second look at 400 if the first includes zero;
    two misses close it). The bars are untouched by any book-state reading. The deciding row
    is the served population (cov 0.02); the `explore_cov05` arm is described beside it.

THE DECISION INSTANT, fixed. The rule decides at a 5m bar's close. On the dumps `entry_ts` is
the bar's open, so the instant is entry_ts + 5 min and the scalar is the 5m book-era table's
row AT that instant (B0's as-of join: the last snapshot at or before it, zeroed and flagged
past the 5-minute cap — training's own alignment). On the ledger the export
(`scripts/gcp_forward_ledger.sh`, `book_at_bars_<date>.csv`) takes the last snapshot at or
before the scored bar's close under forward.py's bar-key convention (bar_ts + 5 min from the
2026-10-21 clock fix, bar_ts − 5 min before it), with the same 5-minute cap, and every trade's
snapshot is checked to precede the row's `inserted_at` — the known-at proof.

WHAT IT NEVER DOES. It changes nothing served. CONFIRMED licenses *writing* a served-change
registration for an entry filter; it is not one.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from . import bookentry, bookregime, forward, metrics

SECTION = "BOOK_WAVE2_PLAN §S1"
COVERAGE = 0.05                    # explore PRIMARY (the trade count decides, as X7 / E1)
COVERAGE_INFO = 0.02               # the served cut: information in the explore, DECIDING forward
SERVED_SEED = bookentry.SERVED_SEED
COST = metrics.TAKER_COST_BPS
DECISION_NS = 5 * 60 * 1_000_000_000   # the dump's entry_ts is the 5m bar's open; the decision is its close
BOOK_MAX_AGE_S = 300.0             # sidetable.BOOK_MAX_AGE (5 min) in seconds — training's cap
NO_BOOK_MAX = 0.10                 # trades with no usable book at the decision: the cap (X7/E1's fallback cap)
BOOTSTRAP_SEED = 20261105          # the registration date
READ_AT = 200                      # the first forward look, in closed policy trades of the fifth start
LOOKS = 2                          # 200 and 400; two misses close it
ARM_DECIDING, ARM_BESIDE = forward.ARM_POLICY, "explore_cov05"

# The arms — the list IS the registration. Three scalars, both orientations each. `spread_pct`
# is the within-pair percentile of the spread (bps of mid) over the window's own bars; the two
# imbalances are signed by the trade's side (+ = the book leans the trade's way). "with" is
# strictly > 0; zero and an unreadable near-depth count as "against" (B0 zero-fills).
ARMS = {
    "spread_lo": ("spread_pct", "lo"),        # IN = the tighter half of the pair's own spreads
    "spread_hi": ("spread_pct", "hi"),
    "imb_with": ("imb_signed", "with"),       # IN = top-20 volume leans the trade's way
    "imb_against": ("imb_signed", "against"),
    "near_with": ("near_signed", "with"),     # IN = the 5-level near depth leans the trade's way
    "near_against": ("near_signed", "against"),
}
SCALARS = ["spread_bps", "imbalance", "depth_near_imb"]


# --------------------------------------------------------------------------------------
# the keys
# --------------------------------------------------------------------------------------

def pair_percentile(t: pd.DataFrame, ref: pd.DataFrame, col: str = "spread_bps") -> np.ndarray:
    """Each trade's `col` as a percentile of ITS pair's reference bars (right-continuous: the
    share of reference values <= the trade's). NaN for a pair with no reference bars."""
    out = np.full(len(t), np.nan)
    pairs = t["pair"].to_numpy()
    for p, g in ref.groupby("pair", observed=True):
        s = np.sort(g[col].to_numpy(np.float64))
        m = pairs == p
        if m.any() and s.size:
            out[m] = np.searchsorted(s, t.loc[m, col].to_numpy(np.float64), side="right") / s.size
    return out


def with_keys(t: pd.DataFrame, ref: pd.DataFrame) -> pd.DataFrame:
    """Add the three keys to trades that carry the decision-instant scalars and a `side`."""
    t = t.copy()
    side = t["side"].to_numpy(np.float64)
    t["imb_signed"] = side * t["imbalance"].fillna(0.0).to_numpy(np.float64)
    t["near_signed"] = side * t["depth_near_imb"].fillna(0.0).to_numpy(np.float64)
    t["spread_pct"] = pair_percentile(t, ref)
    return t


def split(t: pd.DataFrame, arm: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(IN, OUT) for one arm. The two orientations of a key are complements, so for every key
    IN ∪ OUT is the whole booked population — the partition check below relies on it."""
    key, which = ARMS[arm]
    x = t[key].to_numpy(np.float64)
    if key == "spread_pct":
        m = (x <= 0.5) if which == "lo" else (x > 0.5)
    else:
        m = (x > 0) if which == "with" else ~(x > 0)
    return t[m], t[~m]


def check_partition(t: pd.DataFrame) -> tuple[bool, str]:
    """Harness check: every key's two arms partition the booked trades, and spread_pct ∈ [0, 1]."""
    n = len(t)
    probs = []
    for key in {k for k, _ in ARMS.values()}:
        arms = [a for a, (k, _) in ARMS.items() if k == key]
        a_in = split(t, arms[0])[0]
        b_in = split(t, arms[1])[0]
        if len(a_in) + len(b_in) != n:
            probs.append(f"{key}: {len(a_in)} + {len(b_in)} != {n}")
    pct = t["spread_pct"].to_numpy(np.float64)
    if n and (np.isnan(pct).any() or pct.min() < 0 or pct.max() > 1):
        probs.append("spread_pct outside [0, 1] or NaN")
    return not probs, ("the six arms partition the booked trades, spread_pct in [0, 1]"
                       if not probs else "; ".join(probs))


# --------------------------------------------------------------------------------------
# the statistic — forward.py's, on frames with its columns
# --------------------------------------------------------------------------------------

def frame(t: pd.DataFrame) -> pd.DataFrame:
    """Dump trades (signed_ret as a return, size, entry_ts in ns) → forward.py's columns:
    net_bps size-weighted at taker 14, per_notional, the UTC entry day."""
    f = t.copy()
    f["net_bps"] = f["size"] * (f["signed_ret"] * metrics.BPS - COST)
    f["per_notional"] = f["net_bps"] / f["size"]
    f["day"] = pd.to_datetime(f["entry_ts"], unit="ns", utc=True).dt.floor("D")
    return f


def contrast(a: pd.DataFrame, b: pd.DataFrame) -> dict:
    return forward.bootstrap_contrast(a, b, seed=BOOTSTRAP_SEED)


def arm_table(t: pd.DataFrame, seeds: tuple[str, ...] | None = None) -> pd.DataFrame:
    rows = []
    for arm in ARMS:
        a, b = split(t, arm)
        c = contrast(a, b)
        ca, cb = forward.clustered(a), forward.clustered(b)
        row = {"arm": arm, "n_in": len(a), "n_out": len(b),
               "in": ca["mean"], "out": cb["mean"], "in − out": c["diff"],
               "95% CI": f"[{c['lo']:+.2f}, {c['hi']:+.2f}]", "lo": c["lo"], "hi": c["hi"]}
        if seeds:
            per = {s: forward.per_notional(a[a["seed"] == s]) - forward.per_notional(b[b["seed"] == s])
                   for s in seeds}
            row.update(per)
            row["median seed"] = float(np.nanmedian(list(per.values())))
        rows.append(row)
    return pd.DataFrame(rows)


def verdict(table: pd.DataFrame) -> tuple[str, bool, pd.Series]:
    """The explore's choice rule and gate: the arm with the highest pooled IN − OUT; the gate
    passes iff its day-bootstrapped 95 % interval is clear of zero AND the median seed > 0."""
    best = table.sort_values("in − out", ascending=False).iloc[0]
    passed = bool(best["lo"] > 0) and bool(best["median seed"] > 0)
    return str(best["arm"]), passed, best


def _show(tab: pd.DataFrame) -> str:
    cols = [c for c in tab.columns if c not in ("lo", "hi")]
    return tab[cols].to_string(index=False, float_format=lambda v: f"{v:+.2f}")


# --------------------------------------------------------------------------------------
# explore — the book era, the X8″ seeds
# --------------------------------------------------------------------------------------

def load_book5() -> pd.DataFrame:
    path = os.path.join(bookregime.BOOK_DIR, "book_era_5m.parquet")
    if not os.path.exists(path):
        raise SystemExit(f"{path} missing — run `m3 bookera` (B0) first")
    b = pd.read_parquet(path, columns=["pair", "ts", "has_book"] + SCALARS)
    b["pair"] = b["pair"].astype(str)
    return b


def decision_scalars(trades: pd.DataFrame, book5: pd.DataFrame) -> pd.DataFrame:
    """Join each trade to the 5m book-era row at its decision instant (entry_ts + 5 min). The
    row's scalars are the as-of snapshot at or before that instant under the 5-min cap; a row
    without a book (has_book 0, or no row) leaves the trade unbooked."""
    b = book5[book5["has_book"] == 1][["pair", "ts"] + SCALARS].rename(columns={"ts": "dec_ts"})
    t = trades.copy()
    t["dec_ts"] = t["entry_ts"].to_numpy(np.int64) + DECISION_NS
    t = t.merge(b, on=["pair", "dec_ts"], how="left")
    t["has_book"] = t["spread_bps"].notna()
    return t


def reference_bars(pop_bars: pd.DataFrame, book5: pd.DataFrame) -> pd.DataFrame:
    """The window's own bars: the booked 5m rows at the decision instants of the population's
    bars, per pair — what the spread percentile is taken over."""
    k = pop_bars[["pair", "ts"]].drop_duplicates().copy()
    k["ts"] = k["ts"].to_numpy(np.int64) + DECISION_NS
    b = book5[book5["has_book"] == 1][["pair", "ts", "spread_bps"]]
    return k.merge(b, on=["pair", "ts"], how="inner")


def explore(spec_fields: dict) -> int:
    print("\n🔴 NOT CLEAN EVIDENCE: B1/B2/X7/E1/D1 already read these bars. This stage can close the")
    print("   question and choose ONE arm; only the forward confirmation can establish it.")
    book5 = load_book5()
    booked = book5[book5["has_book"] == 1][["pair", "ts"]]
    pairs = sorted(booked["pair"].unique())
    ds = bookentry.load_dumps(pairs)
    ds_pop, regimes = bookentry.population(ds, booked)
    for d in ds_pop:
        t = pd.to_datetime(d.df["ts"], unit="ns", utc=True)
        print(f"  {d.seed} ({d.run_id}): {d.df[['pair', 'ts']].drop_duplicates().shape[0]:,} bars x "
              f"{d.df['pair'].nunique()} pairs, {t.min():%Y-%m-%d %H:%M} .. {t.max():%Y-%m-%d %H:%M}")
    ref = reference_bars(ds_pop[0].df, book5)
    print(f"  reference bars for the spread percentile: {len(ref):,} booked decision instants, "
          f"per pair {ref.groupby('pair').size().min():,}..{ref.groupby('pair').size().max():,}")
    seeds = tuple(bookentry.RUNS)
    forecast = None
    for cov in (COVERAGE, COVERAGE_INFO):
        label = "PRIMARY" if cov == COVERAGE else "information only — the served cut, the forward deciding row"
        print("\n" + "=" * 100)
        print(f"COVERAGE {cov} — {label}")
        print("=" * 100)
        inc = bookentry.incumbent(ds_pop, regimes, spec_fields, cov)
        t = decision_scalars(inc, book5)
        n, nb = len(t), int(t["has_book"].sum())
        share = 1 - nb / n if n else 0.0
        ok1 = share <= NO_BOOK_MAX
        print(f"  harness check 1 (a book at the decision): {nb:,} of {n:,} trades booked, "
              f"{share:.1%} without (cap {NO_BOOK_MAX:.0%}) — {'PASS' if ok1 else 'FAIL'}")
        t = with_keys(frame(t[t["has_book"]]), ref)
        ok2, msg = check_partition(t)
        print(f"  harness check 2 (partition): {'PASS' if ok2 else 'FAIL'} — {msg}")
        if not (ok1 and ok2):
            print("  🔴 harness check failed; nothing below may be read.")
            return 3
        all_c = forward.clustered(t)
        print(f"  incumbent net/notional @14 {all_c['mean']:+.2f} [{all_c['lo']:+.2f}, {all_c['hi']:+.2f}] "
              f"on {all_c['clusters']} entry days; trades per seed {t.groupby('seed').size().to_dict()}")
        tab = arm_table(t, seeds)
        print(_show(tab))
        if cov == COVERAGE_INFO:
            # the forecast for the forward deciding row: the served seed's own interval at this
            # cut, scaled to the registered looks' trade counts
            s3 = t[t["seed"] == SERVED_SEED]
            if len(s3) > 1:
                hw = []
                for arm in ARMS:
                    a, b = split(s3, arm)
                    c = contrast(a, b)
                    if c["draws"]:
                        hw.append((c["hi"] - c["lo"]) / 2)
                if hw:
                    h = float(np.median(hw))
                    forecast = (len(s3), h, h * np.sqrt(len(s3) / READ_AT), h * np.sqrt(len(s3) / (2 * READ_AT)))
            continue
        arm, passed, best = verdict(tab)
        print("\n" + "=" * 100)
        print(f"THE VERDICT, under {SECTION} as written")
        print("=" * 100)
        print(f"  chosen by the rule (highest pooled IN − OUT among the six arms): {arm}  "
              f"{best['in − out']:+.2f} {best['95% CI']}; median seed {best['median seed']:+.2f}; "
              f"IN n={int(best['n_in'])} / OUT n={int(best['n_out'])}")
        print(f"  gate: (i) interval clear of zero (lo > 0) -> {bool(best['lo'] > 0)}; "
              f"(ii) median seed > 0 -> {bool(best['median seed'] > 0)}")
        verdict_line = (f"GATE PASSED — transcribe the table into {SECTION}; the forward confirmation reads "
                        f"arm {arm} on the ledger's policy arm at the {READ_AT}th closed policy trade") \
            if passed else (f"GATE NOT PASSED — {SECTION} closes on these bars; no other scalar, split, "
                            f"orientation or coverage")
        print(f"\n  ==> {verdict_line}")
    if forecast:
        n, h, h1, h2 = forecast
        print(f"\n  forecast for the forward deciding row (served seed at cov {COVERAGE_INFO}: median arm "
              f"half-width ±{h:.1f} on {n} trades): ±{h1:.0f} at {READ_AT} closed policy trades, "
              f"±{h2:.0f} at {2 * READ_AT}")
    return 0


# --------------------------------------------------------------------------------------
# confirm — the forward ledger, read at the 200th closed policy trade
# --------------------------------------------------------------------------------------

def load_book_at_bars(path: str) -> pd.DataFrame:
    """`book_at_bars_<date>.csv`: one row per (pair, bar_ts) of policy_bars with the last
    snapshot at or before the scored bar's close — its scalars, its timestamp and its age."""
    b = pd.read_csv(path)
    for c in ("bar_ts", "snap_ts"):
        b[c] = pd.to_datetime(b[c], utc=True, format="ISO8601")
    b["pair"] = b["pair"].astype(str)
    return b


def ledger_scalars(trades: pd.DataFrame, book: pd.DataFrame) -> pd.DataFrame:
    """Join closed ledger trades to the export at (pair, entry_ts = bar_ts). `has_book` iff the
    snapshot exists and is within the 5-minute cap at the decision instant."""
    cols = ["pair", "bar_ts", "snap_ts", "age_s"] + SCALARS
    t = trades.merge(book[cols].rename(columns={"bar_ts": "entry_ts"}), on=["pair", "entry_ts"], how="left")
    t["has_book"] = t["snap_ts"].notna() & (t["age_s"] >= 0) & (t["age_s"] <= BOOK_MAX_AGE_S)
    return t


def check_known_at(t: pd.DataFrame) -> tuple[bool, str]:
    """Every booked trade's snapshot precedes the row's `inserted_at` — the moment the engine
    wrote the trade, i.e. after the decision. A later snapshot would be lookahead."""
    ins = pd.to_datetime(t["inserted_at"], utc=True, format="ISO8601")
    booked = t["has_book"].to_numpy()
    late = (t["snap_ts"] > ins).to_numpy() & booked
    n = int(late.sum())
    return n == 0, (f"every booked trade's snapshot precedes its inserted_at (max lead "
                    f"{(ins - t['snap_ts'])[booked].min()})" if booked.any() and n == 0
                    else f"{n} booked trades have a snapshot AFTER inserted_at")


def confirm(ledger_path: str, book_path: str, config: str) -> int:
    if config not in ARMS:
        raise SystemExit(f"--config must be one of {list(ARMS)}, got {config!r}")
    led = forward.load(ledger_path)
    n_policy = len(led.arm(ARM_DECIDING))
    print(f"ledger {ledger_path}: rows {led.n_rows}, closed {len(led.closed)}, open {led.n_open}; "
          f"closed policy trades {n_policy}")
    if n_policy < READ_AT:
        print(f"\n🔴 refusing: {SECTION}'s first forward look is at {READ_AT} closed policy trades "
              f"({n_policy} now); no earlier look at the forward window is permitted.")
        return 2
    look = n_policy // READ_AT
    if look > LOOKS:
        print(f"\n⚠️  {n_policy} closed policy trades is beyond the registered looks ({READ_AT} and "
              f"{2 * READ_AT}); {SECTION} is closed after two misses — this run is descriptive only.")
    else:
        print(f"look #{look} of {LOOKS} ({READ_AT} / {2 * READ_AT} closed policy trades)")
    problems = forward.check(led)
    if problems:
        print("\nCONSISTENCY FAILED (forward.check) — nothing below may be read:")
        for x in problems:
            print(f"  - {x}")
        return 2
    print("consistency: ok (one checkpoint, served cut and ladder on every row)")
    book = load_book_at_bars(book_path)
    rc = 0
    for arm_name in (ARM_DECIDING, ARM_BESIDE):
        deciding = arm_name == ARM_DECIDING
        print("\n" + "=" * 100)
        print(f"ARM {arm_name} — {'DECIDING' if deciding else 'described beside, not deciding'}")
        print("=" * 100)
        tr = led.arm(arm_name)
        if tr.empty:
            print("  no closed trades")
            continue
        t = ledger_scalars(tr, book)
        n, nb = len(t), int(t["has_book"].sum())
        share = 1 - nb / n
        ok1 = share <= NO_BOOK_MAX
        print(f"  harness check 1 (a book at the decision): {nb} of {n} trades booked, {share:.1%} without "
              f"(cap {NO_BOOK_MAX:.0%}); snapshot age at the decision median "
              f"{t.loc[t['has_book'], 'age_s'].median():.1f} s — {'PASS' if ok1 else 'FAIL'}")
        ok2, msg = check_known_at(t)
        print(f"  harness check 2 (known-at): {'PASS' if ok2 else 'FAIL'} — {msg}")
        lo_ts, hi_ts = tr["entry_ts"].min(), tr["entry_ts"].max()
        ref = book[(book["age_s"] >= 0) & (book["age_s"] <= BOOK_MAX_AGE_S)
                   & (book["bar_ts"] >= lo_ts) & (book["bar_ts"] <= hi_ts)][["pair", "spread_bps"]]
        t = with_keys(t[t["has_book"]], ref)
        ok3, msg = check_partition(t)
        print(f"  harness check 3 (partition): {'PASS' if ok3 else 'FAIL'} — {msg}; reference bars "
              f"{len(ref):,} ({lo_ts:%Y-%m-%d} .. {hi_ts:%Y-%m-%d})")
        if not (ok1 and ok2 and ok3):
            print("  🔴 harness check failed; this arm's tables may not be read" +
                  (" — the look is VOID" if deciding else ""))
            if deciding:
                rc = 3
            continue
        all_c = forward.clustered(t)
        print(f"  arm net/notional {all_c['mean']:+.2f} [{all_c['lo']:+.2f}, {all_c['hi']:+.2f}] on "
              f"{all_c['clusters']} entry days, {len(t)} booked trades")
        tab = arm_table(t)
        print(_show(tab))
        row = tab[tab["arm"] == config].iloc[0]
        print(f"\n  the registered arm {config}: IN − OUT {row['in − out']:+.2f} {row['95% CI']}  "
              f"(IN n={int(row['n_in'])} {row['in']:+.2f}, OUT n={int(row['n_out'])} {row['out']:+.2f})")
        if deciding:
            if row["lo"] > 0:
                print(f"\n  ==> CONFIRMED — the interval is clear of zero on the served population; this "
                      f"licenses WRITING a served-change registration for the {config} entry filter "
                      f"(nothing served changes here).")
            else:
                print(f"\n  ==> NOT CONFIRMED at look #{min(look, LOOKS)} — "
                      + ("the question moves to the second look at 400." if look < LOOKS
                         else f"two misses: {SECTION} closes; own-pair book state at the decision is "
                              f"closed as a 240m entry filter."))
    return rc


# --------------------------------------------------------------------------------------
# the report
# --------------------------------------------------------------------------------------

def report(spec_fields: dict, stage: str, ledger: str | None = None, book: str | None = None,
           exploration_recorded: bool = False, config: str | None = None) -> int:
    print("=" * 100)
    print(f"{SECTION} — X23: OWN-PAIR BOOK STATE AT THE DECISION AS A FILTER ON THE POLICY'S ENTRIES "
          f"— stage {stage.upper()}")
    print("=" * 100)
    if stage == "confirm":
        if not exploration_recorded or not config:
            print(f"\n🔴 refusing: pass --exploration-recorded and --config <arm> transcribed from {SECTION}.")
            return 2
        if not ledger or not book:
            print("\n🔴 refusing: --ledger and --book (scripts/gcp_forward_ledger.sh's two exports) are required.")
            return 2
        return confirm(ledger, book, config)
    if stage != "explore":
        raise SystemExit(f"stage must be explore or confirm, got {stage!r}")
    return explore(spec_fields)
