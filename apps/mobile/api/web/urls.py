from rest_framework.routers import SimpleRouter

from .views import AppDeviceViewSet, AppLoginViewSet, AppQrViewSet

router = SimpleRouter()
router.register("logins", AppLoginViewSet, basename="app-login")
router.register("qr", AppQrViewSet, basename="app-qr")
router.register("devices", AppDeviceViewSet, basename="app-device")
urlpatterns = router.urls
