"""The tail of cg_count.py's section (4), computed on the pulled `output/by_probe/cg_snapshot_proposals.csv` (the first run raised on its
last line after every CSV was written): the 7-day collapse per name, the large-vote subsets after it, the name-months, the end's hour."""
import pandas as pd
ORDER = ["pre", "F0", "F1", "F2", "F3", "F4", "F5", "post"]
byfold = lambda s: " ".join(f"{k} {int(v)}" for k, v in s.reindex(ORDER, fill_value=0).items())  # noqa: E731
P = pd.read_csv("output/by_probe/cg_snapshot_proposals.csv")
for c in ("created", "start", "end"):
    P[c] = pd.to_datetime(P[c], utc=True)
el = P[(P.perp_ge_30d == True) & (P.state == "closed")].sort_values("end")  # noqa: E712
print(f"closed, the perpetual ≥ 30 d at the end: {len(el)} on {el.symbol.nunique()} bases")
for thr in (0, 50, 200, 1000):
    g = el[el.votes >= thr].sort_values("end")
    keep, last = [], {}
    for r in g.itertuples():
        k = r.symbol not in last or (r.end - last[r.symbol]) >= pd.Timedelta(days=7)
        keep.append(k)
        if k:
            last[r.symbol] = r.end
    c = g[pd.Series(keep, index=g.index)]
    top = c.groupby("symbol").size().sort_values(ascending=False)
    print(f"votes ≥ {thr}: {len(g)} → one cell a name per 7 days: {len(c)} on {c.symbol.nunique()} bases — {byfold(c.groupby('fold').size())}; members at the end {int(c.member_at_end.sum())} "
          f"({byfold(c[c.member_at_end].groupby('fold').size())}); the top five names' share {top.head(5).sum() / len(c):.2f} ({', '.join(f'{k} {v}' for k, v in top.head(5).items())})")
c = el
print(f"name-months with ≥ 2 closed votes: {int((el.assign(m=el.end.dt.strftime('%Y-%m')).groupby(['symbol', 'm']).size() >= 2).sum())} of {el.assign(m=el.end.dt.strftime('%Y-%m')).groupby(['symbol', 'm']).ngroups}")
h = el.end.dt.hour.value_counts()
print("the end's hour (UTC), the top five: " + ", ".join(f"{k:02d}:00 {v}" for k, v in h.head(5).items()) + f"; on the hour exactly {int((el.end.dt.minute == 0).sum())} of {len(el)}; on a weekend {int((el.end.dt.weekday >= 5).sum())}")
print(f"created → end, days, q10 / q50 / q90: {el.lead_d.quantile(0.1):.1f} / {el.lead_d.quantile(0.5):.1f} / {el.lead_d.quantile(0.9):.1f}; start → end: {el.duration_d.quantile(0.1):.1f} / {el.duration_d.quantile(0.5):.1f} / {el.duration_d.quantile(0.9):.1f}")
big = el[el.votes >= 200]
print(f"≥ 200 votes by fold pair, bases: F1+F2 {big[big.fold.isin(['F1','F2'])].symbol.nunique()}, F3+F4 {big[big.fold.isin(['F3','F4'])].symbol.nunique()}, F5 {big[big.fold=='F5'].symbol.nunique()}; "
      f"F1+F2 per month min / median / max: {big[big.fold.isin(['F1','F2'])].assign(m=lambda d: d.end.dt.strftime('%Y-%m')).groupby('m').size().agg(['min','median','max']).tolist()}")
