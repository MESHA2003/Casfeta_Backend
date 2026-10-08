from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import LeadershipPositionViewSet, LeadershipTermViewSet, PublicLeadershipDirectoryView

router = DefaultRouter()
router.register('leaders/positions', LeadershipPositionViewSet, basename='leadership-position')
router.register('leaders/terms', LeadershipTermViewSet, basename='leadership-term')

urlpatterns = [
    # SRS 54 - /api/leaders/...
    path('leaders/public/', PublicLeadershipDirectoryView.as_view(), name='public-leadership'),
    path('', include(router.urls)),
]

