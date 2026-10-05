"""Reserve historical holdout openings in the shared web/CLI ledger."""
from django.db import migrations


def import_holdouts(apps, schema_editor):
    Evaluation = apps.get_model("lab", "Evaluation")
    ResearchRun = apps.get_model("lab", "ResearchRun")
    for item in Evaluation.objects.filter(window="holdout").iterator():
        ResearchRun.objects.get_or_create(owner_id=item.owner_id, workspace=item.workspace,
            dataset_digest=item.dataset_digest, holdout_claim=True, defaults={
                "name":"Existing final holdout", "kind":"backtest", "status":"complete",
                "dataset_id":item.dataset_id, "evaluation_id":item.pk, "experiment_id":item.experiment_id,
                "window":"holdout", "config":{"imported":True}, "result":item.result,
                "finished_at":item.created_at})


class Migration(migrations.Migration):
    dependencies = [("lab", "0005_strategyrevision_researchrun")]
    operations = [migrations.RunPython(import_holdouts, migrations.RunPython.noop)]
