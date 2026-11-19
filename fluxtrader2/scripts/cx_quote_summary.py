import gzip, sys, statistics as st, collections
sp = collections.defaultdict(list); tq = collections.defaultdict(list)
with gzip.open(sys.argv[1], "rt") as f:
    next(f)
    for ln in f:
        p = ln.rstrip().split(",")
        try:
            b, bq, a, aq = float(p[2]), float(p[3]), float(p[4]), float(p[5])
        except Exception:
            continue
        if b <= 0 or a <= 0 or a < b: continue
        m = (a + b) / 2
        sp[p[1]].append((a - b) / m * 1e4); tq[p[1]].append((b * bq + a * aq) / 2)
print("symbol,n,spread_p50,spread_mean,touch_usd_p50,touch_usd_p10")
for s in sorted(sp):
    v = sorted(tq[s])
    print(f"{s},{len(sp[s])},{st.median(sp[s]):.3f},{st.fmean(sp[s]):.3f},{st.median(v):.0f},{v[len(v)//10]:.0f}")
