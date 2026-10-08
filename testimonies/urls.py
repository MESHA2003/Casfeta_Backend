from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import TestimonyViewSet

router = DefaultRouter()
router.register('testimonies', TestimonyViewSet, basename='testimony')

urlpatterns = [
    # SRS 34, 37, 54 - testimonies register + public feed
    path('', include(router.urls)),
]

