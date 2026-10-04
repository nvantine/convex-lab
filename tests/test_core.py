import ast
from copy import deepcopy
from pathlib import Path

import cvxpy as cp
import numpy as np
import pytest

from core.parser import Limits, ProblemError, build_problem
from core.presets import PRESETS, get_preset
from core.solve import solve


def scalar(expression="square(x)", constraints=None, sense="minimize"):
    return {"version": 1, "variables": [{"name": "x", "shape": []}], "parameters": [],
            "objective": {"sense": sense, "expression": expression}, "constraints": constraints or []}


@pytest.mark.parametrize("key", PRESETS)
def test_every_preset_is_dcp_and_solves(key):
    result = solve(build_problem(get_preset(key)))
    assert result["status"] == "optimal"
    assert result["verified_optimal"]


@pytest.mark.parametrize("solver", ["CLARABEL", "OSQP", "SCS"])
def test_min_variance_closed_form(solver):
    # Diagonal variances a=.01,b=.04: w1=b/(a+b)=.8, w2=.2.
    result = solve(build_problem(get_preset("min-variance")), solver)
    np.testing.assert_allclose(result["variables"]["w"], [.8, .2], atol=2e-5)
    assert result["optimal_value"] == pytest.approx(.008, abs=1e-7)


def test_cap_and_dual_sensitivity():
    spec = get_preset("min-variance")
    spec["constraints"].append("w[0] <= 0.6")
    result = solve(build_problem(spec))
    np.testing.assert_allclose(result["variables"]["w"], [.6, .4], atol=1e-5)
    # Relaxing the cap lowers minimized variance by approximately dual*epsilon.
    changed = deepcopy(spec)
    changed["constraints"][-1] = "w[0] <= 0.6001"
    second = solve(build_problem(changed))
    assert (result["optimal_value"] - second["optimal_value"]) / .0001 == pytest.approx(result["constraints"][-1]["dual"], rel=.003)


def test_least_squares_known_answer():
    spec = get_preset("least-squares")
    a, b = [np.asarray(p["value"]) for p in spec["parameters"]]
    expected = np.linalg.lstsq(a, b, rcond=None)[0]
    np.testing.assert_allclose(solve(build_problem(spec))["variables"]["x"], expected, atol=1e-6)


def test_lp_and_socp_known_answers():
    np.testing.assert_allclose(solve(build_problem(get_preset("linear-program")))["variables"]["x"], [0, 1], atol=1e-6)
    assert solve(build_problem(get_preset("socp")))["variables"]["t"] == pytest.approx(5, abs=1e-6)


@pytest.mark.parametrize("expression", ["__import__('os')", "x.value", "x.__class__", "[x for x in [1]]", "(lambda: 1)()", "sum(*[x])", "sum(x, **{})", "open('file')", "x ** 1000000"])
def test_reject_python_execution_and_unknown_operators(expression):
    with pytest.raises(ProblemError):
        build_problem(scalar(expression))


@pytest.mark.parametrize("expression", ["square(", "unknown + x", "x[999]", "norm(x, 3)", "sum(x, axis=8)", "x / 0"])
def test_bad_syntax_names_index_and_atoms(expression):
    with pytest.raises(ProblemError):
        build_problem(scalar(expression))


@pytest.mark.parametrize("shape", [0, [-1], [0], [True], [1.5], [1, 1, 1], "2"])
def test_invalid_variable_shape(shape):
    spec = scalar()
    spec["variables"][0]["shape"] = shape
    with pytest.raises(ProblemError):
        build_problem(spec)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "12", True, [[1], [1, 2]], []])
def test_invalid_parameter_values(value):
    spec = scalar()
    spec["parameters"] = [{"name": "p", "value": value}]
    with pytest.raises(ProblemError):
        build_problem(spec)


def test_indefinite_covariance_not_silently_repaired():
    spec = get_preset("min-variance")
    spec["parameters"][0]["value"] = [[1, 0], [0, -1]]
    with pytest.raises(ProblemError, match="domain mismatch"):
        build_problem(spec)


def test_shapes_and_workload_limits():
    spec = get_preset("min-variance")
    spec["variables"][0]["shape"] = [3]
    with pytest.raises(ProblemError):
        build_problem(spec)
    with pytest.raises(ProblemError, match="entry limit"):
        build_problem(get_preset("min-variance"), Limits(variable_entries=1))
    with pytest.raises(ProblemError, match="AST"):
        build_problem(scalar("x+x+x+x"), Limits(ast_nodes=3))
    with pytest.raises(ProblemError, match="scalar"):
        spec = get_preset("min-variance")
        spec["objective"]["expression"] = "w"
        build_problem(spec)


def test_dcp_explains_objective_and_constraint_rules():
    built = build_problem(scalar("x*x", ["square(x) >= 1"]))
    assert not built.problem.is_dcp()
    text = " ".join(d["rule"] for d in built.diagnostics)
    assert "Objective rule failed" in text
    assert "Constraint 1 failed" in text
    assert "not DCP" in text
    with pytest.raises(ProblemError, match="DCP"):
        solve(built)
    assert build_problem(scalar("square(x)")).problem.is_dcp()


def test_parameter_promotion_rechecks_convexity():
    spec = get_preset("mean-variance")
    p = spec["parameters"].pop()
    spec["variables"].append({"name": p["name"], "shape": [], "domain": "nonneg"})
    built = build_problem(spec)
    assert not built.problem.is_dcp()
    assert built.preview()["constraints"][0]["source"] == "risk_aversion: nonneg domain"


def test_infeasible_unbounded_and_solver_incompatible():
    result = solve(build_problem(scalar("x", ["x >= 1", "x <= 0"])))
    assert result["status"] == "infeasible"
    assert all(c["dual"] is None for c in result["constraints"])
    assert result["optimal_value"] is None
    assert result["variables"]["x"] is None
    result = solve(build_problem(scalar("x")))
    assert result["status"] == "unbounded"
    with pytest.raises(ProblemError, match="OSQP"):
        solve(build_problem(get_preset("socp")), "OSQP")
    with pytest.raises(ProblemError, match="installed"):
        solve(build_problem(scalar()), "ECOS")


def test_math_substitution_constraint_count_and_matrix_values():
    built = build_problem(get_preset("mean-variance"))
    preview = built.preview()
    assert "10" in preview["objective"]["latex"]
    assert "risk_aversion" not in preview["objective"]["latex"]
    assert r"\mathrm{Sigma}" in preview["objective"]["latex"]
    assert len(preview["constraints"]) == 2
    assert preview["declarations"][1]["value"] == [[.01, 0], [0, .04]]


def test_matrix_indexing_stacking_and_axis():
    spec = scalar("sum_squares(hstack([x, 2*x]))", ["x == 2"])
    assert solve(build_problem(spec))["optimal_value"] == pytest.approx(20)
    spec["parameters"] = [{"name": "A", "value": [[1, 2], [3, 4]]}]
    spec["objective"]["expression"] = "sum(sum(A, axis=0)) + A[0, 1] + square(x)"
    assert solve(build_problem(spec))["optimal_value"] == pytest.approx(16)


def test_psd_variable_domain_has_explicit_symmetry_and_duals():
    spec = scalar()
    spec["variables"] = [{"name": "X", "shape": [2, 2], "domain": "PSD"}]
    spec["objective"]["expression"] = "sum_squares(X)"
    spec["constraints"] = ["X[0, 0] >= 1"]
    result = solve(build_problem(spec))
    assert len(result["constraints"]) == 3
    # A boundary direction has quadratic, not linear, sensitivity.
    np.testing.assert_allclose(result["variables"]["X"], [[1, 0], [0, 0]], atol=1e-4)
    assert result["optimal_value"] == pytest.approx(1, abs=1e-7)


def test_pure_core_has_no_django_imports():
    for file in Path("core").glob("*.py"):
        for node in ast.walk(ast.parse(file.read_text())):
            if isinstance(node, ast.Import):
                assert all(not n.name.startswith("django") for n in node.names)
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("django")


def test_time_limit_result_not_claimed_optimal(monkeypatch):
    built = build_problem(scalar())
    def limited(**kwargs):
        built.problem._status = cp.USER_LIMIT
        built.problem._value = None
    monkeypatch.setattr(built.problem, "solve", limited)
    result = solve(built)
    assert not result["verified_optimal"]
    assert result["variables"]["x"] is None


def test_inaccurate_result_keeps_warning(monkeypatch):
    built = build_problem(scalar())
    def inaccurate(**kwargs):
        built.problem._status = cp.OPTIMAL_INACCURATE
        built.problem._value = 0
        built.variables["x"].value = 0
    monkeypatch.setattr(built.problem, "solve", inaccurate)
    result = solve(built)
    assert not result["verified_optimal"]
    assert result["status"] == "optimal_inaccurate"


@pytest.mark.parametrize("field,value", [("domain", []), ("name", ["x"]), ("meaning", 10), ("units", {}), ("shape", None)])
def test_malformed_declarations_are_friendly_errors(field, value):
    spec = scalar()
    spec["variables"][0][field] = value
    with pytest.raises(ProblemError):
        build_problem(spec)


@pytest.mark.parametrize("constraint", ["0 < x", "0 <= x <= 1", "x != 0", "x", "x == __import__('os')"])
def test_invalid_constraint_language(constraint):
    with pytest.raises(ProblemError):
        build_problem(scalar(constraints=[constraint]))


def test_free_sign_coefficient_explains_parameter_domain():
    spec = scalar("p * square(x)")
    spec["parameters"] = [{"name": "p", "value": 2, "domain": "free"}]
    assert not build_problem(spec).problem.is_dcp()
    spec["parameters"][0]["domain"] = "nonneg"
    assert build_problem(spec).problem.is_dcp()


def test_negative_scalar_substitution_keeps_parentheses():
    spec = scalar("x - p")
    spec["parameters"] = [{"name": "p", "value": -2}]
    built = build_problem(spec)
    assert r"\left(-2\right)" in built.preview()["objective"]["latex"]


def test_small_scalar_values_render_as_scientific_math_at_full_precision():
    spec = scalar("p * square(x)")
    spec["parameters"] = [{"name": "p", "value": 1.234567890123456e-8, "domain": "nonneg"}]
    latex = build_problem(spec).preview()["objective"]["latex"]
    assert r"1.234567890123456\times 10^{-8}" in latex
    assert "e-08" not in latex
