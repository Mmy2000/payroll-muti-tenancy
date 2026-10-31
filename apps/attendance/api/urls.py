from rest_framework.routers import SimpleRouter

from .views import DayEntryViewSet, HourlyLeaveViewSet, LeaveRequestViewSet, LeaveTypeViewSet

router = SimpleRouter()
router.register("days", DayEntryViewSet, basename="attendance-day")
router.register("leave-types", LeaveTypeViewSet, basename="leave-type")
router.register("leave-requests", LeaveRequestViewSet, basename="leave-request")
router.register("hourly-leave", HourlyLeaveViewSet, basename="hourly-leave")
urlpatterns = router.urls
