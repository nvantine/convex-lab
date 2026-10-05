"""Command discovery, JSON input, failure exit codes, and frozen exports."""
import json
from pathlib import Path
import pytest
from core.presets import get_preset
from lab.models import Problem, ResearchRun, Dataset
from lab import research, services
from test_research import scope, artifacts, dataset, register_file
from test_cli import invoke


@pytest.mark.django_db
def test_configuration_discovery_and_input_files(scope,capsys,tmp_path,settings):
    settings.BASE_DIR=tmp_path
    assert invoke(capsys,scope.owner,"config",scope.owner.username,"--site-url","http://localhost:8020")[0]==0
    assert json.loads((tmp_path/".local/cli.json").read_text())["owner"]==scope.owner.username
    assert invoke(capsys,scope.owner,"whoami")[1]["data"]["workspace"]==str(scope.workspace)
    assert isinstance(invoke(capsys,scope.owner,"doctor")[1]["data"]["alpaca_credentials_loaded"],bool)
    capabilities=invoke(capsys,scope.owner,"capabilities")[1]["data"]
    assert {"research","sweep","report","publish"} <= set(capabilities["commands"])
    assert capabilities["schemas"]["research_result"]["type"]=="object"
    preset=invoke(capsys,scope.owner,"presets","min-variance")[1]["data"]
    assert preset["variables"]
    request=tmp_path/"request.json"
    request.write_text(json.dumps({"argv":["problems","create","--preset","min-variance","--name","From JSON"]}))
    assert invoke(capsys,scope.owner,"--input",request)[0]==0
    params=tmp_path/"options.json";params.write_text('{"frequency":"weekly"}')
    from lab.cli import object_json
    assert object_json("@"+str(params))=={"frequency":"weekly"}


@pytest.mark.django_db
def test_edit_clone_latex_and_infeasible_status(scope,capsys,tmp_path):
    draft=services.save_problem(scope,"Original",get_preset("min-variance"))
    _,copy=invoke(capsys,scope.owner,"problems","clone",draft.pk)
    assert copy["data"]["id"]!=str(draft.pk)
    spec=get_preset("min-variance");spec["constraints"] += ["w[0] <= 0.6"]
    source=tmp_path/"edited.json";source.write_text(json.dumps(spec))
    assert invoke(capsys,scope.owner,"problems","update",draft.pk,"--name","Edited","--file",source)[0]==0
    assert len(Problem.objects.get(pk=draft.pk).spec["constraints"])==3
    spec["constraints"] += ["w[0] >= 2"]
    source.write_text(json.dumps(spec))
    invoke(capsys,scope.owner,"problems","update",draft.pk,"--name","Infeasible","--file",source)
    code,out=invoke(capsys,scope.owner,"solve",draft.pk)
    assert code==1 and out["data"]["status"]=="failed"
    assert ResearchRun.objects.get().result["metrics"]["objective_value"]["value"] is None
    code,replayed=invoke(capsys,scope.owner,"runs","replay",out["data"]["run_id"])
    assert code==1 and replayed["data"]["status"]=="failed"
    assert replayed["data"]["result"]["metrics"]["objective_value"]["value"] is None
    spec=get_preset("min-variance")
    spec["objective"]["expression"]=r"w^\top\Sigma w"
    spec["constraints"]=[r"\sum(w)=1",r"w\ge 0"]
    source.write_text(json.dumps(spec))
    assert invoke(capsys,scope.owner,"problems","create","--name","LaTeX","--file",source,"--language","latex")[0]==0


@pytest.mark.django_db
def test_frontier_choose_and_replay(scope,capsys):
    from core.presets import PRESETS
    key=next(k for k in PRESETS if get_preset(k).get("criteria"))
    draft=services.save_problem(scope,"Frontier",get_preset(key))
    code,out=invoke(capsys,scope.owner,"frontier",draft.pk,"--options",'{"samples":4}')
    assert code==0,out
    index=out["data"]["result"]["points"][0]["id"]
    code,chosen=invoke(capsys,scope.owner,"choose",out["data"]["id"],"--point",index)
    assert code==0 and chosen["data"]["result"]["verified_optimal"]


@pytest.mark.django_db
def test_export_logs_and_runtime_mismatch(scope,artifacts,tmp_path,capsys):
    revision=register_file(scope,tmp_path,"from core.research import ResearchResult\ndef run(c,p): print('evidence'); return ResearchResult()\n")
    _,out=invoke(capsys,scope.owner,"research","run",revision.pk)
    run=ResearchRun.objects.get()
    assert invoke(capsys,scope.owner,"runs","show",run.pk,"--logs")[1]["data"]["logs"]["stdout.log"]=="evidence\n"
    destination=tmp_path/"export"
    code,out=invoke(capsys,scope.owner,"runs","export",run.pk,"--output",destination)
    assert code==0 and (destination/"run.json").exists()
    assert (destination/"source/model.py").exists()
    assert invoke(capsys,scope.owner,"runs","export",run.pk,"--output",destination)[0]!=0
    # Simulate an old dependency environment; replay must require acknowledgment.
    ResearchRun.objects.filter(pk=run.pk).update(runtime={**run.runtime,"python":"old"})
    assert invoke(capsys,scope.owner,"runs","replay",run.pk)[0]==2
    assert invoke(capsys,scope.owner,"runs","replay",run.pk,"--allow-version-mismatch")[0]==0


@pytest.mark.django_db
def test_holdout_export_is_explicit_and_consumed(scope,dataset,capsys):
    assert invoke(capsys,scope.owner,"datasets","export",dataset.pk,"--window","holdout")[0]==2
    code,out=invoke(capsys,scope.owner,"datasets","export",dataset.pk,"--window","holdout","--confirm-holdout")
    assert code==0 and len(out["data"]["prices"]["values"])==301
    assert ResearchRun.objects.get().holdout_claim
    assert invoke(capsys,scope.owner,"datasets","export",dataset.pk,"--window","holdout","--confirm-holdout")[0]==2


@pytest.mark.django_db
def test_partial_provider_fetch_is_saved_and_retryable(scope,capsys,monkeypatch):
    from lab import fetching
    from core.parser import ProblemError
    from test_data import synthetic_frame
    def provider(source,symbols,start,end,seconds):
        if symbols==["AGG"]: raise ProblemError("Temporary provider failure")
        return synthetic_frame(tuple(symbols)),{"provider":source,"adjustment":"all","feed":"iex"}
    monkeypatch.setattr(fetching,"fetch_prices",provider)
    code,out=invoke(capsys,scope.owner,"datasets","fetch","--source","alpaca","--symbols","SPY,AGG",
        "--start","2023-01-01","--end","2024-03-01","--batch-size","1")
    assert code==1 and out["data"]["status"]=="partial" and out["data"]["completed"]==1
    code,out=invoke(capsys,scope.owner,"datasets","resume",out["data"]["id"],"--save-available")
    # Failed AGG remains reported; a partial universe is an explicit choice.
    assert out["data"]["dataset"]["id"] and Dataset.objects.get().prices["symbols"]==["SPY"]


@pytest.mark.django_db
def test_cli_solve_comparison_flags_actual_problem_constraints(scope,capsys):
    original=get_preset("min-variance")
    draft=services.save_problem(scope,"Original",original)
    _,first=invoke(capsys,scope.owner,"solve",draft.pk)
    original["constraints"] += ["w[0] <= 0.6"]
    changed=services.save_problem(scope,"Changed cap",original)
    _,second=invoke(capsys,scope.owner,"solve",changed.pk)
    code,comparison=invoke(capsys,scope.owner,"compare",first["data"]["run_id"],second["data"]["run_id"])
    assert code==0
    assert "Constraints" in comparison["data"]["differences"]
    assert "Problem fingerprint" in comparison["data"]["differences"]
