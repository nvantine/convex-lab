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


def multi_data(key='return-risk', **changes):
    from lab.forms import initial_from_spec
    values = initial_from_spec('Frontier test', get_preset(key), 'expression')
    values.update({'action':'solve', 'samples':8, 'normalize':'on'})
    for field in ('variables','parameters','criteria'):
        values[field] = json.dumps(values[field])
    values.update(changes)
    return {k:v for k,v in values.items() if v is not None}


@pytest.mark.parametrize('method', ['weighted','epsilon'])
def test_frontier_inspect_choose_clone_and_repeat_selection(client, owner, method):
    client.force_login(owner)
    response = client.post('/problems/new/', multi_data(method=method))
    assert response.status_code == 302
    frontier = Experiment.objects.get(kind='frontier')
    assert client.get(response.url).status_code == 200
    point = frontier.result['points'][0]
    url = reverse('point', args=[frontier.pk, point['id']])
    rendered = client.get(url)
    assert rendered.status_code == 200
    assert b'How this point was produced' in rendered.content
    assert b'Save as chosen solution' in rendered.content
    assert client.get(reverse('choose', args=[frontier.pk])).status_code == 405
    assert client.post(reverse('choose', args=[frontier.pk]), {'point_index':999}).status_code == 400
    assert client.post(reverse('choose', args=[frontier.pk]), {'point_index':'bad'}).status_code == 400
    assert client.get(reverse('point', args=[frontier.pk,999])).status_code == 404
    chosen = client.post(reverse('choose', args=[frontier.pk]), {'point_index':point['id']})
    assert chosen.status_code == 302
    assert client.get(chosen.url).status_code == 200
    assert client.post(reverse('choose', args=[frontier.pk]), {'point_index':point['id']}).url == chosen.url
    child = Experiment.objects.get(kind='chosen')
    assert child.parent == frontier
    assert child.spec == point['solved_spec']
    assert child.result['selection']['generator'] == point['generator']
    with pytest.raises(ValidationError):
        child.save()
    clone = client.post(reverse('clone', args=[child.pk]))
    assert client.get(clone.url).status_code == 200
    cloned_draft = Problem.objects.exclude(pk=frontier.problem_id).get()
    assert 'criteria' not in cloned_draft.spec
    assert cloned_draft.spec == child.spec


@pytest.mark.parametrize('key', ['return-risk-turnover','four-criteria','least-squares-tradeoff'])
def test_additional_multicriterion_views(client, owner, key):
    client.force_login(owner)
    assert b'DCP verdict: passes' in client.get('/problems/new/', {'preset':key}).content
    response = client.post('/problems/new/', multi_data(key))
    assert response.status_code == 302
    assert client.get(response.url).status_code == 200


def test_frontier_scoped_to_guest_workspace(guest):
    first, other = Client(), Client()
    first.force_login(guest)
    other.force_login(guest)
    response = first.post('/problems/new/', multi_data())
    assert response.status_code == 302
    frontier = Experiment.objects.get()
    assert other.get(response.url).status_code == 404
    assert other.get(reverse('point', args=[frontier.pk,0])).status_code == 404
    assert other.post(reverse('choose', args=[frontier.pk]), {'point_index':0}).status_code == 404


def test_latex_default_edit_source_and_notation_switch(client, owner):
    client.force_login(owner)
    response = client.get('/problems/new/')
    assert response.context['form']['source_language'].value() == 'latex'
    assert r'\Sigma' in response.context['form']['expression'].value()
    data = post_data(action='to_latex')
    converted = client.post('/problems/new/', data)
    form = converted.context['form']
    assert form['source_language'].value() == 'latex'
    data.update(source_language='latex', expression=form['expression'].value(), constraints=form['constraints'].value(), action='save')
    draft_response = client.post('/problems/new/', data)
    assert draft_response.status_code == 302
    draft = Problem.objects.get()
    assert draft.spec['input']['objective']['expression'] == data['expression']
    assert client.get(draft_response.url).context['form']['expression'].value() == data['expression']
    data['action'] = 'to_expression'
    converted = client.post(draft_response.url, data)
    assert converted.context['form']['source_language'].value() == 'expression'
    assert 'quad_form' in converted.context['form']['expression'].value()
    data.update(action='solve', expression=r'\input{secrets}')
    bad = client.post('/problems/new/', data)
    assert bad.status_code == 200
    assert b'LaTeX input' in bad.content
    assert Experiment.objects.count() == 0


def test_multicriterion_validation_messages(client, owner):
    client.force_login(owner)
    response = client.post('/problems/new/', multi_data(samples=51))
    assert b'Sample budget must be' in response.content
    assert Experiment.objects.count() == 0
    response = client.post('/problems/new/', multi_data(criteria='[]'))
    assert b'Declare between 2' in response.content
    spec = get_preset('return-risk')
    spec['criteria'][1]['expression'] = 'square(w[0])'
    response = client.post('/problems/new/', multi_data(criteria=json.dumps(spec['criteria'])))
    assert b'DCP rules failed' in response.content
    assert b'Criterion 2 failed' in response.content
    assert Experiment.objects.count() == 0


def test_old_snapshot_math_rerendered_without_altering_saved_evidence(client, owner):
    client.force_login(owner)
    response = client.post('/problems/new/', post_data())
    experiment = Experiment.objects.get()
    old_preview = deepcopy(experiment.preview)
    old_preview['objective']['latex'] = 'old Python looking math'
    Experiment.objects.filter(pk=experiment.pk).update(preview=old_preview)
    rendered = client.get(response.url)
    assert b'old Python looking math' not in rendered.content
    assert r'\Sigma'.encode() in rendered.content
    experiment.refresh_from_db()
    assert experiment.preview == old_preview
