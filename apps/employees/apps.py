from django.apps import AppConfig


class EmployeesConfig(AppConfig):
    name = "apps.employees"
    label = "employees"
    verbose_name = "Employees"

    def ready(self):
        from apps.org.validators import register_use

        from .selectors import department_has_employees, has_employees

        register_use(department=department_has_employees, branch=has_employees)
