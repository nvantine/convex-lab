"""Foreground sweeps share persistence and math with individual research runs."""
import time
from core.workflows import grid_trials, apply_trial, summarize_trials
from core.parser import ProblemError
from core.research import portfolio_report
from lab import research, services
from lab.models import Problem, Experiment, StrategyRevision


def sweep(scope, target, dataset, grid, seeds, params, options, metric, direction, timeout,
          maximum=100, idempotency_key=None, variable="w"):
    trials = list(grid_trials(grid,seeds,maximum))
    revision = target if isinstance(target,StrategyRevision) else None
    spec = None if revision else target.spec
    if not revision and spec.get("criteria"):
        raise ProblemError("Sweep a scalar problem or a chosen frontier solution, not a frontier definition.")
    if not revision and not dataset: raise ProblemError("Symbolic backtest sweeps require --dataset.")
    if revision and revision.interface == "portfolio" and not dataset: raise ProblemError("Portfolio sweeps require --dataset.")
    if revision and any(k.startswith("parameters.") for k in grid):
        raise ProblemError("Python sweeps use params. and options.; parameters. is for symbolic problems.")
    base = {"spec":spec,"params":params,"options":options}
    # Validate every grid address before starting the campaign.
    for trial in trials: apply_trial(base,trial)
    config = {"target_id":str(target.pk), "spec":spec, "grid":grid, "seeds":seeds,
              "params":params,"options":options,"metric":metric,"direction":direction,"timeout":timeout,"maximum":maximum,
              "variable":variable}
    parent, created = research.begin(scope,target.name+" · sweep","sweep",config,dataset,
        "validation",revision,idempotency_key=idempotency_key)
    if not created: return parent
    start = time.monotonic(); evidence = []
    with research.evidence(parent):
        for index, trial in enumerate(trials):
            if time.monotonic()-start >= timeout: break
            changed = apply_trial(base,trial)
            config = {**changed,"changes":trial["changes"],"seed":trial["seed"]}
            child, _ = research.begin(scope,f"{target.name[:85]} · trial {index+1}","backtest" if not revision or revision.interface=="portfolio" else "research",
                config,dataset,"validation",revision,parent)
            try:
                with research.evidence(child):
                    budget = max(.01,timeout-(time.monotonic()-start))
                    if revision:
                        research.run_python(child,changed["params"],{"mode":"rolling","frequency":"monthly","lookback":126,
                            **changed["options"]},trial["seed"],budget)
                    else:
                        experiment = services.solve_problem(scope,child.name,changed["spec"])
                        params_by_name = {p["name"] for p in changed["spec"]["parameters"]}
                        variables = {v["name"] for v in changed["spec"]["variables"]}
                        bindings = {"mean_parameter":"mu","covariance_parameter":"Sigma","returns_parameter":"R",
                            "scenario_count_parameter":"scenario_count","previous_weights_parameter":"w_prev","scenario_variable":"u"}
                        defaults = {k:v for k,v in bindings.items() if v in (variables if k=="scenario_variable" else params_by_name)}
                        evaluation = services.save_evaluation(scope,experiment,dataset,variable,"validation",
                            {"mode":"rolling","frequency":"monthly","lookback":126,"estimator":"ledoit-wolf","solver":"CLARABEL",
                             **defaults,**changed["options"]},seconds=budget,maximum_refits=10000)
                        report = portfolio_report(evaluation.result)
                        status = "complete" if evaluation.result["portfolio"]["status"]=="complete" else "partial"
                        research.finish(child,report,status,experiment=experiment,evaluation=evaluation)
            except Exception:
                # The attempt is already saved by evidence(); continue the grid.
                pass
            evidence.append({"id":str(child.pk),"status":child.status,"seed":trial["seed"],
                             "changes":trial["changes"],"result":child.result})
        report = summarize_trials(evidence,metric,direction)
        report["summary"]["planned"] = len(trials)
        report["summary"]["not_started"] = len(trials)-len(evidence)
        if not report["summary"]["ranked"]:
            status = "failed"
            error = "No completed trials produced the requested ranking metric."
        else:
            status = "complete" if len(evidence)==len(trials) and all(t["status"]=="complete" for t in evidence) else "partial"
            error = ""
        research.finish(parent,report,status,error)
    return parent
