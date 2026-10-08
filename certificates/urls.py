from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import CertificateTemplateViewSet, CertificateVerifyView, CertificateViewSet

router = DefaultRouter()
router.register('certificates', CertificateViewSet, basename='certificate')
router.register('certificate-templates', CertificateTemplateViewSet, basename='certificate-template')

urlpatterns = [
    # SRS 42, 46, 72 - public QR verification of a certificate
    path('certificates/verify/<str:token>/', CertificateVerifyView.as_view(), name='verify-certificate'),
    path('', include(router.urls)),
]

