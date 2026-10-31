from rest_framework.routers import SimpleRouter

from .views import AssignmentViewSet, PayItemViewSet

router = SimpleRouter()
router.register("items", PayItemViewSet, basename="pay-item")
router.register("assignments", AssignmentViewSet, basename="pay-item-assignment")
urlpatterns = router.urls
