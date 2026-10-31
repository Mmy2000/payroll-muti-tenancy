from django.apps import AppConfig


class AdjustmentsConfig(AppConfig):
    name = "apps.adjustments"
    label = "adjustments"
    verbose_name = "Incentives and penalties"

    def ready(self):
        from apps.core.seeding import register_seed

        from .services.types import seed_types

        register_seed("adjustments.types", seed_types)
