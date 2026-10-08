from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AttendanceRecordViewSet,
    AttendanceSessionViewSet,
    QRScanView,
    RegistrationVerifyView,
)

router = DefaultRouter()
router.register('attendance/sessions', AttendanceSessionViewSet, basename='attendance-session')
router.register('attendance/records', AttendanceRecordViewSet, basename='attendance-record')

urlpatterns = [
    # SRS 27, 54, 72 - QR based attendance
    path('attendance/scan/', QRScanView.as_view(), name='attendance-scan'),
    path('attendance/verify/<str:token>/', RegistrationVerifyView.as_view(), name='verify-registration'),
    path('', include(router.urls)),
]

