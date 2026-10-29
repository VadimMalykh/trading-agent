"""X21 (NEXT_TRAINING_PLAN §2 X21) — `models.multi_horizon.column_dropout`: p = 0 is the
identity; shape preserved; a dropped column is zero on every bar of that sample and only
there; kept values unchanged (no rescale); the drop rate within 0.01 of p; masks differ
between samples; a pinned generator reproduces the mask; the model's eval() forward is
untouched by the knob — on made-up tensors, before any run.

Run inside the trainer image (nothing on the host):
    docker compose --profile ml run --rm --no-deps ml_trainer python tests/test_col_dropout.py
"""
from __future__ import annotations

import os
import sys

import torch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.multi_horizon import SharedEncoderMultiHead, column_dropout  # noqa: E402


def _x(b=64, t=12, f=19, seed=0):
    g = torch.Generator().manual_seed(seed)
    # strictly non-zero so a zero can only come from the mask
    return torch.randn((b, t, f), generator=g).abs() + 0.5


def test_p_zero_is_identity_and_same_object():
    x = _x()
    assert column_dropout(x, 0.0) is x
    assert column_dropout(x, -1.0) is x


def test_shape_and_whole_column_zeroing_no_rescale():
    x = _x(b=256, t=16, f=23)
    g = torch.Generator().manual_seed(1)
    y = column_dropout(x, 0.15, generator=g)
    assert y.shape == x.shape and y.dtype == x.dtype
    zero = (y == 0)
    # a column is either zero on EVERY bar of a sample or on none of them
    per_col = zero.all(dim=1)  # [B, F]
    any_col = zero.any(dim=1)
    assert torch.equal(per_col, any_col)
    # kept entries are unchanged — no inverted-dropout scaling
    kept = ~zero
    assert torch.equal(y[kept], x[kept])
    # some columns dropped, not all
    assert 0 < per_col.sum().item() < per_col.numel()


def test_drop_rate_matches_p():
    x = _x(b=4096, t=4, f=19, seed=3)
    for p in (0.1, 0.15, 0.2):
        g = torch.Generator().manual_seed(7)
        y = column_dropout(x, p, generator=g)
        rate = (y == 0).all(dim=1).float().mean().item()
        assert abs(rate - p) < 0.01, (p, rate)


def test_masks_differ_between_samples_and_pin_to_generator():
    x = _x(b=32, t=8, f=19, seed=5)
    g1 = torch.Generator().manual_seed(11)
    g2 = torch.Generator().manual_seed(11)
    y1 = column_dropout(x, 0.15, generator=g1)
    y2 = column_dropout(x, 0.15, generator=g2)
    assert torch.equal(y1, y2)
    m = (y1 == 0).all(dim=1)  # [B, F]
    # per-sample masks: not every row identical
    assert not all(torch.equal(m[0], m[i]) for i in range(1, m.shape[0]))


def test_invalid_p_and_shape_refused():
    x = _x(b=2, t=3, f=4)
    for bad in (1.0, 1.5):
        try:
            column_dropout(x, bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"p={bad} accepted")
    try:
        column_dropout(torch.zeros(3, 4), 0.1)
    except ValueError:
        pass
    else:
        raise AssertionError("2-D input accepted")


def test_eval_forward_untouched_by_the_knob():
    # The knob lives in the training loop; the model has no dropout state to flip.
    torch.manual_seed(0)
    model = SharedEncoderMultiHead(input_size=19, hidden_size=16, num_layers=1,
                                   horizons_minutes=[60, 240], dropout=0.2)
    model.eval()
    x = _x(b=8, t=10, f=19, seed=9)
    with torch.no_grad():
        a = model.forward(x)
        b = model.forward(column_dropout(x, 0.0))
    for h in a:
        assert torch.equal(a[h], b[h])
    assert "col_dropout" not in {n for n, _ in model.named_modules()}


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"{len(fns)} green")
