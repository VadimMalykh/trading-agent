"""Ad-hoc verification for C3 (magnitude-weighted directional loss).

Run inside the trainer container:
  docker compose --profile ml run --rm --no-deps ml_trainer python check_c3_dir_mag.py
"""
import os, sys, types
import numpy as np
import torch
import torch.nn as nn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import train_m2 as T

dev = torch.device("cpu")
torch.manual_seed(0); np.random.seed(0)

H = ["240"]
N, NP = 4000, 3

# ---- fake bundle: 3 pairs whose typical |move| differs 10x, like BTC vs PEPE ----
class Ser:
    def __init__(self, lab, ret): self.labels = {"240": lab}; self.returns = {"240": ret}
scale_per_pair = [0.002, 0.006, 0.020]
labels, rets, pair_i = [], [], []
for p in range(NP):
    y = np.random.choice([0, 1, 2], size=N, p=[0.25, 0.5, 0.25])
    r = np.random.laplace(0.0, scale_per_pair[p], size=N)
    labels.append(y); rets.append(r); pair_i.append(np.full(N, p, dtype=np.int32))
bundle = types.SimpleNamespace(
    series=[Ser(labels[p], rets[p]) for p in range(NP)],
    pair_i=np.concatenate(pair_i),
    t_i=np.concatenate([np.arange(N, dtype=np.int32) for _ in range(NP)]),
)
tr_idx = np.arange(NP * N)

dw = np.array([1.1, 0.9]); dw = dw / dw.mean()
dir_crits = {h: nn.CrossEntropyLoss(weight=torch.tensor(dw, dtype=torch.float32)) for h in H}
dir_class_w = {h: dw for h in H}

# ---- a batch ----
B = 512
sel = np.random.choice(tr_idx, B, replace=False)
pi = bundle.pair_i[sel]; ti = bundle.t_i[sel]
y3 = np.array([bundle.series[p].labels["240"][t] for p, t in zip(pi, ti)])
rr = np.array([bundle.series[p].returns["240"][t] for p, t in zip(pi, ti)])
yb = {"240": torch.tensor(y3), "ret_240": torch.tensor(rr, dtype=torch.float32)}
pair_idx = torch.tensor(pi.astype(np.int64))
logits = {"240": torch.randn(B, 2, requires_grad=True)}

fail = []
def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok: fail.append(name)

print("\n=== 1. OFF path is byte-identical to the pre-C3 loss ===")
ref = T.directional_loss(logits, yb, dir_crits, H)
off = T.directional_loss(logits, yb, dir_crits, H, mag=None, pair_idx=pair_idx)
check("mag=None reproduces the incumbent exactly", ref.item() == off.item(),
      f"{ref.item():.12f} vs {off.item():.12f}")

print("\n=== 2. weighted reduction reduces to the unweighted one when w==1 ===")
mag = T.DirMagWeighter(bundle, tr_idx, H, dir_class_w, dev)
saved = mag.weights
mag.weights = lambda h, ret, p: torch.ones_like(ret)
one = T.directional_loss(logits, yb, dir_crits, H, mag=mag, pair_idx=pair_idx)
mag.weights = saved
check("w==1 gives the same value as the class-weighted mean", abs(one.item() - ref.item()) < 1e-6,
      f"{one.item():.12f} vs {ref.item():.12f}")

print("\n=== 3. normalization: per-pair means and E[w]==1 on train ===")
for p in range(NP):
    got = mag.pair_mean["240"][p].item()
    y, r = labels[p], np.abs(rets[p])
    want = r[y != 1].mean()
    check(f"pair {p} mean|r| = its own train mean ({want*1e4:.1f}bps)", abs(got - want) < 1e-9)
w_all = []
for p in range(NP):
    y, r = labels[p], rets[p]
    m = y != 1
    w_all.append(mag.weights("240", torch.tensor(r[m], dtype=torch.float32),
                             torch.full((int(m.sum()),), p, dtype=torch.long)).numpy())
w_all = np.concatenate(w_all)
check("E[w] == 1.0 over the train window", abs(w_all.mean() - 1.0) < 1e-5, f"mean={w_all.mean():.6f}")
check("w is capped at CLIP/scale", w_all.max() <= (mag.clip / mag.scale['240']) + 1e-6,
      f"max={w_all.max():.3f} cap={mag.clip/mag.scale['240']:.3f}")

print("\n=== 4. the weight is about move size, NOT pair identity ===")
means = [w_all[np.concatenate([np.full(int((labels[q] != 1).sum()), q) for q in range(NP)]) == p].mean()
         for p in range(NP)]
print("   per-pair mean weight:", ", ".join(f"pair{p}={m:.4f}" for p, m in enumerate(means)))
check("no pair is systematically up/down-weighted", max(means) - min(means) < 0.05,
      f"spread={max(means)-min(means):.4f} (10x raw |r| difference between pairs)")

print("\n=== 5. big moves actually get more weight ===")
r0 = np.abs(rets[0]); y0 = labels[0]; m0 = y0 != 1
wv = mag.weights("240", torch.tensor(rets[0][m0], dtype=torch.float32),
                 torch.zeros(int(m0.sum()), dtype=torch.long)).numpy()
rv = r0[m0]; q = np.quantile(rv, [0.2, 0.8])
lo, hi = wv[rv <= q[0]].mean(), wv[rv >= q[1]].mean()
check("top-quintile |r| outweighs bottom-quintile", hi > 3 * lo, f"lo={lo:.3f} hi={hi:.3f} ratio={hi/lo:.1f}x")

print("\n=== 6. gradients flow and differ from the unweighted loss ===")
logits["240"].grad = None
T.directional_loss(logits, yb, dir_crits, H, mag=mag, pair_idx=pair_idx).backward()
g_w = logits["240"].grad.clone()
logits["240"].grad = None
T.directional_loss(logits, yb, dir_crits, H).backward()
g_u = logits["240"].grad.clone()
check("weighted gradient is finite", bool(torch.isfinite(g_w).all()))
check("weighted gradient differs from unweighted", not torch.allclose(g_w, g_u))
check("gradient norms are the same order", 0.2 < (g_w.norm() / g_u.norm()).item() < 5.0,
      f"ratio={(g_w.norm()/g_u.norm()).item():.3f}")

print("\n=== 7. degenerate pair (all-zero returns) does not divide by ~0 ===")
b2 = types.SimpleNamespace(
    series=[Ser(labels[0], np.zeros(N)), Ser(labels[1], rets[1])],
    pair_i=np.concatenate([np.zeros(N, np.int32), np.ones(N, np.int32)]),
    t_i=np.concatenate([np.arange(N, dtype=np.int32)] * 2))
m2 = T.DirMagWeighter(b2, np.arange(2 * N), H, dir_class_w, dev)
w0 = m2.weights("240", torch.zeros(10), torch.zeros(10, dtype=torch.long))
check("all-zero pair yields finite, non-exploding weights",
      bool(torch.isfinite(w0).all()) and float(w0.max()) < 1e3, f"max={float(w0.max()):.3e}")

print("\n" + ("ALL CHECKS PASSED" if not fail else f"FAILURES: {fail}"))
sys.exit(1 if fail else 0)
