#!/usr/bin/env python3
"""
M2 inference HTTP server (Phase I light).
Loads /models/m2_multi.pt, builds features from Postgres, returns gated signals.

  GET /health
  GET /predict?symbol=BTCUSDT
  GET /predict_all
"""

from __future__ import annotations

import json
import os
import sys
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
    PAIRS,
    PRIMARY_HORIZON,
    SEQ_LEN,
)
from data.db import load_whitelist_pairs
from data.dataset import apply_feature_norm
from data.features import build_feature_frame
from gate import directional_signal
from models.multi_horizon import SharedEncoderMultiHead

MODEL_PATH = os.environ.get("MODEL_PATH", f"{MODEL_DIR}/m2_multi.pt")
GATE_THRESHOLD = float(os.environ.get("GATE_THRESHOLD", str(CFG_GATE)))
HOST = os.environ.get("INFER_HOST", "0.0.0.0")
PORT = int(os.environ.get("INFER_PORT", "8001"))
PRIMARY = str(int(os.environ.get("PRIMARY_HORIZON", str(PRIMARY_HORIZON))))

_state = {"model": None, "meta": {}, "horizons": HORIZONS_MINUTES, "error": None}


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
    seq_len = meta.get("seq_len", SEQ_LEN)
    primary = str(meta.get("primary_horizon", PRIMARY))

    model = SharedEncoderMultiHead(
        input_size=feature_dim,
        hidden_size=hidden,
        horizons_minutes=horizons,
    )
    model.load_state_dict(ckpt["model_state"])
    model.eval()

    _state.update(
        {
            "model": model,
            "meta": meta,
            "horizons": horizons,
            "seq_len": seq_len,
            "primary": primary,
            "norm_stats": meta.get("norm_stats") or {},
            "error": None,
            "device": device,
        }
    )
    print(
        f"Loaded {path} horizons={horizons} seq_len={seq_len} "
        f"primary={primary} norm={'ckpt' if _state['norm_stats'] else 'rolling-fallback'}"
    )
    return True


def build_tensor(symbol: str):
    seq_len = _state.get("seq_len", SEQ_LEN)
    frame = build_feature_frame(symbol, CANDLE_INTERVAL)
    if frame.empty or len(frame) < seq_len:
        return None, f"not enough feature rows for {symbol} (have {len(frame)}, need {seq_len})"

    feats = frame.drop(columns=["close"]).values.astype(np.float32)
    norm_stats = _state.get("norm_stats") or {}
    if norm_stats:
        # Match training: per-pair (or global) z-score from checkpoint
        X = feats[-seq_len:][None, ...]  # [1, T, F]
        pair_ids = np.array([symbol.upper()], dtype=object)
        X = apply_feature_norm(X, pair_ids, norm_stats)
        x = X[0]
    else:
        # Legacy checkpoints without norm_stats
        window = feats[-max(seq_len * 3, 64) :]
        mean = window.mean(axis=0, keepdims=True)
        std = window.std(axis=0, keepdims=True) + 1e-6
        feats = (feats - mean) / std
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
    logits_map = _state["model"](x)
    horizons_out = {}
    primary = _state.get("primary") or PRIMARY
    if primary not in [str(h) for h in _state["horizons"]]:
        primary = str(_state["horizons"][0])

    for h, logits in logits_map.items():
        probs = torch.softmax(logits, dim=-1)[0].tolist()
        side, conf = directional_signal(logits)
        side_i = int(side[0].item())
        conf_f = float(conf[0].item())
        argmax = int(logits.argmax(dim=-1)[0].item())
        label = {0: "down", 1: "flat", 2: "up"}
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

    primary_h = horizons_out.get(primary, next(iter(horizons_out.values())))
    trade = primary_h["gated"]
    if trade and primary_h["direction"] == "up":
        side = "BUY"
    elif trade and primary_h["direction"] == "down":
        side = "SELL"
    else:
        side = "FLAT"
        trade = False

    return {
        "ok": True,
        "symbol": symbol,
        "price": price,
        "primary_horizon_m": int(primary),
        "gate_threshold": GATE_THRESHOLD,
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
                        "horizons": _state.get("horizons"),
                        "primary": _state.get("primary"),
                        "norm": "ckpt" if _state.get("norm_stats") else "rolling-fallback",
                    },
                )

            if path == "/predict":
                symbol = (qs.get("symbol") or ["BTCUSDT"])[0].upper()
                return self._json(200, predict_symbol(symbol))

            if path == "/predict_all":
                pairs = load_whitelist_pairs(fallback=PAIRS)
                results = [predict_symbol(p) for p in pairs]
                return self._json(200, {"ok": True, "signals": results, "pairs": pairs})

            return self._json(404, {"ok": False, "error": "not found"})
        except Exception as e:
            traceback.print_exc()
            return self._json(500, {"ok": False, "error": str(e)})


def main():
    print(f"FluxTrader M2 inference on {HOST}:{PORT}")
    print(f"MODEL_PATH={MODEL_PATH} GATE={GATE_THRESHOLD}")
    load_model()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
