"""Audit trail API (SRS 48, 54 - /api/audit-logs/)."""

from django_filters import rest_framework as filters
from rest_framework import viewsets

from core.permissions import IsJimboFinance
from .models import AuditLog
from .serializers import AuditLogSerializer


class AuditLogFilter(filters.FilterSet):
    date_from = filters.DateFilter(field_name='created_at', lookup_expr='date__gte')
    date_to = filters.DateFilter(field_name='created_at', lookup_expr='date__lte')
    username = filters.CharFilter(field_name='username_snapshot', lookup_expr='icontains')

    class Meta:
        model = AuditLog
        fields = ['action', 'entity', 'entity_id', 'branch', 'user', 'date_from', 'date_to', 'username']


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read only: audit records can never be modified or deleted through the API.
    """

    queryset = AuditLog.objects.select_related('user', 'branch').all()
    serializer_class = AuditLogSerializer
    permission_classes = [IsJimboFinance]
    filterset_class = AuditLogFilter
    search_fields = ['username_snapshot', 'entity', 'entity_id', 'description', 'reason']
    ordering_fields = ['created_at', 'action', 'entity']

    def get_queryset(self):
        queryset = super().get_queryset()
        from core import access

        return access.apply_branch_scope(queryset, self.request.user)
