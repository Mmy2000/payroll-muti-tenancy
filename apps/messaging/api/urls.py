from rest_framework.routers import SimpleRouter

from .views import WhatsAppViewSet

router = SimpleRouter()
router.register("whatsapp", WhatsAppViewSet, basename="whatsapp")
urlpatterns = router.urls
