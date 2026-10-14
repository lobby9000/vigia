"""Test runner that loads the shared SQL schema into Django's test database.

Django creates a fresh test database and runs migrations, but migrations skip
``managed = False`` models: their tables would be missing. After the normal
setup, this runner executes the same database/*.sql files that Docker runs in
production, so the tests exercise the real schema (constraints, views,
materialized view and all).
"""

from pathlib import Path

from django.conf import settings
from django.db import connection
from django.test.runner import DiscoverRunner

SCHEMA_FILES = ("01_schema.sql", "02_views.sql", "03_seed_reference.sql")


class SharedSchemaTestRunner(DiscoverRunner):
    def setup_databases(self, **kwargs):
        old_config = super().setup_databases(**kwargs)
        sql_dir = Path(settings.SHARED_SQL_DIR)
        with connection.cursor() as cursor:
            for name in SCHEMA_FILES:
                cursor.execute((sql_dir / name).read_text())
        return old_config
