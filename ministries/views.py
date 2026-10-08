"""
Ministry API (SRS 24, 54 - /api/ministries/).
"""

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from audit.services import log_action
from core import access
from core.permissions import IsBranchLeaderOrAbove, IsJimboAdmin

from .models import Ministry, MinistryMembership
from .serializers import MinistryMembershipSerializer, MinistrySerializer


class MinistryViewSet(viewsets.ModelViewSet):
    """Ministries of the Jimbo and of the branches (SRS 24)."""

    queryset = Ministry.objects.select_related('branch', 'leader').all()
    serializer_class = MinistrySerializer
    filterset_fields = ['level', 'branch', 'is_active']
    search_fields = ['name', 'code', 'description']
    ordering_fields = ['level', 'name']

    def get_permissions(self):
        if self.action in {'create', 'update', 'partial_update', 'destroy'}:
            return [IsJimboAdmin()]
        return super().get_permissions()

    def get_queryset(self):
        return access.apply_branch_scope(super().get_queryset(), self.request.user)

    def perform_create(self, serializer):
        ministry = serializer.save(created_by=self.request.user)
        log_action(request=self.request, action='CREATE', instance=ministry,
                   description=f'Ministry "{ministry.name}" created.')

    def perform_update(self, serializer):
        ministry = serializer.save()
        log_action(request=self.request, action='UPDATE', instance=ministry,
                   description=f'Ministry "{ministry.name}" updated.')

    def perform_destroy(self, instance):
        """Ministries are deactivated, not deleted (SRS 68)."""
        instance.deactivate(self.request.user, self.request.data.get('reason', ''))
        log_action(self.request, action='DEACTIVATE', instance=instance,
                   description=f'Ministry "{instance.name}" deactivated.')

    @action(detail=True, methods=['get'])
    def members(self, request, pk=None):
        ministry = self.get_object()
        queryset = ministry.memberships.select_related('member', 'member__branch').filter(is_active=True)
        if not access.is_jimbo_level(request.user):
            queryset = access.apply_branch_scope(queryset, request.user, 'member__branch')
        return Response({
            'ministry': ministry.name,
            'count': queryset.count(),
            'members': MinistryMembershipSerializer(queryset, many=True).data,
        })


class MinistryMembershipViewSet(viewsets.ModelViewSet):
    """Who serves in which ministry (SRS 24)."""

    queryset = MinistryMembership.objects.select_related('ministry', 'member', 'member__branch').all()
    serializer_class = MinistryMembershipSerializer
    filterset_fields = ['ministry', 'role_in_ministry', 'is_active', 'member']
    search_fields = ['member__first_name', 'member__last_name', 'member__member_id']
    ordering_fields = ['ministry', 'role_in_ministry', 'joined_date']

    def get_permissions(self):
        if self.action in {'create', 'update', 'partial_update', 'destroy'}:
            return [IsBranchLeaderOrAbove()]
        return super().get_permissions()

    def get_queryset(self):
        return access.apply_branch_scope(super().get_queryset(), self.request.user, 'member__branch')

    def perform_create(self, serializer):
        membership = serializer.save()
        log_action(request=self.request, action='CREATE', instance=membership,
                   description=f'{membership.member.full_name} joined {membership.ministry.name}.')

    def perform_update(self, serializer):
        membership = serializer.save()
        log_action(request=self.request, action='UPDATE', instance=membership,
                   description='Ministry membership updated.')

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=['is_active', 'updated_at'])
        log_action(self.request, action='DEACTIVATE', instance=instance,
                   description='Ministry membership removed.')

    @action(detail=False, methods=['post'], url_path='assign-leader')
    def assign_leader(self, request):
        """Make a member the leader of a ministry and record the position (SRS 24)."""
        ministry_id = request.data.get('ministry')
        member_id = request.data.get('member')

        ministry = Ministry.objects.filter(pk=ministry_id).first()
        if ministry is None:
            from rest_framework.exceptions import ValidationError

            raise ValidationError({'ministry': ['A valid ministry is required.']})
        if not access.can_access_branch(request.user, ministry.branch_id):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied('You are not authorized to manage this ministry.')

        membership = MinistryMembership.objects.filter(ministry=ministry, member_id=member_id).first()
        if membership is None:
            raise ValidationError({'member': ['The member is not part of this ministry.']})
        membership.role_in_ministry = 'LEADER'
        membership.save(update_fields=['role_in_ministry', 'updated_at'])
        if membership.member.user_id and ministry.leader_id != membership.member.user_id:
            ministry.leader = membership.member.user
            ministry.save(update_fields=['leader', 'updated_at'])

        log_action(request=request, action='UPDATE', instance=ministry,
                   description=f'Ministry leader assigned: {membership.member.full_name}.')
        return Response(MinistrySerializer(ministry, context={'request': request}).data,
                        status=status.HTTP_200_OK)

