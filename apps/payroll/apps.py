from django.apps import AppConfig


class PayrollConfig(AppConfig):
    name = "apps.payroll"
    label = "payroll"
    verbose_name = "Payroll"

    def ready(self):
        from apps.core import locks

        from .selectors import period_locked, source_locked

        locks.register(period=period_locked, source=source_locked)
