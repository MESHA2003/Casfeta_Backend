"""Prayer request API (SRS 33, 83 Rule 11 - privacy is mandatory)."""

from django_filters import rest_framework as filters
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from audit.services import log_action
from core import access
from core.permissions import IsBranchLeaderOrAbove, IsBranchStaff
from notifications.services import notify_user

from .models import PrayerFollowUp, PrayerRequest
from .serializers import (
    PrayerFollowUpSerializer,
    PrayerRequestCreateSerializer,
    PrayerRequestSerializer,
)


class PrayerRequestFilter(filters.FilterSet):
    class Meta:
        model = PrayerRequest
        fields = ['category', 'status', 'branch', 'is_team_request']


class PrayerRequestViewSet(viewsets.ModelViewSet):
    queryset = PrayerRequest.objects.select_related('branch', 'member', 'assigned_to').all()
    serializer_class = PrayerRequestSerializer
    filterset_class = PrayerRequestFilter
    search_fields = ['reference', 'subject']
    ordering_fields = ['created_at', 'status']

    def get_permissions(self):
        if self.action in {'create', 'mine'}:
            from rest_framework.permissions import IsAuthenticated
            return [IsAuthenticated()]
        return [IsBranchStaff()]

    def get_serializer_class(self):
        if self.action == 'create':
            return PrayerRequestCreateSerializer
        return PrayerRequestSerializer

    def get_queryset(self):
        qs = super().get_queryset().prefetch_related('follow_ups')
        if self.action == 'mine':
            return qs.filter(user=self.request.user)
        if access.is_jimbo_level(self.request.user):
            return qs
        if access.has_role(self.request.user, 'BRANCH_LEADER', 'MINISTRY_LEADER'):
            return access.apply_branch_scope(qs, self.request.user)
        return qs.filter(user=self.request.user)

    def perform_create(self, serializer):
        member = getattr(self.request.user, 'member_profile', None)
        prayer = serializer.save(
            user=self.request.user, member=member,
            branch=getattr(member, 'branch', None) or access.primary_branch(self.request.user),
            is_private=True, status='OPEN',
        )
        log_action(request=self.request, action='CREATE', instance=prayer,
                   description=f'Prayer request {prayer.reference} submitted.')
        notify_user(
            self.request.user, title='Ombi la maombi limepokelewa',
            body=f'Ombi lako {prayer.reference} limepokelewa. Timu ya maombi itakufuatilia.',
            category='PRAYER',
        )

    @action(detail=False, methods=['get'])
    def mine(self, request):
        qs = self.filter_queryset(self.get_queryset())
        return Response(PrayerRequestSerializer(qs, many=True, context={'request': request}).data)

    @action(detail=True, methods=['post'], permission_classes=[IsBranchLeaderOrAbove])
    def assign(self, request, pk=None):
        from django.contrib.auth.models import User
        prayer = self.get_object()
        assignee = User.objects.filter(pk=request.data.get('assigned_to')).first()
        if assignee is None:
            raise ValidationError({'assigned_to': ['Select a valid user.']})
        prayer.assigned_to = assignee
        if prayer.status == 'OPEN':
            prayer.status = 'IN_PROGRESS'
        prayer.save(update_fields=['assigned_to', 'status', 'updated_at'])
        log_action(request=request, action='UPDATE', instance=prayer,
                   description=f'Prayer request {prayer.reference} assigned.')
        return Response(PrayerRequestSerializer(prayer, context={'request': request}).data)

    @action(detail=True, methods=['post'], permission_classes=[IsBranchLeaderOrAbove], url_path='follow-up')
    def add_follow_up(self, request, pk=None):
        prayer = self.get_object()
        note = (request.data.get('note') or '').strip()
        if len(note) < 3:
            raise ValidationError({'note': ['Write the follow-up note.']})
        follow_up = PrayerFollowUp.objects.create(
            prayer_request=prayer, handled_by=request.user, note=note,
            is_private=request.data.get('is_private', True),
        )
        prayer.follow_up_notes = (prayer.follow_up_notes + '\n' + note).strip()[:2000]
        prayer.save(update_fields=['follow_up_notes', 'updated_at'])
        log_action(request=request, action='UPDATE', instance=prayer,
                   description=f'Follow-up added to {prayer.reference}.')
        return Response(PrayerFollowUpSerializer(follow_up).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], permission_classes=[IsBranchLeaderOrAbove])
    def answer(self, request, pk=None):
        prayer = self.get_object()
        prayer.status = 'ANSWERED'
        prayer.answered_note = request.data.get('answered_note', prayer.answered_note)
        prayer.save(update_fields=['status', 'answered_note', 'updated_at'])
        if prayer.user_id:
            notify_user(
                prayer.user, title='Ombi la maombi limejibiwa',
                body=f'Ombi lako {prayer.reference} limewekwa alama ya kujibiwa.',
                category='PRAYER',
            )
        log_action(request=request, action='UPDATE', instance=prayer,
                   new_value={'status': 'ANSWERED'})
        return Response(PrayerRequestSerializer(prayer, context={'request': request}).data)

    @action(detail=True, methods=['post'], permission_classes=[IsBranchLeaderOrAbove])
    def close(self, request, pk=None):
        prayer = self.get_object()
        prayer.status = 'CLOSED'
        prayer.save(update_fields=['status', 'updated_at'])
        log_action(request=request, action='UPDATE', instance=prayer,
                   new_value={'status': 'CLOSED'})
        return Response(PrayerRequestSerializer(prayer, context={'request': request}).data)



