"""Shared web/CLI orchestration. Numerical code remains in core/.

Database writes occur after numerical work, in short transactions only.
"""
import hashlib
import json
from django.conf import settings
from core.parser import Limits, ProblemError, build_problem
from core.solve import accepted_solution, solve
from core.pareto import run_frontier
from core.data import content_digest, estimates_edited, problem_from_training
from core.rolling import evaluate_portfolios
from lab.models import Problem, Experiment, Evaluation


def limits():
    return Limits(variable_entries=settings.LAB_MAX_VARIABLE_ENTRIES,
                  parameter_entries=settings.LAB_MAX_PARAMETER_ENTRIES,
                  ast_nodes=settings.LAB_MAX_AST_NODES, criteria=settings.LAB_MAX_CRITERIA)


def save_problem(scope, name, spec, draft=None):
    build_problem(spec, limits())
    if not name or len(name) > 120:
        raise ProblemError("Problem name must contain 1–120 characters.")
    if draft is None:
        draft = Problem(owner=scope.owner, workspace=scope.workspace)
    if draft.owner_id != scope.owner.pk or draft.workspace != scope.workspace:
        raise ProblemError("Problem belongs to another workspace.")
    draft.name, draft.spec = name, spec
    draft.save()
    return draft


def training_spec(dataset, preset="min-variance", estimator="ledoit-wolf", lookback=None):
    spec, estimate, digest = problem_from_training(dataset.prices, preset, estimator, lookback)
    spec["data"] = {"dataset_id": str(dataset.pk), "dataset_digest": dataset.digest,
                    "symbols": dataset.prices["symbols"], "estimation": estimate,
                    "estimates_digest": digest}
    return spec


def training_problem(scope, dataset, preset="min-variance", estimator="ledoit-wolf", lookback=None):
    spec = training_spec(dataset, preset, estimator, lookback)
    return save_problem(scope, (dataset.name + " · " + preset)[:120], spec)


def solve_problem(scope, name, spec, solver="CLARABEL", options=None, draft=None,
                  seconds=None, frontier_seconds=None):
    built = build_problem(spec, limits())
    preview = built.preview()
    if not preview["is_dcp"]:
        raise ProblemError("DCP rules failed. Check the problem before solving.")
    seconds = settings.LAB_SOLVE_SECONDS if seconds is None else seconds
    if built.criteria:
        result = run_frontier(spec, {**(options or {}), "solver": solver}, limits(),
            maximum_samples=settings.LAB_MAX_FRONTIER_SAMPLES,
            total_seconds=frontier_seconds or settings.LAB_FRONTIER_SECONDS, solve_seconds=seconds)
    else:
        result = solve(built, solver, seconds=seconds)
    draft = save_problem(scope, name, spec, draft)
    digest = content_digest({"spec": spec, "solver": solver,
                             "options": result.get("settings", result.get("solver_options"))})
    return Experiment.objects.create(owner=scope.owner, workspace=scope.workspace, problem=draft,
        name=name, spec=spec, preview=preview, result=result, digest=digest,
        kind="frontier" if built.criteria else "single")


def choose_point(scope, parent, index):
    point = next((p for p in parent.result.get("points", []) if p["id"] == index), None)
    if parent.kind != "frontier" or point is None or not accepted_solution(point["result"]):
        raise ProblemError("Choose a verified sampled frontier point.")
    child, _ = Experiment.objects.get_or_create(parent=parent, point_index=index, kind="chosen", defaults={
        "owner": scope.owner, "workspace": scope.workspace, "problem": parent.problem,
        "name": f"{parent.name[:95]} · chosen point {index}", "spec": point["solved_spec"],
        "preview": point["preview"], "result": {**point["result"], "selection": point,
        "criteria": parent.result["criteria"]}, "digest": content_digest({"parent": parent.digest, "point": point})})
    return child


def usable_variables(experiment):
    import numpy as np
    if experiment.kind == "frontier" or not accepted_solution(experiment.result):
        return []
    return [n for n, v in experiment.result["variables"].items() if v is not None and np.asarray(v).ndim == 1]


def evaluation_inputs(experiment, dataset, variable):
    if variable not in usable_variables(experiment):
        raise ProblemError("Choose a decision vector from a verified optimum. Save a frontier point as the chosen solution first.")
    binding = experiment.spec.get("data")
    if binding and (binding["dataset_digest"] != dataset.digest or binding["symbols"] != dataset.prices["symbols"]):
        raise ProblemError("This solution was bound to a different data snapshot or asset order. Create an editable problem from this dataset before solving.")
    weights = experiment.result["variables"][variable]
    if len(weights) != len(dataset.prices["symbols"]):
        raise ProblemError("Decision vector length must match the dataset asset count. Entries follow the displayed asset order.")
    return weights


def provenance_notice(experiment):
    edited = estimates_edited(experiment.spec)
    if edited is None:
        return "No imported training estimates are attached: these weights are a manually defined portfolio experiment."
    if edited:
        return "Imported training parameters were edited. Their original estimation provenance no longer certifies the current parameter values."
    return "Imported estimates and scenarios are unchanged and use training observations only."


def save_evaluation(scope, experiment, dataset, variable, window, options, seconds=None, evaluator=None, run=None, maximum_refits=None):
    if window == "holdout":
        existing = scope.query(Evaluation).filter(dataset_digest=dataset.digest, window="holdout").first()
        if existing:
            return existing
    weights = evaluation_inputs(experiment, dataset, variable)
    if window == "holdout" and run is None:
        from lab import research
        run, _ = research.begin(scope, experiment.name + " · final holdout", "backtest",
            {"experiment":str(experiment.pk), "options":options, "variable":variable}, dataset,
            window, claim_holdout=True)
    try:
        result = (evaluator or evaluate_portfolios)(dataset.prices, weights, window, options, experiment.spec,
            variable, limits(), seconds=seconds or settings.LAB_EVALUATION_SECONDS,
            maximum_refits=maximum_refits if maximum_refits is not None else settings.LAB_MAX_REFITS)
    except BaseException as error:
        if run:
            from lab import research
            research.finish(run, status="failed", error=str(error))
        raise
    result["provenance_notice"] = provenance_notice(experiment)
    result["runtime"] = experiment.result.get("runtime", {})
    defaults = dict(owner=scope.owner, workspace=scope.workspace, experiment=experiment, dataset=dataset,
        dataset_digest=dataset.digest, variable=variable, window=window, result=result,
        digest=content_digest({"experiment": experiment.digest, "dataset": dataset.digest,
                               "variable": variable, "window": window, "options": options}))
    if window == "holdout":
        saved, _ = Evaluation.objects.get_or_create(owner=scope.owner, workspace=scope.workspace,
            dataset_digest=dataset.digest, window=window, defaults={k: v for k, v in defaults.items()
            if k not in ("owner", "workspace", "dataset_digest", "window")})
        if run:
            from lab import research
            from core.research import portfolio_report
            status = "complete" if result["portfolio"]["status"] == "complete" else "partial"
            research.finish(run, portfolio_report(result), status, evaluation=saved, experiment=experiment)
        return saved
    return Evaluation.objects.create(**defaults)
