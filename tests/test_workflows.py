"""Grid determinism, validation evidence, reporting, and deliberate sharing."""
import json
from pathlib import Path
import pytest
from django.urls import reverse
from core.workflows import grid_trials, apply_trial, summarize_trials
from core.parser import ProblemError
from lab import research, services
from lab.models import ResearchRun
from test_research import scope, dataset, artifacts, register_file
from test_cli import invoke


def test_grid_is_deterministic_and_parameters_editable():
    grid = {"params.alpha":[.1,1], "options.cost_bps":[0,10]}
    trials = list(grid_trials(grid,[42,43]))
    assert len(trials) == 8 and trials == list(grid_trials(grid,[42,43]))
    assert trials[0]["changes"] == {"options.cost_bps":0,"params.alpha":.1}
    base = {"spec":{"parameters":[{"name":"gamma","value":1}]},"params":{},"options":{}}
    assert apply_trial(base,{"changes":{"parameters.gamma":4}})["spec"]["parameters"][0]["value"] == 4
    assert base["spec"]["parameters"][0]["value"] == 1
    with pytest.raises(ProblemError): apply_trial(base,{"changes":{"parameters.missing":2}})


@pytest.mark.parametrize("grid,seeds,maximum", [
    ({"bad":[1]},[42],100),({"params.x":[]},[42],100),({},[],100),({},[42,42],100),
    ({},[True],100),({"params.x":[1,2]},[42],1)])
def test_invalid_grid(grid,seeds,maximum):
    with pytest.raises(ProblemError): list(grid_trials(grid,seeds,maximum))


def test_ranking_excludes_failures_and_partial_and_preserves_evidence():
    def trial(i,status,value,unit="ratio"):
        return {"id":str(i),"status":status,"seed":42,"changes":{"params.x":i},
                "result":{"metrics":{"score":{"value":value,"unit":unit}}}}
    result = summarize_trials([trial(1,"complete",1),trial(2,"partial",99),trial(3,"failed",None),
                               trial(4,"complete",2)],"score","maximize")
    assert result["summary"]["best_run_id"] == "4"
    assert result["summary"]["ranked"] == 2
    assert len(result["tables"][0]["rows"]) == 4
    assert summarize_trials([trial(1,"complete",1),trial(2,"complete",2)],"score","minimize")["summary"]["best_run_id"] == "1"
    with pytest.raises(ProblemError):
        summarize_trials([trial(1,"complete",1),trial(2,"complete",2,"percent")],"score","maximize")


@pytest.mark.django_db
def test_python_sweep_multiple_seeds_failures_and_idempotency(scope,artifacts,tmp_path,capsys):
    revision = register_file(scope,tmp_path,'''from core.research import ResearchResult
def run(c,p):
    if p["alpha"] == -1: raise ValueError("deliberate invalid candidate")
    return ResearchResult(metrics={"score":{"value":p["alpha"]+float(c.rng.normal()),"unit":"ratio"}})
''')
    args = ["sweep",str(revision.pk),"--grid",'{"params.alpha":[-1,1,2]}',"--seeds","[42,43]",
            "--metric","score","--timeout","60"]
    code,out = invoke(capsys,scope.owner,"--idempotency-key","campaign",*args)
    assert code == 1 and out["data"]["status"] == "partial"
    parent = ResearchRun.objects.get(kind="sweep")
    assert parent.children.count() == 6
    assert parent.result["summary"]["ranked"] == 4
    assert parent.children.filter(status="failed").count() == 2
    assert not ResearchRun.objects.filter(holdout_claim=True).exists()
    invoke(capsys,scope.owner,"--idempotency-key","campaign",*args)
    assert ResearchRun.objects.count() == 7


@pytest.mark.django_db
def test_symbolic_cost_sweep_and_replay(scope,dataset,artifacts,capsys):
    draft = services.training_problem(scope,dataset)
    code,out = invoke(capsys,scope.owner,"sweep",draft.pk,"--dataset",dataset.pk,
        "--grid",'{"options.cost_bps":[0,20]}',"--options",'{"lookback":30}',"--timeout","60")
    assert code == 0,out
    parent = ResearchRun.objects.get(kind="sweep")
    assert parent.children.count() == 2
    assert all(r.evaluation_id and r.experiment_id for r in parent.children.all())
    children = list(parent.children.order_by("created_at"))
    assert children[0].result["portfolio"]["metrics"]["total_return"] > children[1].result["portfolio"]["metrics"]["total_return"]
    _,out = invoke(capsys,scope.owner,"runs","replay",children[0].pk)
    assert out["data"]["result"]["portfolio"]["wealth"] == children[0].result["portfolio"]["wealth"]


@pytest.mark.django_db
def test_comparison_report_publication_and_private_artifacts(scope,guest,artifacts,capsys,client):
    def saved(name,unit,value):
        run,_=research.begin(scope,name,"research",{"seed":42})
        research.finish(run,{"provenance":"script-reported","metrics":{"score":{"value":value,"unit":unit}},
            "text":"Selected findings","equations":[r"x^2"],"charts":[],"tables":[]})
        return run
    a,b=saved("First","ratio",1),saved("Second","percent",2)
    code,out=invoke(capsys,scope.owner,"compare",a.pk,b.pk)
    assert code==0,out
    assert len(out["data"]["metrics"])==3  # Status and two different-unit rows.
    assert "Metric units" in out["data"]["differences"]
    code,out=invoke(capsys,scope.owner,"report",a.pk,b.pk,"--text","Investigate units first.","--title","Agent findings")
    assert code==0
    report=ResearchRun.objects.get(kind="report")
    assert "Investigate units" in report.result["text"] and report.result["tables"]
    invoke(capsys,scope.owner,"publish",report.pk)
    report.refresh_from_db();assert report.published
    client.force_login(guest)
    assert client.get(reverse("research_run",args=[report.pk])).status_code==404
    shared=client.get(reverse("gallery_run",args=[report.pk]))
    assert shared.status_code==200 and b"Agent findings" in shared.content
    assert b"Saved artifacts" not in shared.content and b"Reproducibility details" not in shared.content
    assert client.post(reverse("publication",args=[report.pk]),{"action":"unpublish"}).status_code==404
    invoke(capsys,scope.owner,"unpublish",report.pk)
    assert client.get(reverse("gallery_run",args=[report.pk])).status_code==404
    client.force_login(scope.owner)
    assert client.post(reverse("publication",args=[a.pk]),{"action":"publish"}).status_code==302
    assert client.get(reverse("publication",args=[a.pk])).status_code==405


@pytest.mark.django_db
def test_mixed_backtest_comparison(scope,dataset,artifacts,client):
    draft=services.training_problem(scope,dataset)
    experiment=services.solve_problem(scope,draft.name,draft.spec,draft=draft)
    evaluation=services.save_evaluation(scope,experiment,dataset,"w","validation",{"mode":"fixed","frequency":"weekly"})
    run,_=research.begin(scope,"Python-style comparison","backtest",{},dataset,"validation")
    from core.research import portfolio_report
    research.finish(run,portfolio_report(evaluation.result))
    client.force_login(scope.owner)
    response=client.get("/compare/",{"evaluation":str(evaluation.pk),"run":str(run.pk)})
    assert response.status_code==200
    assert len(response.context["charts"][0]["figure"]["data"])==4
    assert len(response.context["records"])==2
    assert client.get("/compare/",{"run":[str(run.pk)]*7}).status_code==400
