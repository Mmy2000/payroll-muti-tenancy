from django.apps import AppConfig


class MobileConfig(AppConfig):
    name = "apps.mobile"
    label = "mobile"
    verbose_name = "Mobile app"

    def ready(self):
        from apps.iam.member_links import EmployeeLink, register

        from . import selectors
        from .services import access

        register(EmployeeLink(can_link=access.can_link, choices=access.link_choices,
                              linked=selectors.linked_employee,
                              link_member=access.link_member))
