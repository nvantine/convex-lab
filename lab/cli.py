"""Agent-friendly local CLI. No HTTP API or separate agent account."""
import argparse
import json
import os
from pathlib import Path
import sys


class CLIError(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CLIError(message)


def read_json(value):
    try:
        return json.loads(sys.stdin.read() if value == "-" else Path(value).read_text())
    except (ValueError, OSError) as error:
        raise CLIError(f"Cannot read JSON input: {error}") from error


def object_json(value):
    try:
        result = json.loads(value)
    except ValueError as error:
        raise CLIError("Expected a JSON object.") from error
    if not isinstance(result, dict):
        raise CLIError("Expected a JSON object.")
    return result


def parser():
    p = Parser(description="Convex Lab: local research CLI. JSON output is the default.")
    p.add_argument("--owner", help="Django staff username; overrides local configuration")
    p.add_argument("--human", action="store_true", help="Pretty-print output")
    p.add_argument("--idempotency-key", help="Reuse the same saved run for a retried invocation")
    sub = p.add_subparsers(dest="command", required=True, parser_class=Parser)
    config = sub.add_parser("config", help="Save owner and website URL in .local/cli.json")
    config.add_argument("username"); config.add_argument("--site-url", default="http://127.0.0.1:8000")
    for name in ("doctor", "whoami", "capabilities"):
        sub.add_parser(name)
    presets = sub.add_parser("presets"); presets.add_argument("name", nargs="?")
    data = sub.add_parser("datasets").add_subparsers(dest="action", required=True)
    data.add_parser("list")
    for name in ("show", "status", "resume", "refresh", "export"):
        cmd = data.add_parser(name); cmd.add_argument("id")
        if name == "resume":
            cmd.add_argument("--retry-errors", action="store_true")
            cmd.add_argument("--save-available", action="store_true")
        if name == "export":
            cmd.add_argument("--window", choices=("train", "validation", "holdout"), default="validation")
            cmd.add_argument("--confirm-holdout", action="store_true")
    cmd = data.add_parser("fetch")
    cmd.add_argument("--source", choices=("alpaca", "yfinance"), required=True)
    cmd.add_argument("--symbols", required=True, help="Comma-separated ticker symbols")
    cmd.add_argument("--start", required=True); cmd.add_argument("--end", required=True)
    cmd.add_argument("--name", default="CLI market history")
    cmd.add_argument("--batch-size", type=int, choices=range(1, 6), default=5)
    cmd.add_argument("--no-cache", action="store_true"); cmd.add_argument("--refresh-daily", action="store_true")
    problem = sub.add_parser("problems").add_subparsers(dest="action", required=True)
    problem.add_parser("list")
    for name in ("show", "clone", "check"):
        cmd = problem.add_parser(name); cmd.add_argument("id")
    for name in ("create", "update"):
        cmd = problem.add_parser(name)
        if name == "update": cmd.add_argument("id")
        cmd.add_argument("--name", required=True)
        source = cmd.add_mutually_exclusive_group(required=True)
        source.add_argument("--file", help="Symbolic JSON, or - for stdin"); source.add_argument("--preset")
        source.add_argument("--dataset", help="Create from training observations only")
        cmd.add_argument("--language", choices=("expression", "latex"), default="expression")
        cmd.add_argument("--template", default="min-variance")
        cmd.add_argument("--estimator", choices=("sample", "ledoit-wolf"), default="ledoit-wolf")
        cmd.add_argument("--lookback", type=int)
    for name in ("solve", "frontier"):
        cmd = sub.add_parser(name); cmd.add_argument("id")
        cmd.add_argument("--solver", choices=("CLARABEL", "OSQP", "SCS"), default="CLARABEL")
        cmd.add_argument("--options", type=object_json, default={})
    cmd = sub.add_parser("choose"); cmd.add_argument("id"); cmd.add_argument("--point", type=int, required=True)
    cmd = sub.add_parser("backtest"); cmd.add_argument("id", help="Saved experiment or strategy revision")
    cmd.add_argument("--dataset", required=True); cmd.add_argument("--variable", default="w")
    cmd.add_argument("--window", choices=("validation", "holdout"), default="validation")
    cmd.add_argument("--confirm-holdout", action="store_true")
    cmd.add_argument("--options", type=object_json, default={})
    cmd.add_argument("--seed", type=int, default=42); cmd.add_argument("--timeout", type=float, default=600)
    cmd.add_argument("--params", type=object_json, default={})
    strategies = sub.add_parser("strategies").add_subparsers(dest="action", required=True)
    strategies.add_parser("list")
    cmd = strategies.add_parser("show"); cmd.add_argument("id")
    cmd = strategies.add_parser("register"); cmd.add_argument("path"); cmd.add_argument("--entry-point")
    cmd.add_argument("--interface", choices=("portfolio", "research"), required=True)
    cmd.add_argument("--name", required=True); cmd.add_argument("--description", default="")
    cmd = sub.add_parser("research").add_subparsers(dest="action", required=True).add_parser("run")
    cmd.add_argument("id"); cmd.add_argument("--dataset")
    cmd.add_argument("--params", type=object_json, default={}); cmd.add_argument("--seed", type=int, default=42)
    cmd.add_argument("--window", choices=("train", "validation", "holdout"), default="validation")
    cmd.add_argument("--confirm-holdout", action="store_true"); cmd.add_argument("--timeout", type=float, default=600)
    cmd = sub.add_parser("tests").add_subparsers(dest="action", required=True).add_parser("run")
    cmd.add_argument("id"); cmd.add_argument("--timeout", type=float, default=600)
    cmd.add_argument("--pytest-args", type=json.loads, default=[])
    runs = sub.add_parser("runs").add_subparsers(dest="action", required=True)
    runs.add_parser("list")
    for name in ("show", "export", "recover", "replay"):
        cmd = runs.add_parser(name); cmd.add_argument("id")
        if name == "replay": cmd.add_argument("--allow-version-mismatch", action="store_true")
    cmd = sub.add_parser("notes").add_subparsers(dest="action", required=True).add_parser("add")
    cmd.add_argument("id"); cmd.add_argument("--kind", choices=("finding", "bug", "idea"), default="finding")
    cmd.add_argument("--text", required=True)
    return p


def configure():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django
    django.setup()


def local_config():
    from django.conf import settings
    path = settings.BASE_DIR / ".local" / "cli.json"
    return path, json.loads(path.read_text()) if path.exists() else {}


def scope_for(args):
    from django.contrib.auth import get_user_model
    from django.conf import settings
    from lab.workspaces import Scope, owner_workspace
    username = args.owner or local_config()[1].get("owner")
    user = get_user_model().objects.filter(username=username, is_staff=True, is_active=True).first()
    if not user or user.username == settings.GUEST_USERNAME:
        raise CLIError("Configure an active staff owner: uv run convex-lab config YOUR_USERNAME")
    return Scope(user, owner_workspace(user))


def get_record(scope, model, value):
    from django.core.exceptions import ValidationError
    try:
        result = scope.query(model).filter(pk=value).first()
    except (ValidationError, ValueError):
        result = None
    if result is None:
        raise CLIError(f"No {model.__name__} with that ID in your workspace.")
    return result


def url(name, pk):
    from django.urls import reverse
    return local_config()[1].get("site_url", "http://127.0.0.1:8000").rstrip("/") + reverse(name, args=[pk])


def snapshot(record):
    names = {"Problem": "edit", "Experiment": "result", "Dataset": "dataset",
             "Evaluation": "evaluation", "FetchRequest": "fetch_progress",
             "ResearchRun": "research_run", "StrategyRevision": "strategy_revision"}
    data = {"id": str(record.pk), "name": getattr(record, "name", ""),
            "url": url(names[type(record).__name__], record.pk)}
    for field in ("digest", "status", "kind", "window"):
        if hasattr(record, field): data[field] = getattr(record, field)
    if hasattr(record, "result"): data["result"] = record.result
    if hasattr(record, "spec"): data["spec"] = record.spec
    return data


def fetch_until_done(record):
    from lab import fetching
    while fetching.pending(record) and not record.dataset_id:
        print(f"Fetching {len(record.series)}/{len(record.symbols)} symbols…", file=sys.stderr)
        fetching.next_batch(record)
        record.refresh_from_db()
    data = snapshot(record)
    data.update(completed=len(record.series), total=len(record.symbols), errors=record.errors, message=record.message,
                dataset=snapshot(record.dataset) if record.dataset_id else None)
    return data


def execute_base(args, run=None):
    from django.conf import settings
    from core.parser import ATOMS, build_problem
    from core.presets import PRESETS, get_preset
    from core.input import convert_spec
    from core.data import split_windows
    from lab import services, fetching
    from lab.models import Problem, Experiment, Dataset, FetchRequest
    if args.command == "capabilities":
        return {"commands": list(parser()._subparsers._group_actions[0].choices),
                "atoms": sorted(ATOMS), "solvers": ["CLARABEL", "OSQP", "SCS"],
                "interfaces": ["symbolic", "portfolio", "research"], "schema_version": 1}
    if args.command == "presets":
        return get_preset(args.name) if args.name else {key: value[0] for key, value in PRESETS.items()}
    if args.command == "doctor":
        import cvxpy
        from core.providers import credentials
        try: credentials(); loaded = True
        except Exception: loaded = False
        return {"database_exists": Path(settings.DATABASES["default"]["NAME"]).exists(),
                "installed_solvers": cvxpy.installed_solvers(), "alpaca_credentials_loaded": loaded,
                "configuration": {k: v for k, v in local_config()[1].items() if k in ("owner", "site_url")}}
    if args.command == "config":
        args.owner = args.username
        scope_for(args)
        path, _ = local_config()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"owner": args.username, "site_url": args.site_url}))
        path.chmod(0o600)
        return {"configured": True, "owner": args.username, "site_url": args.site_url}
    scope = scope_for(args)
    if args.command == "whoami":
        return {"owner": scope.owner.username, "workspace": str(scope.workspace)}
    if args.command == "datasets":
        if args.action == "list":
            return [{"id": str(d.pk), "name": d.name, "source": d.source, "digest": d.digest,
                     "symbols": d.prices["symbols"], "url": url("dataset", d.pk)} for d in scope.query(Dataset)]
        if args.action == "fetch":
            from lab.forms import DatasetForm
            form = DatasetForm({"name": args.name, "source": args.source, "symbols": args.symbols,
                "start": args.start, "end": args.end, "batch_size": args.batch_size,
                "prefer_cache": not args.no_cache, "refresh_daily": args.refresh_daily})
            if not form.is_valid(): raise CLIError(str(form.errors.as_json()))
            record = FetchRequest.objects.create(owner=scope.owner, workspace=scope.workspace, **form.cleaned_data)
            return fetch_until_done(record)
        if args.action in ("resume", "status", "refresh"):
            record = get_record(scope, FetchRequest, args.id)
            if args.action == "refresh":
                fetching.refresh_record(record); record.refresh_from_db()
            if args.action == "resume" and args.retry_errors:
                record.errors = {}; record.save(update_fields=["errors"])
            if args.action == "resume" and args.save_available:
                fetching.finalize(record, [s for s in record.symbols if s in record.series])
                record.save()
            if args.action != "status": return fetch_until_done(record)
            return {**snapshot(record), "completed": len(record.series), "total": len(record.symbols),
                    "errors": record.errors, "dataset_id": str(record.dataset_id) if record.dataset_id else None}
        dataset = get_record(scope, Dataset, args.id)
        windows = split_windows(dataset.prices)
        if args.action == "show":
            return {**snapshot(dataset), "symbols": dataset.prices["symbols"], "windows": windows,
                    "provenance": dataset.provenance}
        end = windows[args.window]["end"] + 1
        return {"dataset_id": str(dataset.pk), "digest": dataset.digest, "window": args.window,
                "prices": {**dataset.prices, "dates": dataset.prices["dates"][:end], "values": dataset.prices["values"][:end]}}
    if args.command == "problems":
        if args.action == "list":
            return [{"id": str(p.pk), "name": p.name, "url": url("edit", p.pk)} for p in scope.query(Problem)]
        draft = get_record(scope, Problem, args.id) if hasattr(args, "id") else None
        if args.action == "show": return snapshot(draft)
        if args.action == "check": return build_problem(draft.spec, services.limits()).preview()
        if args.action == "clone":
            return snapshot(services.save_problem(scope, (draft.name + " (copy)")[:120], draft.spec))
        if args.dataset:
            record = services.training_problem(scope, get_record(scope, Dataset, args.dataset),
                args.template, args.estimator, args.lookback)
            if draft:
                # Reuse the original draft rather than leave an extra imported draft.
                spec = record.spec; record.delete()
            else: spec = record.spec; draft = record
        else:
            spec = convert_spec(read_json(args.file) if args.file else get_preset(args.preset),
                                args.language, services.limits())
        return snapshot(services.save_problem(scope, args.name, spec, draft))
    if args.command in ("solve", "frontier"):
        draft = get_record(scope, Problem, args.id)
        if (args.command == "frontier") != bool(draft.spec.get("criteria")):
            raise CLIError("Use frontier for multiple criteria and solve for a single objective.")
        return snapshot(services.solve_problem(scope, draft.name, draft.spec, args.solver, args.options, draft))
    if args.command == "choose":
        return snapshot(services.choose_point(scope, get_record(scope, Experiment, args.id), args.point))
    if args.command == "backtest":
        if args.window == "holdout" and not args.confirm_holdout:
            raise CLIError("Opening the final holdout requires --window holdout --confirm-holdout.")
        experiment = get_record(scope, Experiment, args.id)
        dataset = get_record(scope, Dataset, args.dataset)
        options = {"mode": "rolling", "frequency": "monthly", "lookback": 126, "estimator": "ledoit-wolf",
                   "solver": "CLARABEL", **{k: v for k, v in {
                   "mean_parameter": "mu", "covariance_parameter": "Sigma", "returns_parameter": "R",
                   "scenario_count_parameter": "scenario_count", "previous_weights_parameter": "w_prev",
                   "scenario_variable": "u"}.items() if v in
                   [d["name"] for d in experiment.spec["parameters"] + experiment.spec["variables"]]}, **args.options}
        return snapshot(services.save_evaluation(scope, experiment, dataset, args.variable, args.window, options, run=run))
    raise CLIError("Unknown command.")


def execute(args):
    from core.parser import ProblemError
    from core.research import portfolio_report
    from lab import research, services
    from lab.models import ResearchRun, StrategyRevision, Dataset, Problem, Experiment, Evaluation
    if args.command in ("config", "doctor", "capabilities", "presets", "whoami"):
        return execute_base(args)
    scope = scope_for(args)
    if args.command == "strategies":
        if args.action == "list":
            return [{**snapshot(r), "interface":r.interface, "entry_point":r.entry_point} for r in scope.query(StrategyRevision)]
        if args.action == "show":
            r = get_record(scope, StrategyRevision, args.id)
            return {**snapshot(r), "interface":r.interface, "entry_point":r.entry_point, "sources":r.sources}
        return snapshot(research.register(scope, args.path, args.entry_point, args.interface, args.name, args.description))
    if args.command == "runs":
        if args.action == "list":
            return [{"id":str(r.pk), "name":r.name, "kind":r.kind, "status":r.status, "url":url("research_run", r.pk)}
                    for r in scope.query(ResearchRun)]
        run = get_record(scope, ResearchRun, args.id)
        if args.action == "recover": return snapshot(research.recover(run))
        if args.action == "replay": return replay(scope, run, args)
        return {**snapshot(run), "config":run.config, "runtime":run.runtime, "artifacts":run.artifacts,
                "notes":run.notes, "error":run.error, "revision_id":str(run.revision_id) if run.revision_id else None}
    if args.command == "notes":
        from django.db import transaction
        from django.utils import timezone
        # Short immediate SQLite transaction serializes concurrent annotations.
        with transaction.atomic():
            run = get_record(scope, ResearchRun, args.id)
            run.notes = [*run.notes, {"kind":args.kind, "text":args.text, "at":timezone.now().isoformat()}]
            run.save(update_fields=["notes"])
        return snapshot(run)
    is_custom = args.command in ("research", "tests")
    if args.command == "backtest":
        is_custom = scope.query(StrategyRevision).filter(pk=args.id).exists()
    should_save = is_custom or args.command in ("solve", "frontier", "backtest", "choose") or (
        args.command == "datasets" and args.action in ("fetch", "resume", "refresh", "export"))
    if not should_save: return execute_base(args)
    config = {k:v for k,v in vars(args).items() if k not in ("owner", "human", "idempotency_key")}
    dataset = get_record(scope, Dataset, args.dataset) if getattr(args, "dataset", None) else None
    if args.command == "datasets" and args.action == "export": dataset = get_record(scope, Dataset, args.id)
    revision = get_record(scope, StrategyRevision, args.id) if is_custom else None
    if revision and args.command == "backtest" and revision.interface != "portfolio":
        raise CLIError("Use research run for a standalone research script.")
    if revision and args.command == "research" and revision.interface != "research":
        raise CLIError("Use backtest for a portfolio callback.")
    if revision and revision.interface == "portfolio" and not dataset:
        raise CLIError("Portfolio strategies require --dataset.")
    window = getattr(args, "window", "")
    if window == "holdout" and not args.confirm_holdout:
        raise CLIError("Opening the final holdout requires --window holdout --confirm-holdout.")
    if window == "holdout" and dataset is None: raise CLIError("Holdout research requires --dataset.")
    if hasattr(args, "seed") and not 0 <= args.seed < 2**32: raise CLIError("Seed must be between 0 and 2^32-1.")
    if hasattr(args, "timeout") and not 0 < args.timeout <= 86400: raise CLIError("Timeout must be positive and at most 86400 seconds.")
    if args.command in ("solve", "frontier"):
        draft = get_record(scope, Problem, args.id); config["spec"] = draft.spec
    if args.command == "tests" and (not isinstance(args.pytest_args, list) or any(not isinstance(x,str) for x in args.pytest_args)):
        raise CLIError("--pytest-args must be a JSON list of argument strings.")
    name = revision.name if revision else args.command + " · " + getattr(args, "action", getattr(args, "id", ""))[:80]
    run, created = research.begin(scope, name, "tests" if args.command == "tests" else "backtest" if args.command == "backtest"
        else "research" if is_custom else args.command, config, dataset, window, revision,
        idempotency_key=args.idempotency_key, claim_holdout=window == "holdout")
    if not created: return snapshot(run)
    try:
        with research.evidence(run):
            if is_custom:
                if args.command == "tests":
                    research.run_tests(run, args.timeout, args.pytest_args)
                else:
                    options = {"mode":"fixed", "frequency":"monthly", "lookback":126, **getattr(args, "options", {})}
                    research.run_python(run, args.params, options, args.seed, args.timeout)
                return snapshot(run)
            output = execute_base(args, run=run)
            links = {}
            if args.command in ("solve", "frontier", "choose"):
                saved = get_record(scope, Experiment, output["id"]); links["experiment"] = saved
                report = {"schema_version":1, "provenance":"CVXPY", "metrics":{
                    "objective_value":{"value":saved.result.get("optimal_value"), "unit":"objective", "direction":saved.spec.get("objective", {}).get("sense", "none")}},
                    "text":"Saved symbolic solution; inspect its mathematics and solver evidence.", "charts":[], "tables":[], "equations":[]}
                if saved.kind == "frontier":
                    from core.charts import frontier_charts
                    report["charts"] = [{"figure":c["figure"]} for c in frontier_charts(saved.result)]
            elif args.command == "backtest":
                saved = get_record(scope, Evaluation, output["id"]); links.update(evaluation=saved, experiment=saved.experiment)
                report = portfolio_report(saved.result)
            else:
                report = {"schema_version":1, "provenance":"data operation", "metrics":{}, "operation":output}
            if run.status == "running":
                research.finish(run, report, **links)
            return {**output, "run_id":str(run.pk), "run_url":url("research_run", run.pk)}
    except Exception as error:
        raise CLIError(f"{research.redact(str(error))} Saved run: {run.pk}; {url('research_run', run.pk)}") from error


def replay(scope, original, args):
    from lab import research
    if original.holdout_claim:
        raise CLIError("Final holdout runs cannot be replayed as another untouched test.")
    if research.runtime_versions()["packages"] != original.runtime.get("packages") and not args.allow_version_mismatch:
        raise CLIError("Dependency versions differ. Restore recorded versions or pass --allow-version-mismatch.")
    config = {**original.config, "replay_of":str(original.pk)}
    run, _ = research.begin(scope, original.name + " · replay", original.kind, config, original.dataset,
                            original.window, original.revision, idempotency_key=args.idempotency_key)
    with research.evidence(run):
        if original.revision:
            if original.kind == "tests":
                research.run_tests(run, config.get("timeout",600), config.get("pytest_args",[]))
            else:
                options = {"mode":"fixed", "frequency":"monthly", "lookback":126, **config.get("options",{})}
                research.run_python(run, config.get("params",{}), options, config.get("seed",42), config.get("timeout",600))
        elif original.kind in ("solve", "frontier"):
            from lab import services
            saved = services.solve_problem(scope, original.name, config["spec"], config["solver"], config.get("options"))
            research.finish(run, {"schema_version":1,"provenance":"CVXPY", "metrics":{}}, experiment=saved)
        else:
            raise CLIError("Replay is supported for Python runs, tests, and symbolic solves. Repeat other commands with their frozen configuration.")
    return snapshot(run)


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        configure()
        data = execute(args)
        print(json.dumps({"schema_version": 1, "ok": True, "data": data},
                         allow_nan=False, default=str, indent=2 if args.human else None))
        return 1 if isinstance(data, dict) and data.get("status") in ("failed", "interrupted", "partial") else 0
    except KeyboardInterrupt:
        print(json.dumps({"schema_version": 1, "ok": False, "error": {"code": "interrupted", "message": "Interrupted."}}))
        return 130
    except Exception as error:
        from core.parser import ProblemError
        from django.db import OperationalError
        code = 2 if isinstance(error, (CLIError, ProblemError, ValueError, KeyError)) else 3 if isinstance(error, OperationalError) else 1
        from lab.research import redact
        print(json.dumps({"schema_version": 1, "ok": False, "error":
              {"code": "invalid_input" if code == 2 else "retryable" if code == 3 else "execution_failed",
               "message": redact(str(error))}}))
        return code


if __name__ == "__main__":
    sys.exit(main())
