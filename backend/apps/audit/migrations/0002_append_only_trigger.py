from django.db import migrations

from common.db import APPEND_ONLY_FUNCTION, append_only_sql, drop_append_only_sql


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]

    operations = [
        migrations.RunSQL(APPEND_ONLY_FUNCTION, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(append_only_sql("audit_auditlog", "actor_id"), reverse_sql=drop_append_only_sql("audit_auditlog")),
    ]
