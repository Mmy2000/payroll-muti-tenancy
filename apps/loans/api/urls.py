from rest_framework.routers import SimpleRouter

from .views import AdvanceViewSet, InstallmentViewSet, LoanViewSet

router = SimpleRouter()
router.register("advances", AdvanceViewSet, basename="advance")
router.register("loans", LoanViewSet, basename="loan")
router.register("installments", InstallmentViewSet, basename="installment")
urlpatterns = router.urls
