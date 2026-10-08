"""Branch API (SRS 22, 37, 41, 54 - /api/branches/)."""

from django_filters import rest_framework as filters
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import log_action, model_snapshot
from core import access
from core.permissions import IsJimboAdmin, IsJimboFinance
from .models import Branch, BranchStatistics
from .serializers import (
    BranchPerformanceSerializer,
    BranchPublicSerializer,
    BranchSerializer,
    BranchStatisticsSerializer,
)
from .services import branch_membership_summary, compute_branch_performance, recalculate_branch_statistics


class BranchFilter(filters.FilterSet):
    district = filters.NumberFilter(field_name='district_id')
    status = filters.CharFilter(field_name='status', lookup_expr='iexact')
    has_institution = filters.BooleanFilter(field_name='institution', lookup_expr='isnull', exclude=True)

    class Meta:
        model = Branch
        fields = ['status', 'district', 'institution', 'is_active', 'meeting_day', 'founded_year']


class BranchViewSet(viewsets.ModelViewSet):
    """
    Branch management (SRS 22).

    Jimbo administrators create, update, activate and deactivate branches;
    branch level users may read only their own branch(es) (SRS 79).
    """

    queryset = Branch.objects.select_related('district', 'institution', 'organization').all()
    serializer_class = BranchSerializer
    filterset_class = BranchFilter
    search_fields = ['name', 'code', 'location', 'description']
    ordering_fields = ['name', 'code', 'created_at', 'status']

    def get_permissions(self):
        if self.action in {'create', 'update', 'partial_update', 'destroy', 'activate', 'deactivate'}:
            return [IsJimboAdmin()]
        if self.action in {'performance', 'performance_summary', 'recalculate_statistics'}:
            return [IsJimboFinance()]
        return super().get_permissions()

    def get_queryset(self):
        queryset = super().get_queryset()
        scope = access.branch_scope(self.request.user)
        if scope is None:
            return queryset
        if not scope:
            return queryset.none()
        return queryset.filter(id__in=list(scope))

    def perform_create(self, serializer):
        organization = serializer.validated_data.get('organization')
        if organization is None:
            from core.models import Organization

            organization = Organization.get_solo()
        branch = serializer.save(organization=organization, created_by=self.request.user)
        log_action(request=self.request, action='CREATE', instance=branch,
                   description=f'Branch {branch.code} created.')

    def perform_update(self, serializer):
        old_value = model_snapshot(serializer.instance, exclude=('updated_at',))
        branch = serializer.save()
        log_action(request=self.request, action='UPDATE', instance=branch, old_value=old_value,
                   description=f'Branch {branch.code} updated.')

    def perform_destroy(self, instance):
        instance.deactivate(self.request.user, self.request.data.get('reason', ''))
        log_action(request=self.request, action='DEACTIVATE', instance=instance,
                   reason=self.request.data.get('reason', ''),
                   description=f'Branch {instance.code} deactivated.')

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        branch = self.get_object()
        branch.status = 'ACTIVE'
        branch.is_active = True
        branch.save(update_fields=['status', 'is_active', 'updated_at'])
        log_action(request=request, action='UPDATE', instance=branch, description='Branch activated.')
        return Response(BranchSerializer(branch, context={'request': request}).data)

    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        branch = self.get_object()
        branch.status = 'INACTIVE'
        branch.is_active = False
        branch.save(update_fields=['status', 'is_active', 'updated_at'])
        log_action(request=request, action='DEACTIVATE', instance=branch,
                   reason=request.data.get('reason', ''), description='Branch deactivated.')
        return Response(BranchSerializer(branch, context={'request': request}).data)

    @action(detail=True, methods=['get'])
    def members(self, request, pk=None):
        """Member count per status for the branch dashboard."""
        branch = self.get_object()
        return Response({
            'branch': branch.id,
            'branch_name': branch.name,
            'statuses': branch_membership_summary(branch),
            'total': branch.member_count,
            'active': branch.active_member_count,
        })

    @action(detail=True, methods=['get'])
    def performance(self, request, pk=None):
        branch = self.get_object()
        year = request.query_params.get('year')
        month = request.query_params.get('month')
        data = compute_branch_performance(
            branch, int(year) if year else None, int(month) if month else None,
        )
        return Response(BranchPerformanceSerializer(data).data)

    @action(detail=False, methods=['get'], url_path='performance-summary')
    def performance_summary(self, request):
        """Comparison table of all accessible branches (SRS 40, 41)."""
        year = request.query_params.get('year')
        month = request.query_params.get('month')
        rows = [
            compute_branch_performance(branch, int(year) if year else None, int(month) if month else None)
            for branch in self.get_queryset().filter(is_active=True)
        ]
        return Response(BranchPerformanceSerializer(rows, many=True).data)

    @action(detail=False, methods=['post'], url_path='recalculate-statistics')
    def recalculate_statistics(self, request):
        from django.utils import timezone

        today = timezone.localdate()
        year = int(request.data.get('year', today.year))
        month = int(request.data.get('month', today.month))
        updated = recalculate_branch_statistics(year, month)
        log_action(request=request, action='SYSTEM', entity='BranchStatistics',
                   description=f'Branch statistics recalculated for {year}-{month:02d} ({updated} branches).')
        return Response({'detail': 'Branch statistics recalculated.', 'branches': updated})


class BranchStatisticsViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = BranchStatisticsSerializer
    permission_classes = [IsJimboFinance]
    queryset = BranchStatistics.objects.select_related('branch').all()
    filterset_fields = ['branch', 'period_year', 'period_month', 'report_submitted']

    def get_queryset(self):
        queryset = super().get_queryset()
        scope = access.branch_scope(self.request.user)
        if scope is None:
            return queryset
        return queryset.filter(branch_id__in=list(scope))


class PublicBranchListView(APIView):
    """Public branch directory (SRS 37)."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        queryset = Branch.objects.filter(is_active=True, status='ACTIVE').select_related('district', 'institution')
        district = request.query_params.get('district')
        if district:
            queryset = queryset.filter(district_id=district)
        search = request.query_params.get('search')
        if search:
            queryset = queryset.filter(name__icontains=search)
        queryset = queryset.order_by('name')
        return Response({
            'count': queryset.count(),
            'results': BranchPublicSerializer(queryset, many=True).data,
        })


class PublicBranchDetailView(APIView):
    """Public branch profile including approved leadership (SRS 37, 66)."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, key):
        if str(key).isdigit():
            branch = Branch.objects.filter(pk=int(key), is_active=True).first()
        else:
            branch = Branch.objects.filter(code__iexact=key, is_active=True).first()
        if branch is None:
            from rest_framework.exceptions import NotFound

            raise NotFound('Branch not found.')

        payload = BranchPublicSerializer(branch).data
        payload['leadership'] = [
            {
                'name': term.user.get_full_name() or term.user.username,
                'position': term.position.title,
            }
            for term in branch.assigned_leaders()
        ]
        payload['stats'] = {
            'total_members': branch.member_count,
            'active_members': branch.active_member_count,
        }
        return Response(payload)
