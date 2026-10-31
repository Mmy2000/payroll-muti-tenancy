from rest_framework.routers import SimpleRouter

from .views import (
    HolidayViewSet,
    InsuranceRateViewSet,
    LatenessPolicyViewSet,
    OvertimePolicyViewSet,
    TaxTableViewSet,
)

router = SimpleRouter()
router.register("lateness", LatenessPolicyViewSet, basename="lateness-policy")
router.register("overtime", OvertimePolicyViewSet, basename="overtime-policy")
router.register("tax-tables", TaxTableViewSet, basename="tax-table")
router.register("insurance-rates", InsuranceRateViewSet, basename="insurance-rate")
router.register("holidays", HolidayViewSet, basename="holiday")
urlpatterns = router.urls
