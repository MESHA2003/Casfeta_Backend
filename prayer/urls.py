from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import PrayerRequestViewSet

router = DefaultRouter()
router.register('prayer-requests', PrayerRequestViewSet, basename='prayer-request')

urlpatterns = [
    # SRS 54 - /api/prayer-requests/
    path('', include(router.urls)),
]

