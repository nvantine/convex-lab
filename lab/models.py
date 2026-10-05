"""Editable drafts, frozen solver evidence, price snapshots, and evaluations."""
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
    kind = models.CharField(max_length=12, default='single', choices=[('single', 'Single'), ('frontier', 'Frontier'), ('chosen', 'Chosen')])
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='chosen_solutions')
    point_index = models.PositiveIntegerField(null=True, blank=True)
    result = models.JSONField()
    digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=['parent', 'point_index'], condition=models.Q(kind='chosen'), name='one_chosen_snapshot_per_point')]

    def save(self, *args, **kwargs):
        if type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Experiments are immutable. Clone the problem to make a new experiment.")
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Dataset(models.Model):
    """An immutable adjusted-price snapshot. The full payload stays on the server."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    workspace = models.UUIDField(db_index=True)
    name = models.CharField(max_length=120)
    source = models.CharField(max_length=12)
    prices = models.JSONField()
    provenance = models.JSONField()
    digest = models.CharField(max_length=64, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Datasets are immutable. Fetch a new snapshot to change data.')
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Evaluation(models.Model):
    """A frozen historical evaluation; one final opening per data fingerprint."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    workspace = models.UUIDField(db_index=True)
    experiment = models.ForeignKey(Experiment, on_delete=models.PROTECT)
    dataset = models.ForeignKey(Dataset, on_delete=models.PROTECT)
    dataset_digest = models.CharField(max_length=64)
    window = models.CharField(max_length=12, choices=[('validation','Validation'),('holdout','Final holdout')])
    variable = models.CharField(max_length=40)
    result = models.JSONField()
    digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['owner','workspace','dataset_digest'],
            condition=models.Q(window='holdout'), name='one_final_holdout_per_snapshot')]

    def save(self, *args, **kwargs):
        if type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Evaluations are immutable. Run a new validation evaluation to change assumptions.')
        return super().save(*args, **kwargs)


class FetchRequest(models.Model):
    """Resumable browser batches and a private cache; finalized datasets stay frozen."""
    id = models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    workspace = models.UUIDField(db_index=True)
    name = models.CharField(max_length=120)
    source = models.CharField(max_length=12)
    symbols = models.JSONField()
    start = models.DateField()
    end = models.DateField()
    batch_size = models.PositiveSmallIntegerField(default=5)
    prefer_cache = models.BooleanField(default=True)
    refresh_daily = models.BooleanField(default=False)
    series = models.JSONField(default=dict)
    provenance = models.JSONField(default=dict)
    errors = models.JSONField(default=dict)
    message = models.TextField(blank=True)
    dataset = models.ForeignKey(Dataset,null=True,blank=True,on_delete=models.PROTECT)
    busy_until = models.DateTimeField(null=True,blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True,blank=True)

    class Meta:
        ordering = ['-updated_at']
