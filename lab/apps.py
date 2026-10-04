from django.apps import AppConfig
from django.db.backends.signals import connection_created


def configure_sqlite(sender, connection, **kwargs):
    if connection.vendor == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode=WAL")


class LabConfig(AppConfig):
    name = "lab"

    def ready(self):
        connection_created.connect(configure_sqlite, dispatch_uid="lab.sqlite.wal")
