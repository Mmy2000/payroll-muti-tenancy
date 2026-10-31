from rest_framework.routers import SimpleRouter

from .views import EmployeeViewSet, GroupHoursViewSet, PayChangeViewSet, ScheduleChangeViewSet

router = SimpleRouter()
router.register("employees", EmployeeViewSet, basename="employee")
router.register("pay-changes", PayChangeViewSet, basename="pay-change")
router.register("schedule-changes", ScheduleChangeViewSet, basename="schedule-change")
router.register("group-hours", GroupHoursViewSet, basename="group-hours")
urlpatterns = router.urls
