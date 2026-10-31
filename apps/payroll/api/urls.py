from rest_framework.routers import SimpleRouter

from .views import CalendarViewSet, ManualLineViewSet, PayslipViewSet, RunViewSet

router = SimpleRouter()
router.register("calendars", CalendarViewSet, basename="pay-calendar")
router.register("runs", RunViewSet, basename="payroll-run")
router.register("payslips", PayslipViewSet, basename="payslip")
router.register("manual-lines", ManualLineViewSet, basename="manual-line")
urlpatterns = router.urls
