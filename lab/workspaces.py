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


def ensure_guest_datasets(request):
    """Give each guest session its own copies of the configured frozen snapshots."""
    if request.user.username != settings.GUEST_USERNAME or not settings.LAB_GUEST_STARTER_DATASET_IDS:
        return
    configured = [str(value) for value in settings.LAB_GUEST_STARTER_DATASET_IDS]
    if request.session.get("guest_starter_dataset_ids") == configured:
        return
    from lab.models import Dataset

    workspace = workspace_for(request)
    starters = list(Dataset.objects.filter(
        pk__in=settings.LAB_GUEST_STARTER_DATASET_IDS, owner__is_staff=True,
    ).values_list("id", "digest"))
    existing = set(Dataset.objects.filter(
        owner=request.user, workspace=workspace, digest__in=[digest for _, digest in starters],
    ).values_list("digest", flat=True))
    missing_ids = [dataset_id for dataset_id, digest in starters if digest not in existing]
    for source in Dataset.objects.filter(pk__in=missing_ids):
        Dataset.objects.get_or_create(
            owner=request.user, workspace=workspace, digest=source.digest,
            defaults={"name": source.name, "source": source.source,
                      "prices": source.prices, "provenance": source.provenance},
        )
    request.session["guest_starter_dataset_ids"] = configured
