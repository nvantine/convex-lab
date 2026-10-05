"""CLI commands use the same owner workspace and snapshots as the website."""
import json
from urllib.parse import urlsplit
import pytest
from lab.cli import main
from lab.models import Experiment, Dataset, Evaluation
from lab.workspaces import Scope, owner_workspace
from core.data import aligned_prices
from test_data import synthetic_frame

pytestmark = pytest.mark.django_db


def invoke(capsys, owner, *args):
    code = main(["--owner", owner.username, *map(str, args)])
    output = json.loads(capsys.readouterr().out)
    return code, output


def test_cli_problem_solve_visible_on_site(owner, client, capsys):
    code, out = invoke(capsys, owner, "problems", "create", "--preset", "min-variance", "--name", "CLI math")
    assert code == 0
    pk = out["data"]["id"]
    code, out = invoke(capsys, owner, "problems", "check", pk)
    assert code == 0 and out["data"]["is_dcp"]
    code, out = invoke(capsys, owner, "solve", pk)
    assert code == 0 and out["data"]["result"]["verified_optimal"]
    client.force_login(owner)
    assert b"CLI math" in client.get("/").content
    assert client.get(urlsplit(out["data"]["url"]).path).status_code == 200
    assert Experiment.objects.get().workspace == owner_workspace(owner)


def test_cli_scope_input_errors_and_dcp(owner, guest, capsys, tmp_path):
    assert invoke(capsys, guest, "whoami")[0] == 2
    assert invoke(capsys, owner, "problems", "show", "bad-id")[0] == 2
    assert invoke(capsys, owner, "not-a-command")[0] == 2
    from core.presets import get_preset
    spec = get_preset("min-variance")
    spec["objective"]["expression"] = "-quad_form(w, Sigma)"
    path = tmp_path / "nonconvex.json"; path.write_text(json.dumps(spec))
    _, out = invoke(capsys, owner, "problems", "create", "--file", path, "--name", "Nonconvex")
    assert invoke(capsys, owner, "problems", "check", out["data"]["id"])[1]["data"]["is_dcp"] is False
    assert invoke(capsys, owner, "solve", out["data"]["id"])[0] == 2


def test_cli_training_backtest_and_holdout_confirmation(owner, capsys):
    scope = Scope(owner, owner_workspace(owner))
    payload, _ = aligned_prices(synthetic_frame(), ["SPY", "AGG"])
    dataset = Dataset.objects.create(owner=owner, workspace=scope.workspace, name="Synthetic", source="synthetic",
                                    prices=payload, provenance={}, digest="synthetic-data")
    _, out = invoke(capsys, owner, "problems", "create", "--dataset", dataset.pk, "--name", "Training")
    _, solved = invoke(capsys, owner, "solve", out["data"]["id"])
    code, out = invoke(capsys, owner, "backtest", solved["data"]["id"], "--dataset", dataset.pk,
                       "--options", '{"lookback":30}')
    assert code == 0 and out["data"]["result"]["portfolio"]["status"] == "complete"
    assert Evaluation.objects.count() == 1
    assert invoke(capsys, owner, "backtest", solved["data"]["id"], "--dataset", dataset.pk, "--window", "holdout")[0] == 2
    _, out = invoke(capsys, owner, "datasets", "export", dataset.pk)
    assert len(out["data"]["prices"]["values"]) == 241


def test_cli_fetch_mocked_batches(owner, capsys, monkeypatch):
    from lab import fetching
    def provider(source, symbols, start, end, seconds):
        return synthetic_frame(tuple(symbols)), {"provider":source, "feed":"iex", "adjustment":"all"}
    monkeypatch.setattr(fetching, "fetch_prices", provider)
    code, out = invoke(capsys, owner, "datasets", "fetch", "--source", "alpaca", "--symbols", "SPY,AGG",
                       "--start", "2023-01-01", "--end", "2024-03-01", "--batch-size", "1")
    assert code == 0 and out["data"]["completed"] == 2 and out["data"]["dataset"]
