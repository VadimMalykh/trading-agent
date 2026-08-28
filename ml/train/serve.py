#!/usr/bin/env python3
"""
M2 inference HTTP server (Phase I light).
Loads /models/m2_multi.pt, builds features from Postgres, returns gated signals.

  GET /health
  GET /predict?symbol=BTCUSDT
  GET /predict_all
"""

from __future__ import annotations

import gc
import json
import os
import sys
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import (
    CANDLE_INTERVAL,
    FEATURE_DIM,
    GATE_THRESHOLD as CFG_GATE,
    HORIZONS_MINUTES,
    MODEL_DIR,
    NORM_DEGENERATE_MODE,
    PAIRS,
    PRIMARY_HORIZON,
    SEQ_LEN,
)
from data.db import load_whitelist_pairs
from data.dataset import (
    apply_feature_norm,
    clip_norm,
    finalize_train_std,
    sanitize_norm_stats,
    zero_degenerate,
)
from data.features import (
    ALL_FEATURE_COLS,
    FEATURE_COLS,
    MARKET_CONTEXT_COLS,
    apply_market_context,
    build_feature_frame,
    build_market_inputs,
    market_context_inputs,
)
from gate import directional_signal
from models.multi_horizon import SharedEncoderMultiHead

MODEL_PATH = os.environ.get("MODEL_PATH", f"{MODEL_DIR}/m2_multi.pt")
# An explicit GATE_THRESHOLD in the environment is an operator OVERRIDE and wins
# over the checkpoint. Unset (the normal case) means "use whatever this checkpoint
# was measured at" — see _resolve_gate.
# `.strip() or None` matters: compose passes GATE_THRESHOLD through as an EMPTY
# string when ML_GATE_THRESHOLD is unset, and "" must mean "no override".
GATE_ENV_OVERRIDE = (os.environ.get("GATE_THRESHOLD") or "").strip() or None
GATE_THRESHOLD = float(GATE_ENV_OVERRIDE if GATE_ENV_OVERRIDE else CFG_GATE)
HOST = os.environ.get("INFER_HOST", "0.0.0.0")
PORT = int(os.environ.get("INFER_PORT", "8001"))
PRIMARY = str(int(os.environ.get("PRIMARY_HORIZON", str(PRIMARY_HORIZON))))
# How long the cross-pair market inputs stay cached. One round of predictions
# over the whole universe must not reload every pair once per symbol. Short
# enough that a new bar is picked up promptly at any supported bar size.
MARKET_CACHE_TTL_S = float(os.environ.get("MARKET_CACHE_TTL_S", "30"))

_state = {
    "model": None,
    "meta": {},
    "horizons": HORIZONS_MINUTES,
    "error": None,
    "gate": GATE_THRESHOLD,
    "gate_source": "env" if GATE_ENV_OVERRIDE else "config",
    "gate_target_coverage": None,
}


def _resolve_gate(meta: dict) -> None:
    """Adopt the checkpoint's own operating point (C13).

    The gate used to be a single global constant. It cannot be: `conf` is a softmax
    output whose scale is a property of the trained model, so the same threshold is
    a different strategy on every checkpoint. Three seeds of one configuration gate
    1.2% / 2.5% / 1.7% of bars at conf >= 0.62, and a 1m model gated 80% at the
    served 0.58 — so promoting a new checkpoint silently moved the operating point
    every single time.

    eval_m2.py now measures, for a chosen COVERAGE, the threshold that realizes it
    on the val window and stores both in meta["served_gate"]. Serving reads that.
    Precedence: explicit env override > checkpoint > config default. An override is
    logged loudly, because using one means deliberately ignoring what was measured.
    """
    global GATE_THRESHOLD
    sg = meta.get("served_gate") or {}
    thr = sg.get("conf_threshold")
    if GATE_ENV_OVERRIDE:
        GATE_THRESHOLD = float(GATE_ENV_OVERRIDE)
        _state["gate_source"] = "env-override"
        if thr:
            print(
                f"  WARNING: GATE_THRESHOLD={GATE_THRESHOLD} from the environment "
                f"OVERRIDES this checkpoint's measured gate {float(thr):.4f} "
                f"(target coverage {sg.get('target_coverage')}). Unset it to serve "
                f"the operating point the model was actually evaluated at."
            )
    elif thr:
        GATE_THRESHOLD = float(thr)
        _state["gate_source"] = "checkpoint"
        _state["gate_target_coverage"] = sg.get("target_coverage")
        m = sg.get("measured") or {}
        print(
            f"  Gate from checkpoint: conf >= {GATE_THRESHOLD:.4f} "
            f"(top {float(sg.get('target_coverage', 0)) * 100:.3g}% of bars; measured "
            f"dir_acc={m.get('dir_acc')} on {m.get('n_trades', '?')} trades, "
            f"gross={m.get('gross_bps_per_trade')}bps/trade)"
        )
    else:
        GATE_THRESHOLD = float(CFG_GATE)
        _state["gate_source"] = "config-fallback"
        print(
            f"  WARNING: checkpoint carries no served_gate — falling back to the "
            f"config default {GATE_THRESHOLD}. That constant was tuned on a DIFFERENT "
            f"model's confidence scale, so the coverage it produces here is unknown. "
            f"Re-run eval_m2.py on this checkpoint to derive and store its own gate."
        )
    _state["gate"] = GATE_THRESHOLD


def load_model():
    path = Path(MODEL_PATH)
    if not path.exists():
        _state["error"] = f"model not found: {path}"
        print(_state["error"])
        return False

    device = torch.device("cpu")
    ckpt = torch.load(path, map_location=device, weights_only=False)
    meta = ckpt.get("meta", {})
    horizons = meta.get("horizons_minutes") or HORIZONS_MINUTES
    feature_dim = meta.get("feature_dim", FEATURE_DIM)
    hidden = meta.get("hidden_size", 64)
    num_layers = int(meta.get("num_layers", 2))  # pre-capacity ckpts had 2
    seq_len = meta.get("seq_len", SEQ_LEN)
    primary = str(meta.get("primary_horizon", PRIMARY))
    has_dir_head = bool(meta.get("directional_head", False))
    has_quantile_head = bool(meta.get("quantile_head", False))
    quantile_levels = meta.get("quantile_levels") or [0.1, 0.5, 0.9]
    pair_embed_dim = int(meta.get("pair_embed_dim", 0))
    pair_vocab = list(meta.get("pair_vocab") or [])

    model = SharedEncoderMultiHead(
        input_size=feature_dim,
        hidden_size=hidden,
        horizons_minutes=horizons,
        directional_head=has_dir_head,
        quantile_head=has_quantile_head,
        quantile_levels=quantile_levels,
        num_layers=num_layers,
        n_pairs=len(pair_vocab) if pair_embed_dim > 0 else 0,
        pair_embed_dim=pair_embed_dim,
    )
    model.load_state_dict(ckpt["model_state"])
    model.eval()
    _resolve_gate(meta)
    _state["has_dir_head"] = has_dir_head
    _state["has_quantile_head"] = has_quantile_head
    _state["quantile_levels"] = quantile_levels
    # symbol -> trained embedding row; unknown symbols use the OOV bucket.
    _state["pair_embed_dim"] = pair_embed_dim
    _state["pair_to_id"] = {p: i for i, p in enumerate(pair_vocab)}
    _state["pair_oov_id"] = len(pair_vocab)

    # P0 FIX 2026-08-17: repair the broken std=1e-6 that every checkpoint written
    # before this date has baked into meta.norm_stats for features that were constant
    # in its train window (order book / trades / OI, whose collection started long
    # after those train windows end). Live bars DO have that data, so serving with
    # the raw stats multiplied 13 of 19 input channels by ~1e6 (trade_count reached
    # ~1e8), saturating the encoder into emitting a near-constant. Sanitizing here
    # makes those channels pass through unscaled instead. See config.py NORM_* and
    # docs/NEXT_TRAINING_PLAN.md.
    raw_norm = meta.get("norm_stats") or {}
    norm_stats = sanitize_norm_stats(raw_norm, f"serve ckpt {path}") if raw_norm else {}
    # Worst pair, NOT the sum across pairs — summing 12 dead columns over 9 pairs
    # reads as "109 broken features" out of 19, which is nonsense.
    n_degen = max(
        (len(st.get("degenerate_cols", [])) for st in norm_stats.values()
         if isinstance(st, dict)),
        default=0,
    )
    # --- the checkpoint's OWN feature columns (C12) -------------------------------
    # FEATURE_COLS grows; a checkpoint must be served the columns it was trained on.
    # Pre-C12 checkpoints record no list, and for those the frozen legacy prefix IS
    # what they saw. Getting this wrong is silent: the tensor would still have the
    # right shape for a 29-column model while every column after the insert point
    # held a different feature.
    feature_cols = list(meta.get("feature_cols") or [])
    if not feature_cols:
        feature_cols = list(ALL_FEATURE_COLS[:feature_dim])
        print(
            f"  NOTE: checkpoint records no feature_cols (pre-C12) — serving its "
            f"{feature_dim} columns from the frozen legacy list."
        )
    needs_market = all(c in feature_cols for c in MARKET_CONTEXT_COLS)
    print(
        f"  Feature columns: {len(feature_cols)}"
        + (" (incl. cross-pair market context)" if needs_market else "")
    )

    _state.update(
        {
            "model": model,
            "meta": meta,
            "horizons": horizons,
            "seq_len": seq_len,
            "primary": primary,
            "norm_stats": norm_stats,
            "norm_degenerate_cols": n_degen,
            "error": None,
            "device": device,
            "feature_cols": feature_cols,
            "needs_market": needs_market,
        }
    )
    print(
        f"Loaded {path} horizons={horizons} seq_len={seq_len} "
        f"primary={primary} norm={'ckpt' if _state['norm_stats'] else 'rolling-fallback'}"
    )
    if n_degen:
        print(
            f"  WARNING: up to {n_degen}/{len(feature_cols)} feature columns had NO variance in "
            "this checkpoint's train window (pre-2026-08-17 norm bug). They are now "
            f"neutralized at load ({NORM_DEGENERATE_MODE}) instead of being multiplied by "
            "~1e6, so serving is no longer degenerate — but the model never LEARNED from "
            "those channels, so its live predictions are effectively CANDLE-ONLY. "
            "Re-train + re-promote for a trustworthy microstructure signal."
        )
    return True


# --- the served universe ------------------------------------------------------
# Two different questions, both answered from the checkpoint's own pair list:
# which pairs may be PREDICTED (_servable_pairs, T5) and which pairs define the
# cross-section a prediction is ranked against (_market_universe, C12).


def _trained_pairs() -> list:
    """The pair list the served checkpoint was actually trained on, upper-cased.

    Empty for a pre-C12 checkpoint that records none — callers must treat that as "no
    ceiling known" rather than as "no pairs".
    """
    return [p.upper() for p in ((_state.get("meta") or {}).get("pairs") or [])]


# The set of pairs already reported as dropped, so the warning below is printed once per
# (checkpoint, whitelist) rather than on every /predict_all request.
_DROPPED_LOGGED: set = set()


def _servable_pairs() -> list:
    """The whitelist, intersected with the checkpoint's own training universe.

    WHY THIS EXISTS. `/predict_all` used to iterate the DB whitelist directly. The
    whitelist is operator state on a VM and lists 12 pairs; the served checkpoint
    (seed 2) was trained on 8, so ADA/AVAX/LINK/XRP resolved to `pair_oov_id` — an
    embedding row no pair ever trained — and the server emitted live signals for four
    instruments the model has never seen (NEXT_TRAINING_PLAN §2, T5).

    The whitelist stays the operator's control: it can only ever narrow the universe.
    The checkpoint's own pair list is a hard ceiling on top of it, so promoting a
    12-pair checkpoint starts serving all 12 with no further change here, and the
    guarantee lives in code rather than in the state of a database row.
    """
    whitelist = [p.upper() for p in load_whitelist_pairs(fallback=PAIRS)]
    trained = _trained_pairs()
    if not trained:
        return whitelist
    trained_set = set(trained)
    servable = [p for p in whitelist if p in trained_set]
    dropped = [p for p in whitelist if p not in trained_set]
    if dropped:
        key = (tuple(whitelist), tuple(trained))
        if key not in _DROPPED_LOGGED:
            _DROPPED_LOGGED.add(key)
            print(
                f"  WARNING [universe] whitelist pairs not in the checkpoint's training "
                f"universe, NOT served: {', '.join(dropped)} "
                f"(checkpoint trained on {len(trained)}: {', '.join(trained)})"
            )
    return servable


# --- cross-pair market context at serve time (C12) --------------------------------
# Training computes these columns across the whole universe in one pass. Serving
# predicts one symbol at a time, so the universe has to be loaded here too. The
# per-pair inputs are two columns wide and identical for every symbol in a round of
# predictions, so they are built once and cached: without the cache, predicting 8
# symbols would load the universe 8 times, i.e. 64 candle queries per round.
_MARKET_CACHE = {"ts": 0.0, "key": None, "inputs": None}


def _market_universe() -> list:
    """Pairs whose returns define the cross-section.

    The model's own training universe when the checkpoint records one — the
    cross-sectional rank of a pair is only comparable to training if it is taken
    against the same set of pairs. Falls back to the live whitelist.
    """
    trained = _trained_pairs()
    if trained:
        return trained
    return [p.upper() for p in load_whitelist_pairs(fallback=PAIRS)]


def _market_inputs(max_rows: int) -> dict:
    universe = _market_universe()
    key = (tuple(universe), int(max_rows), CANDLE_INTERVAL)
    now = time.time()
    cached = _MARKET_CACHE
    if (
        cached["inputs"] is not None
        and cached["key"] == key
        and now - cached["ts"] < MARKET_CACHE_TTL_S
    ):
        return cached["inputs"]

    inputs = {}
    for pair in universe:
        try:
            f = build_market_inputs(pair, CANDLE_INTERVAL, max_rows=max_rows)
            if not f.empty:
                inputs[pair] = f
        except Exception as exc:  # noqa: BLE001 - one bad pair must not kill serving
            print(f"  WARNING [market] {pair}: {exc}")
    _MARKET_CACHE.update({"ts": now, "key": key, "inputs": inputs})
    return inputs


def _fill_market_context(symbol: str, frame, max_rows: int):
    """Overwrite the zeroed market columns with real cross-pair values.

    On any failure the columns stay zero and `has_market` stays 0, which is exactly
    the "this context is missing" signal the model was trained to read — degrading to
    a candle-only prediction is correct, refusing to serve is not.
    """
    try:
        inputs = _market_inputs(max_rows)
        if symbol.upper() not in inputs:
            inputs = dict(inputs)
            inputs[symbol.upper()] = market_context_inputs(frame)
        ctx = apply_market_context(inputs, candle_interval=CANDLE_INTERVAL)
        block = ctx.get(symbol.upper())
        if block is None:
            return frame
        aligned = block.reindex(frame.index)
        for c in MARKET_CONTEXT_COLS:
            if c in frame.columns:
                frame[c] = aligned[c].fillna(0.0).to_numpy()
    except Exception as exc:  # noqa: BLE001
        print(f"  WARNING [market] context unavailable for {symbol}: {exc}")
    return frame


def build_tensor(symbol: str):
    seq_len = _state.get("seq_len", SEQ_LEN)
    feature_cols = _state.get("feature_cols") or list(FEATURE_COLS)
    # Only the last ~max_rows candles are needed: seq_len for the model input
    # plus a buffer for rolling/std computations.
    max_rows = seq_len * 5
    frame = build_feature_frame(
        symbol, CANDLE_INTERVAL, max_rows=max_rows, feature_cols=feature_cols
    )
    if frame.empty or len(frame) < seq_len:
        return None, f"not enough feature rows for {symbol} (have {len(frame)}, need {seq_len})"

    if _state.get("needs_market"):
        frame = _fill_market_context(symbol, frame, max_rows)

    feats = frame.drop(columns=["close"]).values.astype(np.float32)
    norm_stats = _state.get("norm_stats") or {}
    if norm_stats:
        # Match training: per-pair (or global) z-score from checkpoint
        X = feats[-seq_len:][None, ...]  # [1, T, F]
        pair_ids = np.array([symbol.upper()], dtype=object)
        X = apply_feature_norm(X, pair_ids, norm_stats)
        x = X[0]
    else:
        # Legacy checkpoints without norm_stats. Same degenerate-column guard as the
        # training path: a feature that is constant across the rolling window (e.g. a
        # source that is currently down, so its column is all zeros) must not be
        # divided by ~0.
        window = feats[-max(seq_len * 3, 64) :]
        mean = window.mean(axis=0, keepdims=True)
        std_row, degen = finalize_train_std(window.std(axis=0), "serve rolling-fallback")
        feats = (feats - mean) / std_row.reshape(1, -1)
        feats = clip_norm(zero_degenerate(feats, degen))
        x = feats[-seq_len:]

    close = float(frame["close"].iloc[-1])
    t = torch.from_numpy(x.astype(np.float32)).unsqueeze(0)  # [1,T,F]
    return (t, close), None


@torch.no_grad()
def predict_symbol(symbol: str) -> dict:
    if _state["model"] is None:
        return {"ok": False, "error": _state.get("error") or "model not loaded"}

    packed, err = build_tensor(symbol)
    if err:
        return {"ok": False, "symbol": symbol, "error": err}

    x, price = packed
    model = _state["model"]
    has_dir = _state.get("has_dir_head", False)
    pair_idx = None
    if _state.get("pair_embed_dim", 0) > 0:
        pid = _state["pair_to_id"].get(symbol.upper(), _state["pair_oov_id"])
        pair_idx = torch.tensor([pid], dtype=torch.long)
    logits_map, dir_map, quant_map = model.forward_all(x, pair_idx)
    q_levels = _state.get("quantile_levels") or [0.1, 0.5, 0.9]
    horizons_out = {}
    primary = _state.get("primary") or PRIMARY
    if primary not in [str(h) for h in _state["horizons"]]:
        primary = str(_state["horizons"][0])

    for h, logits in logits_map.items():
        probs = torch.softmax(logits, dim=-1)[0].tolist()
        argmax = int(logits.argmax(dim=-1)[0].item())
        label = {0: "down", 1: "flat", 2: "up"}
        if has_dir and dir_map is not None:
            # Clean up/down signal from the auxiliary directional head.
            dprob = torch.softmax(dir_map[h], dim=-1)[0]
            p_up = float(dprob[1].item())
            p_down = float(dprob[0].item())
            side_i = 2 if p_up >= p_down else 0
            conf_f = max(p_up, p_down)
        else:
            side, conf = directional_signal(logits)
            side_i = int(side[0].item())
            conf_f = float(conf[0].item())
        horizons_out[h] = {
            "direction": label[side_i],
            "argmax_class": label[argmax],
            "confidence": round(conf_f, 4),
            "probs": {
                "down": round(probs[0], 4),
                "flat": round(probs[1], 4),
                "up": round(probs[2], 4),
            },
            "gated": conf_f >= GATE_THRESHOLD,
        }
        if quant_map is not None:
            # Forward-return quantiles (risk/vol context for the policy). Keyed by
            # level, e.g. {"p10": -0.004, "p50": 0.0, "p90": 0.005}.
            qvals = quant_map[h][0].tolist()
            horizons_out[h]["quantiles"] = {
                f"p{int(round(lv * 100))}": round(qv, 6)
                for lv, qv in zip(q_levels, qvals)
            }

    primary_h = horizons_out.get(primary, next(iter(horizons_out.values())))
    trade = primary_h["gated"] or any(v["gated"] for v in horizons_out.values())
    if trade and primary_h["direction"] == "up":
        side = "BUY"
    elif trade and primary_h["direction"] == "down":
        side = "SELL"
    else:
        side = "FLAT"
        trade = False

    gc.collect()
    return {
        "ok": True,
        "symbol": symbol,
        "price": price,
        "primary_horizon_m": int(primary),
        "gate_threshold": GATE_THRESHOLD,
        "gate_source": _state.get("gate_source"),
        "gate_target_coverage": _state.get("gate_target_coverage"),
        "trade": trade,
        "side": side,
        "confidence": primary_h["confidence"],
        "horizons": horizons_out,
        "model": os.path.basename(MODEL_PATH),
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))

    def _json(self, code: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)

            if path == "/health":
                return self._json(
                    200,
                    {
                        "ok": _state["model"] is not None,
                        "model_path": MODEL_PATH,
                        "error": _state.get("error"),
                        "gate_threshold": GATE_THRESHOLD,
                        # "checkpoint" is the healthy value: the model is served at
                        # the operating point it was measured at. "config-fallback"
                        # means the gate is a guess from another model's scale.
                        "gate_source": _state.get("gate_source"),
                        "gate_target_coverage": _state.get("gate_target_coverage"),
                        "horizons": _state.get("horizons"),
                        "primary": _state.get("primary"),
                        "norm": "ckpt" if _state.get("norm_stats") else "rolling-fallback",
                        # >0 means this checkpoint was trained with those feature
                        # columns constant (pre-2026-08-17 norm bug): they are now
                        # sanitized at load, but the model never learned from them.
                        "norm_degenerate_cols": _state.get("norm_degenerate_cols", 0),
                        # The universe, so an operator can see at a glance whether the
                        # whitelist is being narrowed by the checkpoint (T5). Empty
                        # "trained_pairs" means a pre-C12 checkpoint that records none,
                        # and then the whitelist is served unfiltered.
                        "trained_pairs": _trained_pairs(),
                        "served_pairs": _servable_pairs(),
                    },
                )

            if path == "/predict":
                symbol = (qs.get("symbol") or ["BTCUSDT"])[0].upper()
                return self._json(200, predict_symbol(symbol))

            if path == "/predict_all":
                # The checkpoint's training universe is a hard ceiling on the whitelist:
                # never emit a signal for a pair the model has never seen (T5).
                pairs = _servable_pairs()
                results = [predict_symbol(p) for p in pairs]
                return self._json(200, {"ok": True, "signals": results, "pairs": pairs})

            return self._json(404, {"ok": False, "error": "not found"})
        except Exception as e:
            traceback.print_exc()
            return self._json(500, {"ok": False, "error": str(e)})


def main():
    print(f"FluxTrader M2 inference on {HOST}:{PORT}")
    print(f"MODEL_PATH={MODEL_PATH} GATE={GATE_THRESHOLD} (pre-load default)")
    load_model()
    print(f"serving gate={GATE_THRESHOLD:.4f} source={_state.get('gate_source')}")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
