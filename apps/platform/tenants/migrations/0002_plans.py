"""The starter plans, so a client can be provisioned on a fresh database."""

from django.db import migrations

PLANS = [
    ("trial", "Trial", "تجريبي", 0),
    ("standard", "Standard", "قياسية", 1),
    ("professional", "Professional", "احترافية", 2),
    ("enterprise", "Enterprise", "مؤسسية", 3),
]


def seed_plans(apps, schema_editor):
    Plan = apps.get_model("tenants", "Plan")
    db = schema_editor.connection.alias
    for code, name, name_ar, position in PLANS:
        Plan.objects.using(db).get_or_create(code=code, defaults={
            "name": name, "name_ar": name_ar, "position": position,
            "is_default": code == "standard"})


class Migration(migrations.Migration):
    dependencies = [("tenants", "0001_initial")]

    operations = [migrations.RunPython(seed_plans, migrations.RunPython.noop)]
