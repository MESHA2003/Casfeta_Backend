from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    MemberTransferViewSet,
    MemberViewSet,
    MembershipApplicationViewSet,
    MyMembershipView,
    PublicMemberVerifyView,
)

router = DefaultRouter()
router.register('members', MemberViewSet, basename='member')
router.register('applications', MembershipApplicationViewSet, basename='membership-application')
router.register('transfers', MemberTransferViewSet, basename='member-transfer')

urlpatterns = [
    # SRS 54 - /api/members/...
    path('members/me/', MyMembershipView.as_view(), name='my-membership'),
    # SRS 21, 46 - public QR verification of a membership card
    path('verify/member/<str:token>/', PublicMemberVerifyView.as_view(), name='verify-member'),
    path('', include(router.urls)),
]

