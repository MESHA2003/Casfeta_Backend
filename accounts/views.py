"""
Authentication and user management API (SRS 6, 7, 45, 54).

Endpoints
    POST /api/auth/login/            JWT login (also served as /api/login/)
    POST /api/auth/refresh/          refresh access token (rotation enabled)
    POST /api/auth/logout/           blacklist the refresh token
    GET  /api/auth/me/               current user + roles + branch scope
    PATCH /api/auth/me/              update own profile
    POST /api/auth/change-password/  change own password
    POST /api/auth/register/         public self registration (Join CASFETA)
    CRUD /api/users/                 user administration (Jimbo admin)
    CRUD /api/roles/                 role catalogue (Jimbo admin)
    CRUD /api/role-assignments/      grant / revoke roles (Jimbo admin)
    GET  /api/permissions/           role + permission catalogue
"""

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.utils import timezone
from django_filters import rest_framework as filters
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from audit.services import log_action
from core import access, roles as role_codes
from core.permissions import IsJimboAdmin, IsSuperAdmin
from notifications.services import notify_user

from .models import Role, RoleAssignment, UserProfile
from .serializers import (
    ChangePasswordSerializer,
    CZDMPTokenObtainPairSerializer,
    PublicSignupSerializer,
    RoleAssignmentSerializer,
    RoleSerializer,
    UserProfileSerializer,
    UserSerializer,
    UserWriteSerializer,
)


def tokens_for_user(user):
    """Issue a fresh access/refresh pair enriched with CZDMP claims."""
    refresh = CZDMPTokenObtainPairSerializer.get_token(user)
    return {'refresh': str(refresh), 'access': str(refresh.access_token)}


def user_payload(user):
    scope = access.branch_scope(user)
    member = getattr(user, 'member_profile', None)
    return {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'full_name': user.get_full_name() or user.username,
        'role_codes': sorted(access.user_role_codes(user)),
        'level': access.user_level(user),
        'branch_scope': None if scope is None else sorted(scope),
        'primary_branch': getattr(getattr(user, 'user_profile', None), 'primary_branch_id', None),
        'member_id': getattr(member, 'member_id', None),
        'member_status': getattr(member, 'status', None),
    }


class LoginAPIView(APIView):
    """Login and return JWT tokens plus the user's roles (SRS 45)."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'

    def post(self, request):
        username = request.data.get('username') or request.data.get('email')
        password = request.data.get('password')
        if not username or not password:
            return Response(
                {'detail': 'Username and password are required.', 'code': 'validation_error', 'errors': {}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(request, username=username, password=password)
        if user is None and '@' in str(username):
            candidate = User.objects.filter(email__iexact=username).first()
            if candidate is not None:
                user = authenticate(request, username=candidate.username, password=password)

        if user is None or not user.is_active:
            log_action(
                request=request, action='LOGIN_FAILED', entity='User',
                description=f'Failed login attempt for "{username}".', username=str(username),
            )
            return Response(
                {
                    'detail': 'Invalid credentials. Please check your username and password.',
                    'code': 'invalid_credentials',
                    'errors': {},
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        tokens = tokens_for_user(user)
        log_action(request=request, action='LOGIN', entity='User', entity_id=user.id, user=user,
                   description=f'{user.username} logged in.')
        return Response(
            {'message': 'Login successful', 'user': user_payload(user), **tokens},
            status=status.HTTP_200_OK,
        )


class LogoutAPIView(APIView):
    """Blacklist the refresh token so it can no longer be used (SRS 45)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get('refresh') or request.data.get('refresh_token')
        if not refresh_token:
            return Response(
                {'detail': 'The refresh token is required.', 'code': 'validation_error', 'errors': {}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            RefreshToken(refresh_token).blacklist()
        except TokenError:
            # Already invalid / expired: logout is still successful for the client.
            pass
        log_action(request=request, action='LOGOUT', entity='User', entity_id=request.user.id,
                   description=f'{request.user.username} logged out.')
        return Response({'detail': 'Logged out successfully.'}, status=status.HTTP_200_OK)


class MeAPIView(APIView):
    """Read or update the authenticated user's own profile (SRS 6.2)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user, context={'request': request}).data)

    def patch(self, request):
        user = request.user
        profile, _ = UserProfile.objects.get_or_create(user=user)

        changed = []
        for field in ['first_name', 'last_name']:
            if field in request.data:
                setattr(user, field, request.data[field])
                changed.append(field)
        if changed:
            user.save(update_fields=changed)

        profile_serializer = UserProfileSerializer(
            profile, data=request.data, partial=True, context={'request': request},
        )
        profile_serializer.is_valid(raise_exception=True)
        profile_serializer.save()

        log_action(request=request, action='UPDATE', entity='UserProfile', entity_id=profile.id,
                   description='User updated own profile.')
        return Response(UserSerializer(user, context={'request': request}).data)


class ChangePasswordAPIView(APIView):
    """Authenticated password change with audit trail (SRS 45, 48)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        user = request.user
        user.set_password(serializer.validated_data['new_password'])
        user.save(update_fields=['password'])

        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.password_changed_at = timezone.now()
        profile.must_change_password = False
        profile.save(update_fields=['password_changed_at', 'must_change_password', 'updated_at'])

        log_action(request=request, action='PASSWORD_CHANGE', entity='User', entity_id=user.id,
                   description='Password changed by the account owner.')
        return Response({'detail': 'Password changed successfully.', **tokens_for_user(user)})


class PublicSignupAPIView(APIView):
    """Public account creation (SRS 37 - Join CASFETA)."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'public_join'

    def post(self, request):
        serializer = PublicSignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        log_action(request=request, action='CREATE', entity='User', entity_id=user.id,
                   description=f'Public signup for "{user.username}" (awaiting membership application).')

        return Response(
            {
                'detail': 'Account created successfully. You can now apply for CASFETA membership.',
                'user': user_payload(user),
                **tokens_for_user(user),
            },
            status=status.HTTP_201_CREATED,
        )


class UserFilter(filters.FilterSet):
    role = filters.CharFilter(field_name='role_assignments__role__code', lookup_expr='iexact')
    branch = filters.NumberFilter(field_name='role_assignments__branch_id')
    has_member_profile = filters.BooleanFilter(field_name='member_profile', lookup_expr='isnull', exclude=True)

    class Meta:
        model = User
        fields = ['is_active', 'is_staff', 'is_superuser', 'role', 'branch']


class UserViewSet(viewsets.ModelViewSet):
    """User administration (SRS 6.8, 6.9)."""

    queryset = (
        User.objects
        .select_related('user_profile', 'member_profile')
        .prefetch_related('role_assignments__role', 'role_assignments__branch')
        .order_by('username')
    )
    permission_classes = [IsJimboAdmin]
    filterset_class = UserFilter
    search_fields = ['username', 'email', 'first_name', 'last_name', 'user_profile__phone']
    ordering_fields = ['username', 'date_joined', 'last_login']

    def get_serializer_class(self):
        if self.action in {'create', 'update', 'partial_update'}:
            return UserWriteSerializer
        return UserSerializer

    def _guard_superuser(self, instance):
        if instance.is_superuser and not access.is_super_admin(self.request.user):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied('Only a Super Administrator can modify another Super Administrator.')

    def perform_create(self, serializer):
        serializer.save()
        log_action(request=self.request, action='CREATE', instance=serializer.instance,
                   description='User account created.')

    def perform_update(self, serializer):
        self._guard_superuser(serializer.instance)
        old_value = {field: getattr(serializer.instance, field) for field in ['username', 'email', 'is_active']}
        serializer.save()
        log_action(request=self.request, action='UPDATE', instance=serializer.instance,
                   old_value=old_value, description='User account updated.')

    def perform_destroy(self, instance):
        self._guard_superuser(instance)
        if instance.pk == self.request.user.pk:
            from rest_framework.exceptions import ValidationError

            raise ValidationError({'detail': 'You cannot deactivate your own account.'})
        instance.is_active = False
        instance.save(update_fields=['is_active'])
        log_action(request=self.request, action='DEACTIVATE', instance=instance,
                   description='User account deactivated.')

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        user = self.get_object()
        user.is_active = True
        user.save(update_fields=['is_active'])
        log_action(request=request, action='UPDATE', instance=user, description='User account activated.')
        return Response(UserSerializer(user, context={'request': request}).data)

    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        user = self.get_object()
        self._guard_superuser(user)
        user.is_active = False
        user.save(update_fields=['is_active'])
        log_action(request=request, action='DEACTIVATE', instance=user,
                   reason=request.data.get('reason', ''), description='User account deactivated.')
        return Response(UserSerializer(user, context={'request': request}).data)

    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        user = self.get_object()
        self._guard_superuser(user)
        user.is_active = True
        user.save(update_fields=['is_active'])
        log_action(request=request, action='APPROVE', instance=user,
                   description='User account approved by an administrator.')
        notify_user(
            user,
            title='Registration approved',
            body='Your CASFETA Zanzibar account has been approved by the Regional Officer. You can now access the platform and continue with your assigned responsibilities.',
            category='ACCOUNT',
            priority='HIGH',
            related_entity='User',
            related_object_id=user.pk,
            action_url='/member',
        )
        return Response(UserSerializer(user, context={'request': request}).data)

    @action(detail=True, methods=['post'], url_path='reject')
    def reject(self, request, pk=None):
        user = self.get_object()
        self._guard_superuser(user)
        reason = request.data.get('reason') or 'Registration rejected by the Regional Officer.'
        user.is_active = False
        user.save(update_fields=['is_active'])
        log_action(request=request, action='REJECT', instance=user,
                   reason=reason, description='User registration rejected.')
        notify_user(
            user,
            title='Registration update',
            body=f'Your CASFETA Zanzibar account registration has been reviewed and is currently inactive. Reason: {reason}',
            category='ACCOUNT',
            priority='HIGH',
            related_entity='User',
            related_object_id=user.pk,
            action_url='/',
        )
        return Response(UserSerializer(user, context={'request': request}).data)

    @action(detail=True, methods=['post'], url_path='reset-password')
    def reset_password(self, request, pk=None):
        from django.contrib.auth.password_validation import validate_password

        user = self.get_object()
        self._guard_superuser(user)
        new_password = request.data.get('new_password') or User.objects.make_random_password()
        validate_password(new_password, user)
        user.set_password(new_password)
        user.save(update_fields=['password'])

        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.must_change_password = True
        profile.password_changed_at = timezone.now()
        profile.save(update_fields=['must_change_password', 'password_changed_at', 'updated_at'])

        log_action(request=request, action='PASSWORD_CHANGE', instance=user,
                   description='Password reset by an administrator.')
        return Response({'detail': 'Password reset successfully.', 'temporary_password': new_password})

    @action(detail=True, methods=['post'], url_path='set-roles')
    def set_roles(self, request, pk=None):
        """Replace the active role assignments of a user (SRS 48 - ROLE CHANGE)."""
        user = self.get_object()
        self._guard_superuser(user)
        role_codes_payload = request.data.get('role_codes') or []
        branch_id = request.data.get('branch')

        RoleAssignment.objects.filter(user=user).update(is_active=False)
        created = []
        for code in role_codes_payload:
            role = Role.objects.filter(code=code).first()
            if role is None:
                continue
            assignment, _ = RoleAssignment.objects.update_or_create(
                user=user,
                role=role,
                branch_id=branch_id if role.is_branch_scoped else None,
                ministry=None,
                defaults={'is_active': True, 'assigned_by': request.user},
            )
            created.append(assignment.id)

        log_action(request=request, action='ROLE_CHANGE', instance=user,
                   new_value={'role_codes': role_codes_payload, 'branch': branch_id},
                   description=f'Roles updated for {user.username}.')
        return Response(
            {'detail': 'Roles updated successfully.', 'assignment_ids': created},
            status=status.HTTP_200_OK,
        )

class RoleViewSet(viewsets.ModelViewSet):
    """Role catalogue management (SRS 6.8)."""

    queryset = Role.objects.prefetch_related('assignments').all()
    serializer_class = RoleSerializer
    permission_classes = [IsJimboAdmin]
    filterset_fields = ['scope', 'is_active', 'is_system']
    search_fields = ['code', 'name', 'name_sw', 'description']
    ordering_fields = ['level', 'name', 'code']

    def get_permissions(self):
        if self.action in {'create', 'destroy'}:
            return [IsSuperAdmin()]
        return super().get_permissions()

    def perform_create(self, serializer):
        serializer.save(is_system=False)
        log_action(request=self.request, action='CREATE', instance=serializer.instance,
                   description='Role created.')

    def perform_update(self, serializer):
        old = {'name': serializer.instance.name, 'level': serializer.instance.level}
        serializer.save()
        log_action(request=self.request, action='UPDATE', instance=serializer.instance, old_value=old,
                   description='Role updated.')

    def perform_destroy(self, instance):
        if instance.is_system or instance.assignments.exists():
            from rest_framework.exceptions import ValidationError

            raise ValidationError({
                'detail': 'System roles or roles already assigned to users cannot be deleted; '
                          'deactivate the role instead.',
            })
        log_action(request=self.request, action='DELETE', instance=instance, description='Role deleted.')
        instance.delete()


class RoleAssignmentViewSet(viewsets.ModelViewSet):
    """Grant or revoke roles (SRS 48 - ROLE CHANGE)."""

    queryset = RoleAssignment.objects.select_related('role', 'branch', 'ministry', 'user').all()
    serializer_class = RoleAssignmentSerializer
    permission_classes = [IsJimboAdmin]
    filterset_fields = ['user', 'role', 'branch', 'ministry', 'is_active']
    search_fields = ['user__username', 'role__code', 'role__name', 'branch__name']
    ordering_fields = ['created_at', 'role__level']

    def perform_create(self, serializer):
        serializer.save()
        log_action(request=self.request, action='ROLE_CHANGE', instance=serializer.instance,
                   description='Role granted.')
        role_name = serializer.instance.role.name
        branch_name = serializer.instance.branch.name if serializer.instance.branch else 'the assigned scope'
        notify_user(
            serializer.instance.user,
            title='Leadership role assigned',
            body=f'Congratulations! Your CASFETA Zanzibar account has been assigned the position of {role_name} at {branch_name}. You can now access the functions authorized for your position.',
            category='ROLE_ASSIGNMENT',
            priority='HIGH',
            branch=serializer.instance.branch,
            related_entity='RoleAssignment',
            related_object_id=serializer.instance.pk,
            action_url='/member',
        )

    def perform_update(self, serializer):
        old = {'role': serializer.instance.role.code, 'branch': serializer.instance.branch_id,
               'is_active': serializer.instance.is_active}
        serializer.save()
        log_action(request=self.request, action='ROLE_CHANGE', instance=serializer.instance,
                   old_value=old, description='Role assignment updated.')

    def perform_destroy(self, instance):
        if instance.role.code == role_codes.SUPER_ADMIN and not access.is_super_admin(self.request.user):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied('Only a Super Administrator can revoke the Super Administrator role.')
        log_action(request=self.request, action='ROLE_CHANGE', instance=instance,
                   old_value={'role': instance.role.code, 'branch': instance.branch_id},
                   description='Role assignment revoked.')
        notify_user(
            instance.user,
            title='Access revoked',
            body=f'Your CASFETA Zanzibar role assignment for {instance.role.name} has been revoked by an administrator. Your access to related functions has been removed.',
            category='ROLE_ASSIGNMENT',
            priority='HIGH',
            branch=instance.branch,
            related_entity='RoleAssignment',
            related_object_id=instance.pk,
            action_url='/member',
        )
        instance.delete()


class PermissionCatalogAPIView(APIView):
    """
    Role and permission catalogue used by the frontend RoleGuard (SRS 7, 71).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        catalogue = {}
        for role in Role.objects.filter(is_active=True).order_by('-level'):
            catalogue[role.code] = {
                'name': role.name,
                'name_sw': role.name_sw,
                'scope': role.scope,
                'level': role.level,
                'permission_codes': role.permission_codes or [],
            }
        return Response(
            {
                'roles': catalogue,
                'levels': role_codes.LEVELS,
                'finance_policy_roles': role_codes.FINANCE_POLICY_ROLES,
                'jimbo_finance_roles': role_codes.JIMBO_FINANCE_ROLES,
                'branch_scoped_roles': role_codes.BRANCH_SCOPED_ROLES,
                'current_user': user_payload(request.user),
            }
        )
