from django.apps import AppConfig


class AttendanceConfig(AppConfig):
    name = "apps.attendance"
    label = "attendance"
    verbose_name = "Attendance"

    def ready(self):
        from apps.core.seeding import register_seed

        from .leave import seed_leave_types

        register_seed("attendance.leave_types", seed_leave_types)
