from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import MinistryMembershipViewSet, MinistryViewSet

router = DefaultRouter()
router.register('ministries', MinistryViewSet, basename='ministry')
router.register('ministry-memberships', MinistryMembershipViewSet, basename='ministry-membership')

urlpatterns = [
    # SRS 54 - /api/ministries/
    path('', include(router.urls)),
]

