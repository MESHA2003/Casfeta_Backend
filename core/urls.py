from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AcademicYearViewSet,
    ContactMessageViewSet,
    DistrictViewSet,
    FinancialPolicyViewSet,
    InstitutionViewSet,
    OrganizationPublicView,
    OrganizationView,
    SystemSettingViewSet,
)

router = DefaultRouter()
router.register('settings', SystemSettingViewSet, basename='system-setting')
router.register('academic-years', AcademicYearViewSet, basename='academic-year')
router.register('districts', DistrictViewSet, basename='district')
router.register('institutions', InstitutionViewSet, basename='institution')
router.register('financial-policies', FinancialPolicyViewSet, basename='financial-policy')
router.register('contact-messages', ContactMessageViewSet, basename='contact-message')

urlpatterns = [
    # SRS 37, 38 - public website configuration
    path('organization/public/', OrganizationPublicView.as_view(), name='public-organization'),
    # SRS 86 - Jimbo profile
    path('organization/', OrganizationView.as_view(), name='organization'),
    path('', include(router.urls)),
]
