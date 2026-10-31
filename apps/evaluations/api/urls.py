from rest_framework.routers import SimpleRouter

from .views import EvaluationViewSet

router = SimpleRouter()
router.register("evaluations", EvaluationViewSet, basename="evaluation")
urlpatterns = router.urls
