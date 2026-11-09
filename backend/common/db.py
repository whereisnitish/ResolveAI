"""Database-level guards.

The audit log and usage ledger are append-only *in the database*, not just in the
ORM: Postgres triggers reject UPDATE/DELETE, so a bug, a raw SQL statement or a
compromised app path cannot rewrite history. Two narrow exceptions:

* audit_auditlog.actor_id may be set to NULL (ON DELETE SET NULL when a user is
  erased — the trail keeps actor_email).
* Deletion is allowed inside `allow_purge()`, which sets a transaction-local flag.
  Only tenant erasure / retention jobs may use it, and they must audit it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from django.db import connection, transaction

PURGE_FLAG = "resolveai.allow_purge"


@contextmanager
def allow_purge() -> Iterator[None]:
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config(%s, 'on', true)", [PURGE_FLAG])
        try:
            yield
        finally:
            # Reset explicitly: when nested in an outer transaction, SET LOCAL would
            # otherwise stay in force until that outer transaction ends.
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config(%s, '', true)", [PURGE_FLAG])


APPEND_ONLY_FUNCTION = f"""
CREATE OR REPLACE FUNCTION resolveai_append_only() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF coalesce(current_setting('{PURGE_FLAG}', true), '') = 'on' THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION '% is append-only: DELETE rejected', TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
    END IF;
    -- UPDATE: the only permitted change is clearing a nullable actor reference.
    IF TG_ARGV[0] IS NOT NULL AND TG_ARGV[0] <> '' THEN
        IF (to_jsonb(NEW) - TG_ARGV[0]) = (to_jsonb(OLD) - TG_ARGV[0])
           AND (to_jsonb(NEW) ->> TG_ARGV[0]) IS NULL THEN
            RETURN NEW;
        END IF;
    END IF;
    RAISE EXCEPTION '% is append-only: UPDATE rejected', TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;
"""


def append_only_sql(table: str, nullable_column: str = "") -> str:
    return f"""
DROP TRIGGER IF EXISTS {table}_append_only ON {table};
CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table}
    FOR EACH ROW EXECUTE FUNCTION resolveai_append_only('{nullable_column}');
"""


def drop_append_only_sql(table: str) -> str:
    return f"DROP TRIGGER IF EXISTS {table}_append_only ON {table};"
