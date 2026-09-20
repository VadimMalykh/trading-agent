"""Regression: no route to a prediction may serve a pair the checkpoint never trained on.

Found 2026-09-16 (BACKLOG rows 10/11): `/predict_all` applied the T5 ceiling, `/predict?symbol=`
did not, and the engine uses the latter — four pairs traded through `pair_oov_id`.

    docker compose exec ml_inference python tests/test_serve_universe.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import serve  # noqa: E402

EIGHT = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT",
         "WLDUSDT", "HYPEUSDT", "ZECUSDT", "1000PEPEUSDT"]


def main() -> None:
    serve._state["model"] = object()          # "loaded"; the refusal must fire before any use
    serve._state["meta"] = {"pairs": EIGHT}

    out = serve.predict_symbol("XRPUSDT")
    assert out["ok"] is False and out["error"].startswith("untrained_symbol"), out
    assert serve.predict_symbol("xrpusdt")["ok"] is False          # case-insensitive

    assert serve._untrained_refusal("BTCUSDT") is None
    assert serve._untrained_refusal("btcusdt") is None

    serve._state["meta"] = {}                 # pre-C12 checkpoint: no ceiling known
    assert serve._untrained_refusal("XRPUSDT") is None

    print("PASS test_serve_universe")


if __name__ == "__main__":
    main()
