from django.contrib.postgres.operations import CreateExtension
from django.db import migrations


class Migration(migrations.Migration):
    """Enable extensions needed platform-wide.

    - vector: pgvector for knowledge-chunk embeddings (Phase 3).
    - citext/pg_trgm: case-insensitive identifiers and fuzzy search.
    """

    initial = True
    dependencies: list = []

    operations = [
        CreateExtension("vector"),
        CreateExtension("citext"),
        CreateExtension("pg_trgm"),
    ]
