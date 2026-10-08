from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    ChangePasswordAPIView,
    LoginAPIView,
    LogoutAPIView,
    MeAPIView,
    PermissionCatalogAPIView,
    PublicSignupAPIView,
    RoleAssignmentViewSet,
    RoleViewSet,
    UserViewSet,
)

router = DefaultRouter()
router.register('users', UserViewSet, basename='user')
router.register('roles', RoleViewSet, basename='role')
router.register('role-assignments', RoleAssignmentViewSet, basename='role-assignment')

urlpatterns = [
    # SRS 54 - /api/auth/
    path('auth/login/', LoginAPIView.as_view(), name='auth-login'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='auth-refresh'),
    path('auth/logout/', LogoutAPIView.as_view(), name='auth-logout'),
    path('auth/me/', MeAPIView.as_view(), name='auth-me'),
    path('auth/change-password/', ChangePasswordAPIView.as_view(), name='auth-change-password'),
    path('auth/register/', PublicSignupAPIView.as_view(), name='auth-register'),

    # SRS 54 - /api/permissions/
    path('permissions/', PermissionCatalogAPIView.as_view(), name='permission-catalog'),

    path('', include(router.urls)),
]
