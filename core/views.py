"""
Core platform API (SRS sections 37, 38, 52, 85, 86).

    GET/PATCH  /api/organization/           Jimbo profile (SRS 86)
    GET        /api/organization/public/    public website configuration (SRS 37, 38)
    CRUD       /api/settings/               system settings catalogue (SRS 86)
    CRUD       /api/academic-years/         academic / membership years
    CRUD       /api/districts/              district catalogue (SRS 52)
    CRUD       /api/institutions/           institution catalogue (SRS 52)
    CRUD       /api/financial-policies/     configurable contribution policy (SRS 85)
    CRUD       /api/contact-messages/       "Contact CASFETA" form (SRS 37)
"""

from django.utils import timezone
from django_filters import rest_framework as filters
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import log_action, model_snapshot
from notifications.services import notify_role

from .models import (
    AcademicYear,
    ContactMessage,
    District,
    FinancialPolicy,
    Institution,
    Organization,
    SystemSetting,
)
from .permissions import IsFinancePolicyManager, IsJimboAdmin, IsJimboFinance
from .serializers import (
    AcademicYearSerializer,
    ContactMessageSerializer,
    DistrictSerializer,
    FinancialPolicySerializer,
    InstitutionSerializer,
    OrganizationPublicSerializer,
    OrganizationSerializer,
    SystemSettingSerializer,
)


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

class SystemSettingFilter(filters.FilterSet):
    class Meta:
        model = SystemSetting
        fields = ['group', 'value_type', 'is_public']


class DistrictFilter(filters.FilterSet):
    class Meta:
        model = District
        fields = ['region', 'parent', 'is_active']


class InstitutionFilter(filters.FilterSet):
    institution_type = filters.CharFilter(field_name='institution_type', lookup_expr='iexact')

    class Meta:
        model = Institution
        fields = ['district', 'institution_type', 'is_active']


class FinancialPolicyFilter(filters.FilterSet):
    effective_from = filters.DateFilter(field_name='effective_date', lookup_expr='gte')
    effective_to = filters.DateFilter(field_name='effective_date', lookup_expr='lte')

    class Meta:
        model = FinancialPolicy
        fields = ['status', 'effective_date']


class ContactMessageFilter(filters.FilterSet):
    class Meta:
        model = ContactMessage
        fields = ['status']


# ---------------------------------------------------------------------------
# Organization profile (SRS 37, 38, 86)
# ---------------------------------------------------------------------------

class OrganizationView(APIView):
    """``GET/PATCH /api/organization/`` - the Jimbo profile (SRS 86)."""

    def get_permissions(self):
        if self.request.method in ('GET', 'HEAD', 'OPTIONS'):
            return [IsAuthenticated()]
        return [IsJimboAdmin()]

    def get(self, request):
        return Response(OrganizationSerializer(Organization.get_solo()).data)

    def patch(self, request):
        organization = Organization.get_solo()
        old_value = model_snapshot(organization, exclude=('updated_at',))
        serializer = OrganizationSerializer(organization, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        log_action(request=request, action='UPDATE', instance=organization, old_value=old_value,
                   description='Organization profile updated.')
        return Response(serializer.data)


class OrganizationPublicView(APIView):
    """``GET /api/organization/public/`` - public website configuration (SRS 37, 38)."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        organization = Organization.get_solo()
        public_settings = {
            setting.key: setting.typed_value()
            for setting in SystemSetting.objects.filter(is_public=True)
        }
        return Response({
            'organization': OrganizationPublicSerializer(organization).data,
            'settings': public_settings,
            'generated_at': timezone.now(),
        })


# ---------------------------------------------------------------------------
# Configuration catalogues (SRS 52, 86)
# ---------------------------------------------------------------------------

class SystemSettingViewSet(viewsets.ModelViewSet):
    """System configuration catalogue (SRS 86) - writable by Jimbo admins only."""

    queryset = SystemSetting.objects.all()
    serializer_class = SystemSettingSerializer
    filterset_class = SystemSettingFilter
    search_fields = ['key', 'label', 'description']
    ordering_fields = ['group', 'key', 'updated_at']

    def get_permissions(self):
        if self.action in {'list', 'retrieve'}:
            return [IsAuthenticated()]
        return [IsJimboAdmin()]

    def perform_create(self, serializer):
        setting = serializer.save()
        log_action(request=self.request, action='CREATE', instance=setting,
                   description=f'System setting "{setting.key}" created.')

    def perform_update(self, serializer):
        old_value = model_snapshot(serializer.instance, exclude=('updated_at',))
        setting = serializer.save()
        log_action(request=self.request, action='UPDATE', instance=setting, old_value=old_value,
                   description=f'System setting "{setting.key}" updated.')


class AcademicYearViewSet(viewsets.ModelViewSet):
    """Academic / membership years (SRS 86)."""

    queryset = AcademicYear.objects.all()
    serializer_class = AcademicYearSerializer
    filterset_fields = ['is_current', 'is_membership_year', 'is_active']
    search_fields = ['name']
    ordering_fields = ['start_date', 'name']

    def get_permissions(self):
        if self.action in {'list', 'retrieve', 'current'}:
            return [IsAuthenticated()]
        return [IsJimboAdmin()]

    @action(detail=False, methods=['get'])
    def current(self, request):
        year = AcademicYear.current()
        if year is None:
            return Response(
                {'detail': 'No current academic year is configured.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(self.get_serializer(year).data)

    def perform_create(self, serializer):
        year = serializer.save()
        log_action(request=self.request, action='CREATE', instance=year,
                   description=f'Academic year {year.name} created.')

    def perform_update(self, serializer):
        old_value = model_snapshot(serializer.instance, exclude=('updated_at',))
        year = serializer.save()
        log_action(request=self.request, action='UPDATE', instance=year, old_value=old_value,
                   description=f'Academic year {year.name} updated.')


class DistrictViewSet(viewsets.ModelViewSet):
    """District / region catalogue (SRS 52) - browsable by staff, edited by admins."""

    queryset = District.objects.select_related('parent').all()
    serializer_class = DistrictSerializer
    filterset_class = DistrictFilter
    search_fields = ['name', 'code', 'region']
    ordering_fields = ['name', 'region', 'created_at']

    def get_permissions(self):
        if self.action in {'list', 'retrieve'}:
            return [IsAuthenticated()]
        return [IsJimboAdmin()]

    def perform_create(self, serializer):
        district = serializer.save()
        log_action(request=self.request, action='CREATE', instance=district,
                   description=f'District {district.name} created.')

    def perform_update(self, serializer):
        old_value = model_snapshot(serializer.instance, exclude=('updated_at',))
        district = serializer.save()
        log_action(request=self.request, action='UPDATE', instance=district, old_value=old_value,
                   description=f'District {district.name} updated.')


class InstitutionViewSet(viewsets.ModelViewSet):
    """Institution catalogue (SRS 52) - browsable by staff, edited by admins."""

    queryset = Institution.objects.select_related('district').all()
    serializer_class = InstitutionSerializer
    filterset_class = InstitutionFilter
    search_fields = ['name', 'code', 'location']
    ordering_fields = ['name', 'created_at']

    def get_permissions(self):
        if self.action in {'list', 'retrieve'}:
            return [IsAuthenticated()]
        return [IsJimboAdmin()]

    def perform_create(self, serializer):
        institution = serializer.save()
        log_action(request=self.request, action='CREATE', instance=institution,
                   description=f'Institution {institution.name} created.')

    def perform_update(self, serializer):
        old_value = model_snapshot(serializer.instance, exclude=('updated_at',))
        institution = serializer.save()
        log_action(request=self.request, action='UPDATE', instance=institution, old_value=old_value,
                   description=f'Institution {institution.name} updated.')


# ---------------------------------------------------------------------------
# Financial policy (SRS 85) - the 10% is data, never hard coded
# ---------------------------------------------------------------------------

class FinancialPolicyViewSet(viewsets.ModelViewSet):
    """
    Configurable contribution policy (SRS 85).

    Jimbo finance users may read the policy history; only Jimbo administrators
    may define a new percentage and effective date (SRS 83 Rule 6 + 10).
    """

    queryset = FinancialPolicy.objects.all()
    serializer_class = FinancialPolicySerializer
    filterset_class = FinancialPolicyFilter
    search_fields = ['name', 'description']
    ordering_fields = ['effective_date', 'contribution_percentage']

    def get_permissions(self):
        if self.action in {'list', 'retrieve', 'current'}:
            return [IsJimboFinance()]
        return [IsFinancePolicyManager()]

    @action(detail=False, methods=['get'])
    def current(self, request):
        """The percentage that applies today (falls back to settings)."""
        policy = FinancialPolicy.current()
        if policy is None:
            return Response({
                'contribution_percentage': str(FinancialPolicy.current_percentage()),
                'source': 'settings fallback',
                'effective_date': None,
            })
        return Response(self.get_serializer(policy).data)

    def perform_create(self, serializer):
        policy = serializer.save(approved_by=self.request.user)
        log_action(
            request=self.request, action='FINANCIAL_APPROVAL', instance=policy,
            description=(
                f'Financial policy "{policy.name}" set to {policy.contribution_percentage}% '
                f'from {policy.effective_date}.'
            ),
        )

    def perform_update(self, serializer):
        old_value = model_snapshot(serializer.instance, exclude=('updated_at',))
        policy = serializer.save()
        log_action(request=self.request, action='UPDATE', instance=policy, old_value=old_value,
                   description=f'Financial policy "{policy.name}" updated.')

    @action(detail=True, methods=['post'], permission_classes=[IsFinancePolicyManager])
    def supersede(self, request, pk=None):
        policy = self.get_object()
        policy.supersede(request.user)
        log_action(request=request, action='UPDATE', instance=policy,
                   new_value={'status': 'SUPERSEDED'},
                   description=f'Financial policy "{policy.name}" superseded.')
        return Response(self.get_serializer(policy).data)


# ---------------------------------------------------------------------------
# Public contact form (SRS 37)
# ---------------------------------------------------------------------------

class ContactMessageViewSet(viewsets.ModelViewSet):
    """
    "Contact CASFETA" form.

    Anonymous visitors may submit; only Jimbo administrators may read and
    handle the messages.
    """

    queryset = ContactMessage.objects.select_related('handled_by').all()
    serializer_class = ContactMessageSerializer
    filterset_class = ContactMessageFilter
    search_fields = ['full_name', 'email', 'subject', 'message']
    ordering_fields = ['created_at', 'status']

    def get_permissions(self):
        if self.action == 'create':
            return [AllowAny()]
        return [IsJimboAdmin()]

    def perform_create(self, serializer):
        message = serializer.save()
        log_action(request=self.request, action='CREATE', instance=message,
                   description=f'Contact message from {message.full_name} received.')
        notify_role(
            'JIMBO_ADMIN', title='New contact message',
            body=f'{message.full_name} ({message.email})\n{message.subject}',
            category='SYSTEM', related_entity='ContactMessage', related_object_id=message.pk,
            action_url='/admin/contact-messages',
        )

    @action(detail=True, methods=['post'], permission_classes=[IsJimboAdmin])
    def respond(self, request, pk=None):
        """Mark a message as resolved and store the response note (SRS 37)."""
        message = self.get_object()
        note = (request.data.get('response_notes') or '').strip()
        if not note:
            raise ValidationError({'response_notes': ['Write the response note.']})
        message.status = 'RESOLVED'
        message.handled_by = request.user
        message.response_notes = note
        message.save(update_fields=['status', 'handled_by', 'response_notes', 'updated_at'])
        log_action(request=request, action='UPDATE', instance=message,
                   new_value={'status': 'RESOLVED'},
                   description=f'Contact message "{message.subject}" resolved.')
        return Response(self.get_serializer(message).data)



