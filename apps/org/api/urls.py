from rest_framework.routers import SimpleRouter

from .views import BranchViewSet, DepartmentViewSet, PositionViewSet

router = SimpleRouter()
router.register("branches", BranchViewSet, basename="branch")
router.register("departments", DepartmentViewSet, basename="department")
router.register("positions", PositionViewSet, basename="position")

urlpatterns = router.urls
