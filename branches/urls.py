from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    BranchStatisticsViewSet,
    BranchViewSet,
    PublicBranchDetailView,
    PublicBranchListView,
)

router = DefaultRouter()
router.register('branches', BranchViewSet, basename='branch')
router.register('branch-statistics', BranchStatisticsViewSet, basename='branch-statistic')

urlpatterns = [
    # SRS 37 - public branch directory
    path('branches/public/', PublicBranchListView.as_view(), name='public-branches'),
    path('branches/public/<str:key>/', PublicBranchDetailView.as_view(), name='public-branch-detail'),
    path('', include(router.urls)),
]
