from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AnnouncementViewSet,
    NotificationPreferenceView,
    NotificationTemplateViewSet,
    NotificationViewSet,
    TestNotificationView,
)

router = DefaultRouter()
router.register('notifications', NotificationViewSet, basename='notification')
router.register('announcements', AnnouncementViewSet, basename='announcement')
router.register('notification-templates', NotificationTemplateViewSet, basename='notification-template')

urlpatterns = [
    # SRS 36, 44, 54
    path('notifications/preferences/', NotificationPreferenceView.as_view(), name='notification-preferences'),
    path('notifications/test/', TestNotificationView.as_view(), name='notification-test'),
    path('', include(router.urls)),
]

