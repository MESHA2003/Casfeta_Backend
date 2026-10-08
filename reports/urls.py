from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import BranchReportViewSet, ReportTypeViewSet

router = DefaultRouter()
# NOTE: 'reports/types' must be registered BEFORE 'reports', otherwise the
# reports detail route (reports/<pk>/) swallows /api/reports/types/ (SRS 54).
router.register('reports/types', ReportTypeViewSet, basename='report-type')
router.register('reports', BranchReportViewSet, basename='branch-report')

urlpatterns = [
    # SRS 54 - /api/reports/
    path('', include(router.urls)),
]

