"""Decision CA's seed count (2026-11-02): is the exchange's flag knowable at t0 or soon after? Read off the FROZEN episode lists'
own t0-known columns and the flag's stamp — no bar, no price, no fold read. Runs on the laptop in the ft2 image:

    docker run --rm -v "$PWD:/workspace/ft2" -w /workspace/ft2 fluxtrader2-analysis:latest \
        python scripts/ca_count.py ft2/fundep_f12.csv ft2/fundep_f34.csv ft2/fundep_f5.csv >> output/by_probe/counts.md
"""
import sys

import pandas as pd

L = pd.concat([pd.read_csv(p) for p in sys.argv[1:]], ignore_index=True)
for c in ("t0", "flag_t0"):
    L[c] = pd.to_datetime(L[c], utc=True)
L["ar"] = L["rate_t0"].abs()
L["pin"] = L["ar"] >= 0.95 * L["cap_rate"]  # the crossing settlement at or over the name's own prior extreme (fundfreq's CAP_FRAC)
L["fp"] = L["fold"].map(lambda f: "F1+F2" if f in ("F1", "F2") else ("F3+F4" if f in ("F3", "F4") else f))
fl = L["flagged_7d"].astype(bool)
L["after_h"] = -L["flag_lag_h"]  # hours AFTER t0 (fundep's lag is t0 − the shortening's stamp)

print("\n## Decision CA's seed count (2026-11-02; `scripts/ca_count.py` on the laptop, the frozen lists only; no bar, no price, no fold read)")
print(f"{len(L)} eligible episodes, {int(fl.sum())} flagged within ± 7 days (by fold pair "
      + ", ".join(f"{k} {v} of {n}" for (k, v), n in zip(L[fl].groupby("fp").size().items(), L.groupby("fp").size())) + ").")
print("\n### The flag's timing against the crossing (the shortening's settlement stamp, public at that second — DATA.md `fund_freq_events`)")
print("| fold pair | flagged | at or before t0 | within 1 h | within 4 h | within 8 h | within 24 h | later |")
print("|---|---|---|---|---|---|---|---|")
for fp, g in L[fl].groupby("fp"):
    a = g["after_h"]
    print(f"| {fp} | {len(g)} | {int((a <= 0).sum())} | {int((a <= 1).sum())} | {int((a <= 4).sum())} | {int((a <= 8).sum())} | {int((a <= 24).sum())} | {int((a > 24).sum())} |")
a = L.loc[fl, "after_h"]
print(f"| all | {len(a)} | {int((a <= 0).sum())} | {int((a <= 1).sum())} | {int((a <= 4).sum())} | {int((a <= 8).sum())} | {int((a <= 24).sum())} | {int((a > 24).sum())} |")
print(f"\nLag after t0, hours, q10 / q25 / q50 / q75 / q90: " + " / ".join(f"{x:.0f}" for x in a.quantile([.1, .25, .5, .75, .9])) + ".")
f12 = L[fl & L["fold"].isin(["F1", "F2"])]
print("F1+F2's flagged (the notice era): " + ", ".join(f"{r.symbol.replace('USDT', '')} {r.after_h:+.0f} h" for r in f12.itertuples()) + ".")
print("F5 per month: " + ", ".join(f"{m} {n}" for m, n in L[L["fold"] == "F5"].assign(m=L["t0"].dt.strftime("%Y-%m")).groupby("m").size().items()) + ".")

print("\n### What the list knows at t0, flagged against unflagged (medians; the pin = |rate_t0| ≥ 0.95 × the name's largest |rate| before t0)")
print("| column | flagged | unflagged |")
print("|---|---|---|")
for c, lab in (("ar", "|rate_t0|"), ("fund_1d", "|fund_1d|"), ("cap_share_7d", "cap_share_7d"), ("interval_h", "interval_h"),
               ("prior_episodes", "prior_episodes"), ("perp_age_days", "perp_age_days")):
    v = L[c].abs() if c == "fund_1d" else L[c]
    print(f"| {lab} | {v[fl].median():.4g} | {v[~fl].median():.4g} |")
for c, lab in (("pin", "pinned at t0, share"), ("member_at_t0", "member at t0, share")):
    print(f"| {lab} | {L.loc[fl, c].astype(bool).mean():.2f} | {L.loc[~fl, c].astype(bool).mean():.2f} |")
print("\nThe pin as a t0 exclusion, by fold pair (flagged & pinned / flagged & unpinned / unflagged & pinned / unflagged & unpinned):")
for fp, g in L.groupby("fp"):
    f = g["flagged_7d"].astype(bool)
    p = g["pin"].astype(bool)
    print(f"- {fp}: n {len(g)} — {int((f & p).sum())} / {int((f & ~p).sum())} / {int((~f & p).sum())} / {int((~f & ~p).sum())}")
print("A |rate_t0| cut as the exclusion (kept = below the cut; flagged kept of flagged):")
for cut in (0.005, 0.01, 0.02):
    print(f"- < {cut * 100:g} %: " + "; ".join(
        f"{fp} {int((g['ar'] < cut).sum())} of {len(g)} kept, {int((g['flagged_7d'].astype(bool) & (g['ar'] < cut)).sum())} of {int(g['flagged_7d'].astype(bool).sum())} flagged"
        for fp, g in L.groupby("fp")))
print("\nThe interval at t0 × flagged: " + "; ".join(f"{int(h)}h {int(r.get(False, 0))} / {int(r.get(True, 0))}" for h, r in pd.crosstab(L["interval_h"], fl).iterrows()) + ".")
