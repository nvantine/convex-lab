"""Execute one trusted source revision in a child process, without Django.

Input/output files carry structured evidence; Python prints remain in logs.
This is process isolation for reliability, not a sandbox.
"""
from pathlib import Path
import importlib
import json
import sys
import traceback
import numpy as np
from core.data import price_frame, split_windows
from core.rolling import portfolio_path
from core.research import ResearchContext, result_payload, portfolio_report


def load_entry(bundle, entry_point):
    filename, function = entry_point.rsplit(":", 1)
    sys.path.insert(0, str(bundle))
    module = importlib.import_module(filename.removesuffix(".py").replace("/", "."))
    callback = getattr(module, function)
    if not callable(callback):
        raise ValueError("Registered entry point is not callable.")
    return callback


def execute(request):
    callback = load_entry(Path(request["bundle"]), request["entry_point"])
    artifact_dir = Path(request["artifacts"])
    payload = request.get("prices")
    params = request["params"]
    seed = request["seed"]
    if request["interface"] == "portfolio":
        chosen = portfolio_path(payload, [0.] * len(payload["symbols"]), request["window"],
            request["options"], strategy=lambda context, state: callback(context, params, state),
            artifact_dir=artifact_dir, seed=seed, windows=request["windows"],
            maximum_refits=request["maximum_refits"])
        benchmark = portfolio_path(payload, [1/len(payload["symbols"])] * len(payload["symbols"]),
            request["window"], {**request["options"], "mode":"fixed"}, stop_after=len(chosen["wealth"]),
            windows=request["windows"])
        result = portfolio_report({"portfolio":chosen, "equal_weight":benchmark})
        result["equations"] = list(dict.fromkeys(eq for refit in chosen["refits"]
            for eq in refit.get("diagnostics",{}).get("equations",[])))
        return result
    prices = price_frame(payload) if payload else None
    # Registration passes an already-redacted price payload. Keep original spans
    # supplied by the parent; recomputing 60/20/20 on a truncated series is wrong.
    train_end = request.get("train_end")
    context = ResearchContext(prices, prices.iloc[:train_end+1].copy() if prices is not None else None,
        tuple(payload["symbols"]) if payload else (), request["window"],
        np.random.default_rng(seed), artifact_dir)
    return result_payload(callback(context, params))


def main():
    target = Path(sys.argv[2])
    try:
        target.write_text(json.dumps({"ok":True, "result":execute(json.loads(Path(sys.argv[1]).read_text()))},
                                     allow_nan=False))
    except BaseException as error:
        traceback.print_exc()
        target.write_text(json.dumps({"ok":False, "error":f"{type(error).__name__}: {error}"}))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
