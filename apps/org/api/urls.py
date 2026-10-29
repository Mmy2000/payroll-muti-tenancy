from rest_framework.routers import SimpleRouter

from .views import BranchViewSet, DepartmentViewSet

router = SimpleRouter()
router.register("branches", BranchViewSet, basename="branch")
router.register("departments", DepartmentViewSet, basename="department")

urlpatterns = router.urls
