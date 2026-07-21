# M2 Implementation Plan

**Multi-horizon supervised signals + confidence gating** (no RL).

See [PLAN.md](./PLAN.md), [MODEL.md](../MODEL.md).

**Status:** Implemented  
**Keys / GPU:** Not required (public data + CPU Docker)

---

## Goals

1. Shared LSTM encoder + heads for **1m, 15m, 1h**
2. Joint supervised training (direction: down/flat/up per head)
3. **Confidence gating** (skip when max softmax < threshold)
4. Eval: per-horizon accuracy + gate sweep (coverage vs conditional accuracy)
5. Checkpoint: `/models/m2_multi.pt`

**Out of scope:** RL policy (M3), live inference service (Phase I), positional heads (M4).

---

## Commands

```bash
docker compose up -d postgres app

docker compose --profile ml run --rm ml_trainer \
  python train_m2.py --device cpu --epochs 8

docker compose --profile ml run --rm ml_trainer \
  python eval_m2.py --checkpoint /models/m2_multi.pt --gate 0.5,0.6,0.7
```

---

## Success criteria

- [x] Multi-head model trains end-to-end
- [x] Per-horizon val metrics printed
- [x] Gate sweep shows fewer trades at higher thresholds
- [x] Checkpoint written

---

*Updated: 2026-07-19*
