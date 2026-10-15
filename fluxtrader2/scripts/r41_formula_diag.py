"""R41 diagnostic, label-free: fund_due (the formula) against the settled rate per (name, S) on the members over F1+F2."""
import numpy as np, pandas as pd
from ft2.universe import screen_symbols
CL, I8 = 5.0, 1.0
names = screen_symbols()
a, b = pd.Timestamp("2023-05-01", tz="UTC"), pd.Timestamp("2024-09-01", tz="UTC")
pr = pd.read_parquet("data/premium.parquet"); pr["symbol"] = pr.symbol.astype(str); pr = pr[pr.symbol.isin(names)]
pr["t"] = pr.open_time + pd.Timedelta("5min"); pr["p"] = pr.premium * 1e4
fu = pd.read_parquet("data/funding_archive.parquet"); fu["symbol"] = fu.symbol.astype(str)
fu = fu[fu.symbol.isin(names) & (fu.ts >= a) & (fu.ts <= b)].sort_values(["symbol", "ts"])
rows = []
for sym, f in fu.groupby("symbol"):
    p = pr[pr.symbol == sym].sort_values("t")
    if p.empty: continue
    tt = p.t.values.astype("datetime64[ns]").astype(np.int64); pv = p.p.to_numpy()
    S = f.ts.values.astype("datetime64[ns]").astype(np.int64); iv = f.interval_h.to_numpy(float); rt = f.rate.to_numpy() * 1e4
    pid = np.searchsorted(S, tt, side="left")
    cs = pd.Series(pv).groupby(pid).cumsum().to_numpy(); cn = pd.Series(np.ones(len(pv))).groupby(pid).cumsum().to_numpy()
    for k in range(1, len(S)):
        per = (pid == k)
        if not per.any(): continue
        idx_all = np.flatnonzero(per)
        last = idx_all[-1]
        if tt[last] != S[k]: continue
        full = cs[last] / cn[last]
        before = tt <= S[k] - 3600 * 10**9
        j = idx_all[before[idx_all]]
        if len(j) == 0: continue
        part = cs[j[-1]] / cn[j[-1]]
        nbars = cn[last]; expect = (S[k] - S[k - 1]) / (300 * 10**9)
        rows.append((sym, pd.Timestamp(S[k]), iv[k], rt[k], full, part, nbars / expect))
d = pd.DataFrame(rows, columns=["symbol", "S", "iv", "rate", "P_full", "P_1h", "cover"])
d = d[d.cover >= 0.6]
for nm, I_of in (("I = 1 bp × iv/8", lambda iv: I8 * iv / 8), ("I = 1 bp always", lambda iv: np.full_like(iv, I8))):
    I = I_of(d.iv.to_numpy())
    for col in ("P_full", "P_1h"):
        fd = d[col] + np.clip(I - d[col], -CL, CL)
        err = (fd - d.rate)
        print(f"\n## {nm}, {col}: n={len(d)}  within 1bp: all {(err.abs()<=1).mean():.3f}  8h {(err.abs()<=1)[d.iv==8].mean():.3f}  4h {(err.abs()<=1)[d.iv==4].mean():.3f}   |err| median {err.abs().median():.3f} p90 {err.abs().quantile(.9):.2f}")
        inband = np.isclose(fd, I)
        print(f"   share in the dead band {inband.mean():.3f}; of those, settled rate == I exactly: {np.isclose(d.rate[inband], I[inband], atol=1e-6).mean():.3f}; by iv: 8h {np.isclose(d.rate[inband&(d.iv==8)], I[inband&(d.iv==8)], atol=1e-6).mean():.3f} 4h {np.isclose(d.rate[inband&(d.iv==4)], I[inband&(d.iv==4)], atol=1e-6).mean():.3f}")
        g = d.assign(fd=fd, inb=inband).groupby("S")
        rho_all, rho_out, nout, share_tied = [], [], [], []
        for s_, x in g:
            if len(x) < 10: continue
            rho_all.append(x.fd.rank().corr(x.rate.rank()))
            share_tied.append(x.inb.mean())
            y = x[~x.inb]
            nout.append(len(y))
            if len(y) >= 10: rho_out.append(y.fd.rank().corr(y.rate.rank()))
        print(f"   settlements {len(rho_all)}: Spearman all names median {np.nanmedian(rho_all):.3f} p10 {np.nanquantile(rho_all,.1):.3f}; names outside the band per S median {np.median(nout):.0f}; Spearman on them (≥10) n={len(rho_out)} median {np.nanmedian(rho_out):.3f} p10 {np.nanquantile(rho_out,.1):.3f}; share tied at I per S median {np.median(share_tied):.3f}")
print("\n## settled rate: share |rate| >= 75 bps", (d.rate.abs() >= 75).mean().round(4), "; >= 50", (d.rate.abs() >= 50).mean().round(4), "; rate exactly 1.0 bp", np.isclose(d.rate, 1.0).mean().round(3), "; exactly 0.5", np.isclose(d.rate, 0.5).mean().round(3))
print("## by hour of S: n and within-1bp (I=iv/8, P_1h)")
I = I8 * d.iv / 8; fd = d.P_1h + np.clip(I - d.P_1h, -CL, CL); e = (fd - d.rate).abs() <= 1
print(pd.DataFrame({"n": d.groupby(d.S.dt.hour).size(), "within": e.groupby(d.S.dt.hour).mean().round(3)}).T.to_string())
big = d[(fd - d.rate).abs() > 5].copy(); big["fd"] = fd[big.index]
print("## the 12 largest misses (P_1h formula vs settled)"); print(big.assign(err=(big.fd-big.rate)).sort_values("err", key=abs, ascending=False).head(12)[["symbol","S","iv","rate","P_full","P_1h","fd","err"]].round(2).to_string())
