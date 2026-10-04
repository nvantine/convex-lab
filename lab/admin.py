from django.contrib import admin
from lab.models import Experiment, Problem

admin.site.register(Problem)


@admin.register(Experiment)
class ExperimentAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "created_at")
    readonly_fields = tuple(f.name for f in Experiment._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
