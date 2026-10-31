from rest_framework.routers import SimpleRouter

from .views import (
    IncentiveBatchViewSet,
    IncentiveTypeViewSet,
    IncentiveViewSet,
    PenaltyBatchViewSet,
    PenaltyTypeViewSet,
    PenaltyViewSet,
)

router = SimpleRouter()
router.register("incentive-types", IncentiveTypeViewSet, basename="incentive-type")
router.register("penalty-types", PenaltyTypeViewSet, basename="penalty-type")
router.register("incentive-batches", IncentiveBatchViewSet, basename="incentive-batch")
router.register("penalty-batches", PenaltyBatchViewSet, basename="penalty-batch")
router.register("incentives", IncentiveViewSet, basename="incentive")
router.register("penalties", PenaltyViewSet, basename="penalty")
urlpatterns = router.urls
