from django.db import migrations


def seed_plans(apps, schema_editor):  # type: ignore[no-untyped-def]
    from apps.billing.catalog import PLANS

    Plan = apps.get_model("billing", "Plan")
    for data in PLANS:
        Plan.objects.update_or_create(code=data["code"], defaults={k: v for k, v in data.items() if k != "code"})


class Migration(migrations.Migration):
    dependencies = [("billing", "0001_initial")]

    operations = [migrations.RunPython(seed_plans, migrations.RunPython.noop)]
