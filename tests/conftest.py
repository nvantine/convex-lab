import json
import pytest
from django.contrib.auth import get_user_model
from core.presets import get_preset


@pytest.fixture
def owner(db):
    return get_user_model().objects.create_user(username="test-owner", password="testing-passphrase-123", is_staff=True)


@pytest.fixture
def guest(db):
    return get_user_model().objects.create_user(username="guest", password="testing-passphrase-123")


def post_data(spec=None, action="solve", name="Test problem", solver="CLARABEL"):
    spec = spec or get_preset("min-variance")
    return {"name": name, "variables": json.dumps(spec["variables"]), "parameters": json.dumps(spec["parameters"]),
            "sense": spec["objective"]["sense"], "expression": spec["objective"]["expression"],
            "constraints": "\n".join(spec["constraints"]), "action": action, "solver": solver}
