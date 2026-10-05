"""Compare frozen evidence without computing new solutions or touching data."""

import json
from core.data import content_digest


def comparison_rows(records):
    """Keep all metadata, flag exact differences, and preserve selected order."""
    keys = list(dict.fromkeys(key for record in records for key in record["metadata"]))
    rows = []
    for key in keys:
        values = [record["metadata"].get(key) for record in records]
        different = len({json.dumps(value, sort_keys=True) for value in values}) > 1
        rows.append({"name": key, "values": values, "different": different})
    return rows


def experiment_metadata(spec, result):
    binding = spec.get("data", {})
    return {
        "Problem fingerprint": content_digest(spec),
        "Data fingerprint": binding.get("dataset_digest"),
        "Asset order": binding.get("symbols"),
        "Estimation": binding.get("estimation"),
        "Parameter fingerprint": content_digest(spec.get("parameters", [])),
        "Objective / criteria": spec.get("objective", spec.get("criteria")),
        "Constraints": spec.get("constraints"),
        "Solver": result.get("solver", result.get("settings", {}).get("solver")),
        "Seed": result.get("settings", {}).get("seed"),
        "Solver options": result.get("solver_options"),
        "Runtime": result.get("runtime"),
    }


def evaluation_metadata(prices, digest, window, variable, result):
    portfolio = result["portfolio"]
    settings = portfolio["settings"]
    metadata = {
        "Data fingerprint": digest,
        "Asset order": prices["symbols"],
        "Window": window,
        "Completed dates": [portfolio["dates"][0], portfolio["dates"][-1]],
        "Decision variable": variable,
    }
    for key, default in [
        ("mode", "fixed"),
        ("frequency", "hold"),
        ("lookback", None),
        ("estimator", None),
        ("cost_bps", None),
        ("borrow_rate", None),
        ("financing_rate", None),
        ("risk_free_rate", None),
        ("solver", None),
    ]:
        metadata[key] = settings.get(key, default)
    metadata["Rolling parameter bindings"] = {
        k: v
        for k, v in settings.items()
        if k.endswith("_parameter") or k == "scenario_variable"
    }
    metadata["Seed"] = (
        None  # Refits/returns are deterministic; frontier seeds belong to experiments.
    )
    metadata["Runtime"] = result.get("runtime")
    return metadata
