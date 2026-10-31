from rest_framework.routers import SimpleRouter

from .views import DeviceUserViewSet, DeviceViewSet

router = SimpleRouter()
router.register("devices", DeviceViewSet, basename="device")
router.register("device-users", DeviceUserViewSet, basename="device-user")
urlpatterns = router.urls
