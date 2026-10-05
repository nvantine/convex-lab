"""The shared guest username does not imply shared mutable work."""
import uuid
from django.conf import settings
from dataclasses import dataclass


@dataclass(frozen=True)
class Scope:
    """The same explicit owner/workspace boundary for requests and CLI calls."""
    owner: object
    workspace: uuid.UUID

    def query(self, model):
        return model.objects.filter(owner=self.owner, workspace=self.workspace)


def owner_workspace(user):
    return uuid.uuid5(uuid.NAMESPACE_URL, f"convex-lab-owner:{user.pk}")


def request_scope(request):
    return Scope(request.user, workspace_for(request))


def workspace_for(request):
    if request.user.is_staff and request.user.username != settings.GUEST_USERNAME:
        return owner_workspace(request.user)
    if "workspace" not in request.session:
        request.session["workspace"] = str(uuid.uuid4())
    return uuid.UUID(request.session["workspace"])


def scoped(model, request):
    return model.objects.filter(owner=request.user, workspace=workspace_for(request))
