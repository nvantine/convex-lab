"""Pure SDK, subprocess research, saved evidence, and owner boundaries."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse
from core.research import ResearchResult, result_payload, clean_json
from core.data import aligned_prices
from core.parser import ProblemError
from lab import research, services
from lab.models import Dataset, ResearchRun, StrategyRevision
from lab.workspaces import Scope, owner_workspace
from test_data import synthetic_frame
from test_cli import invoke


def test_sdk_nonfinite_schema_and_plotly():
    import numpy as np
    import plotly.graph_objects as go
    assert clean_json({"x":np.array([1,2])}) == {"x":[1,2]}
    for value in (float("nan"),float("inf"),np.array([float("nan")])):
        with pytest.raises(ValueError): clean_json(value)
    with pytest.raises(ProblemError): result_payload({})
    with pytest.raises(ProblemError): result_payload(ResearchResult(metrics={"x":{"value":1}}))
    with pytest.raises(ProblemError): result_payload(ResearchResult(tables=[{"columns":["A"],"rows":[[1,2]]}]))
    result = ResearchResult(metrics={"x":{"value":1,"unit":"ratio"}},
                            charts=[{"figure":go.Figure(go.Scatter(y=[1,2])).to_plotly_json()}])
    assert result_payload(result)["provenance"] == "script-reported"


@pytest.fixture
def scope(owner):
    return Scope(owner, owner_workspace(owner))


@pytest.fixture
def artifacts(settings, tmp_path):
    settings.LAB_ARTIFACT_ROOT = tmp_path / "runs"
    return settings.LAB_ARTIFACT_ROOT


@pytest.fixture
def dataset(scope):
    payload, _ = aligned_prices(synthetic_frame(), ["SPY","AGG"])
    return Dataset.objects.create(owner=scope.owner,workspace=scope.workspace,name="Research prices",
        source="synthetic",prices=payload,provenance={},digest="research-data")


def register_file(scope, tmp_path, text, interface="research"):
    path = tmp_path / "model.py"; path.write_text(text)
    return research.register(scope, path, f"model.py:{'target_weights' if interface == 'portfolio' else 'run'}",
                             interface, "Local model")


@pytest.mark.django_db
def test_custom_research_logs_seed_artifacts_and_replay(scope, artifacts, capsys, tmp_path):
    source = '''from core.research import ResearchResult
def run(context, params):
    print("A diagnostic, not CLI JSON")
    (context.artifact_dir / "model.txt").write_text("model evidence")
    return ResearchResult(metrics={"score":{"value":float(context.rng.normal()),"unit":"ratio"}},
        equations=[r"x^2"], artifacts=["model.txt"])
'''
    revision = register_file(scope, tmp_path, source)
    code, out = invoke(capsys, scope.owner, "research", "run", revision.pk, "--seed", "12")
    assert code == 0
    run = ResearchRun.objects.get()
    assert run.status == "complete" and run.revision == revision
    assert any(a["path"] == "artifacts/model.txt" for a in run.artifacts)
    assert (artifacts/str(run.pk)/"stdout.log").read_text().startswith("A diagnostic")
    _, replayed = invoke(capsys, scope.owner, "runs", "replay", run.pk)
    assert replayed["data"]["result"] == run.result
    run.result = {}; run.status = "failed"
    with pytest.raises(ValidationError): run.save()
    revision.description = "changed"
    with pytest.raises(ValidationError): revision.save()


@pytest.mark.django_db
def test_custom_backtest_past_only_signed_and_dataset_truncation(scope, dataset, artifacts, tmp_path, capsys):
    source = '''from core.research import StrategyDecision
def target_weights(context, params, state):
    assert str(context.history.index[-1].date()) == context.signal_date
    assert len(context.history) == 31
    assert context.history.index.max() < __import__("pandas").Timestamp(params["first_holdout"])
    return StrategyDecision({"SPY":1.2,"AGG":-0.2}, (state or 0)+1,
        {"signal_date":context.signal_date,"state":(state or 0)+1})
'''
    revision = register_file(scope, tmp_path, source, "portfolio")
    from core.data import split_windows
    first_holdout = split_windows(dataset.prices)["holdout"]["first"]
    code, out = invoke(capsys, scope.owner, "backtest", revision.pk, "--dataset", dataset.pk,
        "--params", json.dumps({"first_holdout":first_holdout}),
        "--options", '{"lookback":30,"frequency":"weekly"}')
    assert code == 0, out
    run = ResearchRun.objects.get()
    path = run.result["portfolio"]
    assert len(path["trades"]) > 2
    assert path["gross_exposure"] == pytest.approx(1.4)
    assert path["borrow_cost"] > 0
    assert all(t["signal_date"] < t["date"] for t in path["trades"])
    request = json.loads((artifacts/str(run.pk)/"input.json").read_text())
    assert len(request["prices"]["values"]) == 241
    assert path["refits"][-1]["diagnostics"]["state"] == len(path["refits"])
    code,out=invoke(capsys,scope.owner,"backtest",revision.pk,"--dataset",dataset.pk,
        "--params",json.dumps({"first_holdout":first_holdout}),
        "--options",'{"mode":"fixed","lookback":30,"frequency":"weekly"}')
    assert code==0
    fixed=out["data"]["result"]["portfolio"]
    assert len(fixed["refits"])==1 and len(fixed["trades"])>2
    assert all(trade["weights"]==[1.2,-.2] for trade in fixed["trades"])
    code,out=invoke(capsys,scope.owner,"backtest",revision.pk,"--dataset",dataset.pk,
        "--options",'{"lookback":30,"frequency":"weekly"}',"--max-refits","1")
    assert code==1 and "request limit is 1" in out["error"]["message"]
    assert ResearchRun.objects.get(pk=out["error"]["run_id"]).status=="failed"
    assert out["error"]["run_url"].endswith(out["error"]["run_id"]+"/")


@pytest.mark.django_db
@pytest.mark.parametrize("source,timeout", [
    ("def run(context, params):\n    raise RuntimeError('intentional error')\n", 15),
    ("def run(context, params):\n    while True: pass\n", .15),
    ("def run(context, params):\n    return {'metrics': {}}\n", 15)])
def test_custom_errors_saved(scope, artifacts, tmp_path, capsys, source, timeout):
    revision = register_file(scope, tmp_path, source)
    code, out = invoke(capsys, scope.owner, "research", "run", revision.pk, "--timeout", timeout)
    assert code != 0
    run = ResearchRun.objects.get()
    assert run.status == "failed" and run.error and run.artifacts


@pytest.mark.django_db
def test_revision_directory_helpers_and_saved_pytest(scope, artifacts, tmp_path, capsys):
    (tmp_path/"model.py").write_text("from helper import answer\ndef run(context,params): return answer()\n")
    (tmp_path/"helper.py").write_text("def answer(): return 42\n")
    (tmp_path/"test_model.py").write_text("from helper import answer\ndef test_answer(): assert answer() == 42\n")
    (tmp_path/".env").write_text("PRIVATE_SECRET=not-for-snapshot")
    revision = research.register(scope, tmp_path, "model.py:run", "research", "Tests")
    assert ".env" not in revision.sources and "helper.py" in revision.sources
    code, out = invoke(capsys, scope.owner, "tests", "run", revision.pk)
    assert code == 0, out
    run = ResearchRun.objects.get()
    assert run.result["counts"]["tests"] == 1 and run.result["counts"]["failures"] == 0
    (tmp_path/"test_model.py").write_text("def test_fail(): assert False\n")
    bad = research.register(scope, tmp_path, "model.py:run", "research", "Failing tests")
    code, out = invoke(capsys, scope.owner, "tests", "run", bad.pk)
    assert code == 1 and out["data"]["status"] == "failed"
    assert out["data"]["result"]["counts"]["failures"] == 1


@pytest.mark.django_db
def test_idempotency_holdout_failure_and_web_gate(scope, dataset, artifacts, tmp_path, capsys, client):
    revision = register_file(scope,tmp_path,"def run(context,params): raise RuntimeError('failed after opening')\n")
    args = ["research","run",str(revision.pk),"--dataset",str(dataset.pk),"--window","holdout","--confirm-holdout"]
    assert invoke(capsys,scope.owner,"--idempotency-key","once",*args)[0] != 0
    assert ResearchRun.objects.get().holdout_claim
    code, out = invoke(capsys,scope.owner,"--idempotency-key","once",*args)
    assert code == 1 and ResearchRun.objects.count() == 1
    assert invoke(capsys,scope.owner,*args)[0] != 0 and ResearchRun.objects.count() == 1
    draft = services.training_problem(scope,dataset)
    experiment = services.solve_problem(scope,draft.name,draft.spec,draft=draft)
    with pytest.raises(ProblemError,match="reserved or opened"):
        services.save_evaluation(scope,experiment,dataset,"w","holdout",{"mode":"fixed"})
    client.force_login(scope.owner)
    page=client.get(reverse("dataset",args=[dataset.pk]))
    assert page.status_code==200 and b"opening is recorded" in page.content
    from test_data_views import options
    response=client.post(reverse("evaluate",args=[experiment.pk]),options(dataset,action="review_holdout"))
    assert response.status_code==302 and "/research/" in response.url


@pytest.mark.django_db
def test_research_views_scope_artifact_checks_and_notes(scope, guest, artifacts, tmp_path, capsys, client):
    revision = register_file(scope,tmp_path,"from core.research import ResearchResult\ndef run(c,p): return ResearchResult()\n")
    invoke(capsys,scope.owner,"research","run",revision.pk)
    run = ResearchRun.objects.get()
    client.force_login(scope.owner)
    for name, args in [("research_index",[]),("research_run",[run.pk]),("run_status",[run.pk]),("strategy_revision",[revision.pk])]:
        assert client.get(reverse(name,args=args)).status_code == 200
    assert client.get(reverse("artifact",args=[run.pk,0])).status_code == 200
    item = run.artifacts[0]; (artifacts/str(run.pk)/item["path"]).write_text("changed")
    assert client.get(reverse("artifact",args=[run.pk,0])).status_code == 409
    invoke(capsys,scope.owner,"notes","add",run.pk,"--kind","idea","--text","Investigate estimation")
    run.refresh_from_db(); assert run.notes[0]["kind"] == "idea"
    client.force_login(guest)
    assert client.get(reverse("research_run",args=[run.pk])).status_code == 404
    assert client.get(reverse("strategy_revision",args=[revision.pk])).status_code == 404
    assert client.get(reverse("artifact",args=[run.pk,0])).status_code == 404


@pytest.mark.django_db
def test_recovery_and_idempotency_conflict(scope):
    run, _ = research.begin(scope,"Test","research",{"seed":1},idempotency_key="key")
    assert research.begin(scope,"Test","research",{"seed":1},idempotency_key="key")[1] is False
    with pytest.raises(ProblemError): research.begin(scope,"Test","research",{"seed":2},idempotency_key="key")
    with pytest.raises(ProblemError,match="still running"): research.recover(run)
    run.runtime["pid"]=999999999; run.save()
    assert research.recover(run).status == "interrupted"


@pytest.mark.django_db
def test_finishing_preserves_annotations_added_during_run(scope):
    run,_=research.begin(scope,"Annotated","research",{})
    fresh=ResearchRun.objects.get(pk=run.pk)
    fresh.notes=[{"kind":"finding","text":"Written while running"}]
    fresh.save(update_fields=["notes"])
    research.finish(run,{"metrics":{}})
    run.refresh_from_db()
    assert run.notes == fresh.notes


@pytest.mark.django_db
def test_known_secret_redaction_in_child_logs(scope,artifacts,tmp_path,capsys,monkeypatch):
    secret="synthetic-secret-for-redaction-test"
    monkeypatch.setenv("TEST_PRIVATE_TOKEN",secret)
    revision=register_file(scope,tmp_path,'''import os
from core.research import ResearchResult
def run(c,p):
    print(os.environ["TEST_PRIVATE_TOKEN"])
    return ResearchResult(text=os.environ["TEST_PRIVATE_TOKEN"])
''')
    assert invoke(capsys,scope.owner,"research","run",revision.pk)[0]==0
    run=ResearchRun.objects.get()
    assert "[REDACTED]" in (artifacts/str(run.pk)/"stdout.log").read_text()
    assert run.result["text"]=="[REDACTED]"
    assert all(secret not in path.read_text(errors="replace") for path in (artifacts/str(run.pk)).rglob("*") if path.is_file())


@pytest.mark.django_db(transaction=True)
def test_two_cli_processes_share_atomic_holdout(scope,dataset,artifacts,tmp_path):
    """Real processes use the isolated test DB, never the development database."""
    import os, subprocess, sys
    from django.conf import settings
    revision=register_file(scope,tmp_path,'''from core.research import ResearchResult
def run(c,p): return ResearchResult()
''')
    database=Path(settings.DATABASES["default"]["NAME"]).resolve()
    assert database == Path(os.environ.get("LAB_TEST_DATABASE_PATH", settings.BASE_DIR / "test.sqlite3")).resolve()
    env={**os.environ,"LAB_DATABASE_PATH":str(database),"LAB_ARTIFACT_ROOT":str(artifacts)}
    command=[sys.executable,"-m","lab.cli","--owner",scope.owner.username,"research","run",str(revision.pk),
        "--dataset",str(dataset.pk),"--window","holdout","--confirm-holdout"]
    children=[subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env) for _ in range(2)]
    outputs=[child.communicate(timeout=30) for child in children]
    assert sorted(child.returncode for child in children)==[0,2],outputs
    assert ResearchRun.objects.filter(holdout_claim=True).count()==1
    assert ResearchRun.objects.get().status=="complete"


@pytest.mark.django_db(transaction=True)
def test_sigterm_stops_child_and_saves_interruption(scope,artifacts,tmp_path):
    import os, subprocess, sys, time
    from django.conf import settings
    revision=register_file(scope,tmp_path,"import time\ndef run(c,p): time.sleep(60)\n")
    env={**os.environ,"LAB_DATABASE_PATH":str(settings.DATABASES["default"]["NAME"]),"LAB_ARTIFACT_ROOT":str(artifacts)}
    child=subprocess.Popen([sys.executable,"-m","lab.cli","--owner",scope.owner.username,
        "research","run",str(revision.pk)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
    try:
        deadline=time.monotonic()+15
        run=None
        while time.monotonic()<deadline:
            run=ResearchRun.objects.first()
            if run and run.runtime.get("child_pid"): break
            time.sleep(.05)
        assert run and run.runtime.get("child_pid")
        child.terminate()
        output,_=child.communicate(timeout=10)
        assert child.returncode==130 and json.loads(output)["error"]["code"]=="interrupted"
        run.refresh_from_db()
        assert run.status=="interrupted"
        assert research.process_identity(run.runtime["child_pid"]) is None
    finally:
        if child.poll() is None:
            child.kill();child.communicate(timeout=10)
