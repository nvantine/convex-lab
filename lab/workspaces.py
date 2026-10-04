"""The shared guest username does not imply shared mutable work."""
import uuid
from django.conf import settings


def workspace_for(request):
    if request.user.is_staff and request.user.username != settings.GUEST_USERNAME:
        return uuid.uuid5(uuid.NAMESPACE_URL, f"convex-lab-owner:{request.user.pk}")
    if "workspace" not in request.session:
        request.session["workspace"] = str(uuid.uuid4())
    return uuid.UUID(request.session["workspace"])


def scoped(model, request):
    return model.objects.filter(owner=request.user, workspace=workspace_for(request))
