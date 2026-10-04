from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json

import pytest
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse

from core.parser import build_problem
from core.presets import get_preset
from core.solve import solve
from lab.models import Experiment, Problem
from lab import views
from conftest import post_data

pytestmark = pytest.mark.django_db


def test_login_logout_and_authentication_required(client, guest):
    assert client.get("/").status_code == 302
    assert client.get("/problems/new/").status_code == 302
    assert client.get("/login/").status_code == 200
    assert client.post("/login/", {"username": "guest", "password": "wrong"}).status_code == 200
    assert client.post("/login/", {"username": "guest", "password": "testing-passphrase-123"}).status_code == 302
    assert client.get("/").status_code == 200
    assert client.get("/logout/").status_code == 405
    assert client.post("/logout/").status_code == 302
    assert client.get("/").status_code == 302


def test_all_presets_render(client, owner):
    client.force_login(owner)
    for name in ("min-variance", "mean-variance", "risk-cap", "signed", "least-squares", "regularized-ls", "linear-program", "socp", "cvar"):
        response = client.get("/problems/new/", {"preset": name})
        assert response.status_code == 200
        assert b"DCP verdict: passes" in response.content
    assert client.get("/problems/new/?preset=missing").status_code == 404


def test_solve_save_view_clone_and_immutable(client, owner):
    client.force_login(owner)
    response = client.post("/problems/new/", post_data())
    assert response.status_code == 302
    experiment = Experiment.objects.get()
    assert client.get(response.url).status_code == 200
    assert b"0.8" in client.get(response.url).content
    frozen = deepcopy(experiment.spec)
    response = client.post(reverse("edit", args=[experiment.problem.pk]), post_data(name="Changed name", action="save"))
    assert response.status_code == 302
    experiment.refresh_from_db()
    assert experiment.spec == frozen
    assert experiment.name == "Test problem"
    with pytest.raises(ValidationError, match="immutable"):
        experiment.save()
    assert client.get(reverse("clone", args=[experiment.pk])).status_code == 405
    response = client.post(reverse("clone", args=[experiment.pk]))
    assert response.status_code == 302
    assert Problem.objects.count() == 2
    assert client.get(response.url).status_code == 200
    assert client.get("/").status_code == 200


def test_preview_nonconvex_syntax_infeasible_and_form_errors(client, owner):
    client.force_login(owner)
    data = post_data(action="preview")
    assert client.post("/problems/new/", data).status_code == 200
    assert Experiment.objects.count() == 0
    data["action"] = "solve"
    data["expression"] = "w[0]*w[1]"
    response = client.post("/problems/new/", data)
    assert b"DCP rules failed" in response.content
    assert Experiment.objects.count() == 0
    data["expression"] = "square("
    assert b"Bad syntax" in client.post("/problems/new/", data).content
    data = post_data()
    data["constraints"] += "\nw <= -1"
    response = client.post("/problems/new/", data)
    assert response.status_code == 302
    assert b"infeasible" in client.get(response.url).content
    data["variables"] = "{"
    assert b"Enter a valid JSON" in client.post("/problems/new/", data).content
    data = post_data()
    data["action"] = "unknown"
    assert b"Unknown action" in client.post("/problems/new/", data).content
    data["action"], data["solver"] = "solve", "ECOS"
    assert client.post("/problems/new/", data).status_code == 200


def test_incompatible_solver_explained(client, owner):
    client.force_login(owner)
    response = client.post("/problems/new/", post_data(get_preset("socp"), solver="OSQP"))
    assert response.status_code == 200
    assert b"OSQP could not solve" in response.content
    assert Experiment.objects.count() == 0


def test_five_guests_isolated_and_logout_resets_workspace(guest):
    clients = [Client() for _ in range(5)]
    experiment_ids = []
    for index, browser in enumerate(clients):
        browser.force_login(guest)
        response = browser.post("/problems/new/", post_data(name=f"Guest {index}"))
        assert response.status_code == 302
        experiment_ids.append(response.url)
    assert len({str(p.workspace) for p in Problem.objects.all()}) == 5
    for index, browser in enumerate(clients):
        for other, url in enumerate(experiment_ids):
            assert browser.get(url).status_code == (200 if other == index else 404)
        assert browser.get("/admin/").status_code == 302
    p = Problem.objects.first()
    for browser in clients:
        if str(browser.session["workspace"]) != str(p.workspace):
            assert browser.post(reverse("edit", args=[p.pk]), post_data(action="save")).status_code == 404
            assert browser.post(reverse("clone", args=[p.experiment_set.first().pk])).status_code == 404
    clients[0].post("/logout/")
    clients[0].force_login(guest)
    assert clients[0].get(experiment_ids[0]).status_code == 404


def test_owner_workspace_persists_across_sessions(owner):
    first, second = Client(), Client()
    first.force_login(owner)
    second.force_login(owner)
    response = first.post("/problems/new/", post_data())
    assert second.get(response.url).status_code == 200


def test_busy_slots_and_solver_error_release_slot(client, owner, monkeypatch):
    client.force_login(owner)
    class Slots:
        released = 0
        def acquire(self, blocking):
            return False
        def release(self):
            self.released += 1
    slots = Slots()
    monkeypatch.setattr(views, "SOLVE_SLOTS", slots)
    response = client.post("/problems/new/", post_data())
    assert response.status_code == 503
    assert response["Retry-After"] == "3"
    assert Experiment.objects.count() == 0
    monkeypatch.setattr(slots, "acquire", lambda blocking: True)
    response = client.post("/problems/new/", post_data(get_preset("socp"), solver="OSQP"))
    assert response.status_code == 200
    assert slots.released == 1


def test_csrf_required(owner):
    browser = Client(enforce_csrf_checks=True)
    browser.force_login(owner)
    assert browser.post("/problems/new/", post_data()).status_code == 403


def test_untrusted_text_escaped(client, owner):
    client.force_login(owner)
    spec = get_preset("min-variance")
    spec["variables"][0]["meaning"] = "<script>alert(1)</script>"
    response = client.post("/problems/new/", post_data(spec, name="<img src=x onerror=alert(1)>"))
    rendered = client.get(response.url).content
    assert b"<script>alert(1)</script>" not in rendered
    assert b"&lt;script&gt;" in rendered
    assert b"<img src=x" not in rendered


def test_five_concurrent_pure_solves_have_independent_parameters():
    def task(index):
        spec = get_preset("min-variance")
        spec["parameters"][0]["value"] = [[.01 * (index+1), 0], [0, .04]]
        result = solve(build_problem(spec))
        return result["variables"]["w"][0]
    with ThreadPoolExecutor(max_workers=5) as pool:
        values = list(pool.map(task, range(5)))
    for index, value in enumerate(values):
        assert value == pytest.approx(.04/(.04+.01*(index+1)), abs=1e-5)


def test_json_declaration_wrong_type_not_silently_discarded(client, owner):
    client.force_login(owner)
    data = post_data()
    data["parameters"] = "{}"
    response = client.post("/problems/new/", data)
    assert response.status_code == 200
    assert b"parameters must be a list" in response.content
    assert Experiment.objects.count() == 0


def test_initial_json_fields_are_arrays_not_encoded_strings(client, owner):
    client.force_login(owner)
    response = client.get("/problems/new/")
    form = response.context["form"]
    assert isinstance(json.loads(form["variables"].value()), list)
    assert isinstance(json.loads(form["parameters"].value()), list)
