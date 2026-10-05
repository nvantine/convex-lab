"""Persist source revisions and foreground run evidence for web and CLI."""
from contextlib import contextmanager
from datetime import datetime
from importlib.metadata import distributions
from pathlib import Path
import hashlib
import json
import os
import platform
import signal
import socket
import subprocess
import sys
import time
from django.conf import settings
from django.db import IntegrityError, OperationalError, transaction
from django.utils import timezone
from core.data import content_digest, split_windows
from core.parser import ProblemError
from core.research import clean_json, file_checksum
from lab.models import ResearchRun, StrategyRevision, Evaluation

TERMINAL = {"complete", "partial", "failed", "interrupted"}


def runtime_versions():
    packages = {d.metadata["Name"]:d.version for d in distributions() if d.metadata["Name"]}
    files = sorted((settings.BASE_DIR/"core").glob("*.py"))
    files += [settings.BASE_DIR/"lab"/name for name in ("cli.py","services.py","research.py","workflows.py")]
    digest = content_digest({str(p.relative_to(settings.BASE_DIR)):p.read_text() for p in files if p.exists()})
    try:
        commit = subprocess.run(["git","rev-parse","HEAD"],cwd=settings.BASE_DIR,capture_output=True,text=True,timeout=2).stdout.strip()
    except (OSError, subprocess.TimeoutExpired): commit = None
    return {"python":platform.python_version(), "packages":packages, "app_code_digest":digest,
            "app_commit":commit, "platform":platform.platform()}


def register(scope, path, entry_point, interface, name, description=""):
    path = Path(path).expanduser().resolve()
    if not path.exists(): raise ProblemError("Source path does not exist.")
    root = path.parent if path.is_file() else path
    entry_point = entry_point or (f"{path.name}:target_weights" if interface == "portfolio" else f"{path.name}:run")
    try: filename, function = entry_point.rsplit(":", 1)
    except ValueError: raise ProblemError("Entry point must be relative/file.py:function.")
    entry = Path(filename)
    if entry.is_absolute() or ".." in entry.parts or entry.suffix != ".py" or not function.isidentifier():
        raise ProblemError("Choose a relative Python filename and function name.")
    sources = {}
    paths = [path] if path.is_file() else sorted(root.rglob("*"))
    for file in paths:
        if file.is_relative_to(settings.LAB_ARTIFACT_ROOT.resolve()):
            continue
        relative = file.relative_to(root)
        if file.is_symlink() or any(part.startswith(".") or part in ("__pycache__", "node_modules", "screenshots", "dist", "build") for part in relative.parts):
            continue
        if not file.is_file(): continue
        if file.suffix not in (".py", ".json", ".toml", ".lock", ".txt", ".md", ".yaml", ".yml"):
            continue
        if file.stat().st_size > 10_000_000:
            raise ProblemError("Source file exceeds 10 MB; store generated data as run artifacts.")
        sources[relative.as_posix()] = file.read_text()
    if any(redact(text) != text for text in sources.values()):
        raise ProblemError("Source contains a loaded secret. Load credentials from the environment rather than embedding them in code.")
    if filename not in sources:
        raise ProblemError("Entry point file is absent from the source bundle. Register its containing directory for helper modules.")
    if interface not in ("portfolio", "research"): raise ProblemError("Choose portfolio or research.")
    if not name or len(name) > 120: raise ProblemError("Strategy name must contain 1–120 characters.")
    digest = content_digest({"sources":sources, "entry_point":entry_point, "interface":interface})
    return StrategyRevision.objects.create(owner=scope.owner, workspace=scope.workspace, name=name,
        description=redact(description), interface=interface, entry_point=entry_point, sources=sources, digest=digest)


def retry_write(callback):
    """Only retry short, idempotent persistence operations, never research code."""
    for attempt in range(4):
        try: return callback()
        except OperationalError as error:
            if "locked" not in str(error).lower() or attempt == 3: raise
            time.sleep(.1 * 2**attempt)


def begin(scope, name, kind, config, dataset=None, window="", revision=None, parent=None,
          idempotency_key=None, claim_holdout=False):
    if idempotency_key is not None and not 1 <= len(idempotency_key) <= 200:
        raise ProblemError("Idempotency keys must contain 1–200 characters.")
    config = redact_payload(clean_json(config))
    if idempotency_key:
        existing = scope.query(ResearchRun).filter(idempotency_key=idempotency_key).first()
        if existing:
            if existing.config != config or existing.kind != kind or existing.dataset_id != getattr(dataset, "pk", None) or existing.revision_id != getattr(revision, "pk", None) or existing.window != window:
                raise ProblemError("Idempotency key was already used for a different invocation.")
            return existing, False
    if claim_holdout and (dataset is None or window != "holdout"):
        raise ProblemError("A holdout opening requires a dataset and holdout window.")
    if claim_holdout and scope.query(Evaluation).filter(dataset_digest=dataset.digest, window="holdout").exists():
        raise ProblemError("The final holdout was already opened through the website.")
    @transaction.atomic
    def create_run():
        return ResearchRun.objects.create(owner=scope.owner, workspace=scope.workspace,
            name=name[:120], kind=kind, config=config, dataset=dataset,
            dataset_digest=dataset.digest if dataset else "", window=window, revision=revision, parent=parent,
            idempotency_key=idempotency_key, holdout_claim=claim_holdout,
            runtime={**runtime_versions(), "host":socket.gethostname(), "pid":os.getpid(),
                     "process_started":process_identity(os.getpid())})
    try:
        run = retry_write(create_run)
    except IntegrityError:
        if idempotency_key:
            existing = scope.query(ResearchRun).filter(idempotency_key=idempotency_key).first()
            if existing:
                return begin(scope, name, kind, config, dataset, window, revision, parent, idempotency_key, claim_holdout)
        raise ProblemError("The final holdout is already reserved or opened. Inspect its saved research run.")
    return run, True


def finish(run, result=None, status="complete", error="", **links):
    if run.status != "running": return run
    run.result = redact_payload(clean_json(result or {}))
    run.status, run.error, run.finished_at = status, redact(error), timezone.now()
    for name, value in links.items(): setattr(run, name, value)
    retry_write(lambda: run.save(update_fields=["result","status","error","finished_at","artifacts",*links]))
    return run


@contextmanager
def evidence(run):
    """Persist failures and interruptions as well as successful numerical output."""
    try:
        yield run
    except BaseException as error:
        folder = settings.LAB_ARTIFACT_ROOT / str(run.pk)
        if folder.exists(): collect_artifacts(run, folder)
        finish(run, status="interrupted" if isinstance(error, KeyboardInterrupt) else "failed", error=str(error))
        raise


def secret_values():
    from core.providers import credentials
    values = [v for k, v in os.environ.items() if any(s in k.upper() for s in ("SECRET", "PASSWORD", "TOKEN", "API_KEY")) and len(v) >= 6]
    try: values.extend(credentials())
    except ProblemError: pass
    return sorted(set(values), key=len, reverse=True)


def redact(text, values=None):
    for value in secret_values() if values is None else values:
        if value: text = text.replace(value, "[REDACTED]")
    return text


def redact_payload(value, values=None):
    """Redact strings without altering numeric data or corrupting JSON syntax."""
    values = secret_values() if values is None else values
    if isinstance(value,str): return redact(value,values)
    if isinstance(value,list): return [redact_payload(item,values) for item in value]
    if isinstance(value,dict): return {redact(str(k),values):redact_payload(v,values) for k,v in value.items()}
    return value


def folder_for(run):
    folder = settings.LAB_ARTIFACT_ROOT / str(run.pk)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    return folder


def materialize(revision, folder):
    bundle = folder / "source"; bundle.mkdir(exist_ok=True)
    for name, text in revision.sources.items():
        target = bundle / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return bundle


def collect_artifacts(run, folder):
    artifacts = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.is_symlink(): continue
        relative = path.relative_to(folder)
        if "__pycache__" in relative.parts: continue
        if any(parent.is_symlink() for parent in path.parents if parent != folder): continue
        if path.suffix in (".log", ".txt", ".json", ".xml", ".py", ".md", ".toml", ".lock"):
            try: path.write_text(redact(path.read_text()))
            except UnicodeError: pass
        artifacts.append({"path":relative.as_posix(), "size":path.stat().st_size,
                          "sha256":file_checksum(path)})
    run.artifacts = artifacts


def process(run, command, folder, timeout, cwd=None, env=None):
    """Kill the child process group on timeout/Ctrl-C; keep both output streams."""
    if not 0 < timeout <= 86400: raise ProblemError("Timeout must be between 0 and 86400 seconds.")
    with (folder / "stdout.log").open("w") as out, (folder / "stderr.log").open("w") as err:
        child = subprocess.Popen(command, cwd=cwd, env=env, stdout=out, stderr=err, start_new_session=True)
        run.runtime.update({"host":socket.gethostname(), "pid":os.getpid(), "child_pid":child.pid,
                            "process_started":process_identity(os.getpid()), "child_started":process_identity(child.pid)})
        run.save(update_fields=["runtime"])
        try:
            return child.wait(timeout=timeout)
        except BaseException:
            try: os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError: pass
            try: child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try: os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                child.wait()
            raise


def process_identity(pid):
    """Linux process start tick prevents confusing a reused PID with this run."""
    try: return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except OSError: return None


def recover(run):
    if run.status != "running": return run
    runtime = run.runtime
    if runtime.get("host") != socket.gethostname() or "pid" not in runtime:
        raise ProblemError("Recovery needs a run process recorded on this host.")
    if process_identity(runtime["pid"]) == runtime.get("process_started") and runtime.get("process_started") is not None:
        raise ProblemError("The recorded process is still running.")
    child = runtime.get("child_pid")
    if child and runtime.get("child_started") and process_identity(child) == runtime["child_started"]:
        try: os.killpg(child,signal.SIGTERM)
        except ProcessLookupError: pass
        deadline=time.monotonic()+2
        while process_identity(child)==runtime["child_started"] and time.monotonic()<deadline:
            time.sleep(.05)
        if process_identity(child)==runtime["child_started"]:
            try: os.killpg(child,signal.SIGKILL)
            except ProcessLookupError: pass
    return finish(run, status="interrupted", error="The recorded CLI process ended before saving its result.")


def run_python(run, params, options, seed, timeout):
    folder = folder_for(run)
    bundle = materialize(run.revision, folder)
    output = folder / "artifacts"; output.mkdir(exist_ok=True)
    payload = run.dataset.prices if run.dataset else None
    train_end, windows = None, None
    if payload:
        windows = split_windows(payload); train_end = windows["train"]["end"]
        end = windows[run.window]["end"]+1
        payload = {**payload, "dates":payload["dates"][:end], "values":payload["values"][:end]}
    request = {"bundle":str(bundle), "entry_point":run.revision.entry_point, "interface":run.revision.interface,
               "artifacts":str(output), "prices":payload, "train_end":train_end, "params":params,
               "options":options, "seed":seed, "window":run.window or "validation", "windows":windows,
               "maximum_refits":run.config.get("max_refits",10000)}
    input_path, output_path = folder / "input.json", folder / "output.json"
    input_path.write_text(json.dumps(request, allow_nan=False))
    with evidence(run):
        code = process(run, [sys.executable, "-m", "core.research_worker", str(input_path), str(output_path)],
                       folder, timeout)
        if not output_path.exists():
            raise ProblemError(f"Python process exited with code {code} without a result. Inspect logs.")
        response = json.loads(output_path.read_text())
        if code or not response["ok"]: raise ProblemError(response.get("error", f"Process exited with code {code}."))
        result = response["result"]
        for name in result.get("artifacts", []):
            path = (output / name).resolve()
            if not path.is_relative_to(output.resolve()) or not path.is_file():
                raise ProblemError("A declared artifact is missing or outside the artifact directory.")
        # Capture all produced files, including model artifacts, not just a
        # self-reported path list. Web views serve only the frozen manifest.
        collect_artifacts(run, folder)
        status = "partial" if result.get("portfolio", {}).get("status", "complete") != "complete" else "complete"
        finish(run, result, status)
    return run


def run_tests(run, timeout, pytest_args):
    import xml.etree.ElementTree as ET
    folder = folder_for(run); bundle = materialize(run.revision, folder)
    report = folder / "pytest.xml"
    env = {**os.environ, "LAB_DATABASE_PATH":str(folder / "tests.sqlite3"),
           "LAB_TEST_DATABASE_PATH":str(folder / "tests-test.sqlite3")}
    with evidence(run):
        code = process(run, [sys.executable, "-m", "pytest", str(bundle), "--rootdir", str(bundle),
            "-o", "testpaths=", "--junit-xml", str(report), *pytest_args], folder, timeout, cwd=bundle, env=env)
        counts = {"tests":0, "failures":0, "errors":0, "skipped":0}
        cases = []
        if report.exists():
            root = ET.parse(report).getroot()
            for suite in root.iter("testsuite"):
                for key in counts: counts[key] += int(suite.get(key, "0"))
            for case in root.iter("testcase"):
                failed = case.find("failure"); error = case.find("error"); skipped = case.find("skipped")
                failure = failed if failed is not None else error
                cases.append({"name":case.get("name"), "status":"failed" if failure is not None else "skipped" if skipped is not None else "passed",
                              "message":redact(failure.get("message", "") if failure is not None else "")})
        result = {"schema_version":1, "provenance":"pytest", "exit_code":code, "counts":counts,
                  "metrics":{key:{"value":value, "unit":"count", "direction":"none"} for key,value in counts.items()},
                  "tables":[{"title":"Test cases", "columns":["Name","Status","Message"],
                             "rows":[[c["name"],c["status"],c["message"]] for c in cases]}],
                  "charts":[], "equations":[], "text":"Pytest evidence for this exact source revision."}
        collect_artifacts(run, folder)
        finish(run, result, "complete" if code == 0 else "failed", error="" if code == 0 else f"pytest exited with code {code}")
    return run
