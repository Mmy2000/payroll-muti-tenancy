from django.urls import path

from .views import NotificationsView, ReadAllView, ReadView

urlpatterns = [
    path("", NotificationsView.as_view(), name="notifications-api"),
    path("<int:pk>/read/", ReadView.as_view(), name="notifications-read"),
    path("read-all/", ReadAllView.as_view(), name="notifications-read-all"),
]
