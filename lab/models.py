"""Two small storage models: mutable drafts and frozen solver evidence."""
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Problem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    workspace = models.UUIDField(db_index=True)
    name = models.CharField(max_length=120)
    spec = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.name


class Experiment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    workspace = models.UUIDField(db_index=True)
    problem = models.ForeignKey(Problem, on_delete=models.PROTECT)
    name = models.CharField(max_length=120)
    spec = models.JSONField()
    preview = models.JSONField()
    result = models.JSONField()
    digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Experiments are immutable. Clone the problem to make a new experiment.")
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name
