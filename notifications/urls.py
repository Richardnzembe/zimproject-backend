from django.urls import path

from .views import (
    NotificationClearView,
    NotificationListView,
    NotificationReadAllView,
    NotificationReadView,
)

urlpatterns = [
    path("", NotificationListView.as_view(), name="notification-list"),
    path("<int:notification_id>/read/", NotificationReadView.as_view(), name="notification-read"),
    path("read-all/", NotificationReadAllView.as_view(), name="notification-read-all"),
    path("clear/", NotificationClearView.as_view(), name="notification-clear"),
]

