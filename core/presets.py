"""Presets are ordinary specifications, not special solver implementations.

Portfolio quadratic examples: Boyd & Vandenberghe §4.4.1.
Least-squares regularization: §6.3. CVaR: Rockafellar & Uryasev (2000).
"""
from copy import deepcopy


def variable(name, shape, meaning, domain="free"):
    return {"name": name, "shape": shape, "meaning": meaning, "domain": domain, "units": ""}


def parameter(name, value, meaning, domain="free", units=""):
    return {"name": name, "value": value, "meaning": meaning, "domain": domain, "units": units}


def portfolio():
    return {"version": 1, "variables": [variable("w", [2], "Asset allocation fractions")],
            "parameters": [parameter("Sigma", [[0.01, 0], [0, 0.04]], "Daily return covariance", "PSD", "return squared"),
                           parameter("mu", [0.001, 0.002], "Expected daily returns", units="return / day")],
            "objective": {"sense": "minimize", "expression": "quad_form(w, Sigma)"},
            "constraints": ["sum(w) == 1", "w >= 0"]}


PRESETS = {}
PRESETS["min-variance"] = ("Minimum variance", portfolio())
s = portfolio()
s["parameters"].append(parameter("risk_aversion", 10, "Variance penalty", "nonneg"))
s["objective"] = {"sense": "maximize", "expression": "mu @ w - risk_aversion * quad_form(w, Sigma)"}
PRESETS["mean-variance"] = ("Mean–variance", s)
s = portfolio()
s["parameters"].append(parameter("risk_cap", 0.012, "Maximum daily variance", "nonneg"))
s["objective"] = {"sense": "maximize", "expression": "mu @ w"}
s["constraints"].append("quad_form(w, Sigma) <= risk_cap")
PRESETS["risk-cap"] = ("Maximum return with risk cap", s)
s = deepcopy(PRESETS["mean-variance"][1])
s["parameters"] += [parameter("gross_cap", 1.5, "Maximum gross exposure", "nonneg"),
                    parameter("short_cap", 0.2, "Maximum short fraction per asset", "nonneg")]
s["constraints"] = ["sum(w) == 1", "norm(w, 1) <= gross_cap", "w >= -short_cap"]
PRESETS["signed"] = ("Signed mean–variance", s)
PRESETS["least-squares"] = ("Least squares", {
    "version": 1, "variables": [variable("x", [2], "Regression coefficients")],
    "parameters": [parameter("A", [[1, 0], [0, 1], [1, 1]], "Design matrix"),
                   parameter("b", [1, 2, 2.5], "Observed responses")],
    "objective": {"sense": "minimize", "expression": "sum_squares(A @ x - b)"}, "constraints": []})
s = deepcopy(PRESETS["least-squares"][1])
s["parameters"].append(parameter("penalty", 0.5, "Regularization strength", "nonneg"))
s["objective"]["expression"] += " + penalty * sum_squares(x)"
PRESETS["regularized-ls"] = ("Regularized least squares", s)
PRESETS["linear-program"] = ("Linear program", {
    "version": 1, "variables": [variable("x", [2], "Activity levels")],
    "parameters": [parameter("c", [1, 2], "Profit per activity")],
    "objective": {"sense": "maximize", "expression": "c @ x"},
    "constraints": ["x >= 0", "sum(x) <= 1"]})
PRESETS["socp"] = ("Second-order cone problem", {
    "version": 1, "variables": [variable("x", [2], "Coordinates"), variable("t", [], "Epigraph value")],
    "parameters": [parameter("b", [3, 4], "Target coordinates")],
    "objective": {"sense": "minimize", "expression": "t"},
    "constraints": ["norm(x, 2) <= t", "x == b"]})
PRESETS["cvar"] = ("Scenario CVaR", {
    "version": 1, "variables": [variable("w", [2], "Allocation fractions"),
                                variable("t", [], "Loss threshold"), variable("u", [4], "Excess losses")],
    "parameters": [parameter("R", [[0.02, -0.01], [-0.03, 0.01], [0.01, 0.005], [-0.01, -0.02]], "Scenario returns"),
                   parameter("tail_multiplier", 5, "1 / (scenario count * (1 - alpha)); here alpha = 0.95", "nonneg")],
    "objective": {"sense": "minimize", "expression": "t + tail_multiplier * sum(u)"},
    "constraints": ["sum(w) == 1", "w >= 0", "u >= 0", "u >= -R @ w - t"]})


def get_preset(name):
    return deepcopy(PRESETS[name][1])
