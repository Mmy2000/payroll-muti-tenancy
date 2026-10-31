from django.apps import AppConfig


class EmployeesConfig(AppConfig):
    name = "apps.employees"
    label = "employees"
    verbose_name = "Employees"

    def ready(self):
        from apps.org.validators import register_department_use

        from .selectors import department_in_use

        register_department_use(department_in_use)
