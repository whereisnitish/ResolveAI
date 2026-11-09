from django.db import migrations

from common.db import APPEND_ONLY_FUNCTION, append_only_sql, drop_append_only_sql


class Migration(migrations.Migration):
    dependencies = [("billing", "0002_seed_plans"), ("audit", "0002_append_only_trigger")]

    operations = [
        migrations.RunSQL(APPEND_ONLY_FUNCTION, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(
            append_only_sql("billing_usageledger"), reverse_sql=drop_append_only_sql("billing_usageledger")
        ),
    ]
