"""
Testimony API (SRS 34, 37, 54).

    /api/testimonies/                 testimonies register (submit + review)
    /api/testimonies/mine/            my own submissions (SRS 6.2)
    /api/testimonies/public/          published testimonies for the website (SRS 37)
    /api/testimonies/<id>/review/     approve / publish / reject (branch staff)
    /api/testimonies/<id>/feature/    mark as featured (branch staff)
"""

from django.db.models import Q
from django_filters import rest_framework as filters
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from audit.services import log_action, model_snapshot
from core import access
from core.permissions import IsBranchStaff
from notifications.services import notify_role, notify_user

from .models import Testimony
from .serializers import TestimonyPublicSerializer, TestimonySerializer


class TestimonyFilter(filters.FilterSet):
    class Meta:
        model = Testimony
        fields = ['status', 'category', 'branch', 'is_featured', 'allow_public']


class TestimonyViewSet(viewsets.ModelViewSet):
    """Testimony workflow: PENDING -> UNDER_REVIEW -> APPROVED/PUBLISHED (SRS 34)."""

    queryset = Testimony.objects.select_related('member', 'branch', 'reviewed_by').all()
    serializer_class = TestimonySerializer
    filterset_class = TestimonyFilter
    search_fields = ['reference', 'title', 'body']
    ordering_fields = ['created_at', 'published_at', 'status']

    REVIEW_STATUSES = {'UNDER_REVIEW', 'APPROVED', 'PUBLISHED', 'REJECTED'}

    def get_permissions(self):
        if self.action == 'public':
            return [AllowAny()]
        if self.action in {'review', 'feature', 'update', 'partial_update', 'destroy'}:
            return [IsBranchStaff()]
        return [IsAuthenticated()]

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if self.action == 'mine':
            return queryset.filter(Q(user=user) | Q(member__user=user))
        if self.action == 'public':
            return queryset.filter(status='PUBLISHED', allow_public=True, is_active=True)
        if access.is_jimbo_level(user) or access.has_role(
            user, 'BRANCH_LEADER', 'BRANCH_SECRETARY', 'MINISTRY_LEADER',
        ):
            return access.apply_branch_scope(queryset, user)
        return queryset.filter(Q(user=user) | Q(member__user=user))


    def perform_create(self, serializer):
        user = self.request.user
        member = getattr(user, 'member_profile', None)
        branch = getattr(member, 'branch', None) or access.primary_branch(user)
        testimony = serializer.save(user=user, member=member, branch=branch, status='PENDING')
        log_action(request=self.request, action='CREATE', instance=testimony,
                   description=f'Testimony {testimony.reference} submitted for review.')
        for role_code in ('BRANCH_LEADER', 'BRANCH_SECRETARY'):
            notify_role(
                role_code, title='Ushuhuda mpya umewasilishwa',
                body=f'{testimony.reference}: {testimony.title}',
                category='SYSTEM', branch=branch, related_entity='Testimony',
                related_object_id=testimony.pk, action_url='/testimonies',
            )

    def perform_update(self, serializer):
        old_value = model_snapshot(serializer.instance, exclude=('updated_at',))
        testimony = serializer.save()
        log_action(request=self.request, action='UPDATE', instance=testimony, old_value=old_value,
                   description=f'Testimony {testimony.reference} updated.')

    def perform_destroy(self, instance):
        """Testimonies are deactivated, never deleted (SRS 18, 68)."""
        reason = self.request.data.get('reason', '')
        instance.deactivate(self.request.user, reason)
        log_action(request=self.request, action='DEACTIVATE', instance=instance, reason=reason,
                   description=f'Testimony {instance.reference} deactivated.')

    @action(detail=True, methods=['post'], permission_classes=[IsBranchStaff])
    def review(self, request, pk=None):
        """
        Move a testimony through the review workflow (SRS 34).

        Only branch leadership may approve, publish or reject; rejecting a
        testimony requires a reason that is stored for the author.
        """
        testimony = self.get_object()
        new_status = (request.data.get('status') or '').upper()
        if new_status not in self.REVIEW_STATUSES:
            allowed = ', '.join(sorted(self.REVIEW_STATUSES))
            raise ValidationError({'status': [f'Choose one of: {allowed}.']})
        notes = (request.data.get('review_notes') or '').strip()
        if new_status == 'REJECTED' and not notes:
            raise ValidationError({'review_notes': ['Explain why the testimony was rejected.']})

        testimony.review(request.user, new_status, notes)
        if new_status in {'APPROVED', 'PUBLISHED'}:
            audit_action = 'APPROVE'
        elif new_status == 'REJECTED':
            audit_action = 'REJECT'
        else:
            audit_action = 'UPDATE'
        log_action(request=request, action=audit_action, instance=testimony,
                   new_value={'status': new_status}, reason=notes,
                   description=f'Testimony {testimony.reference} marked {new_status}.')
        if testimony.user_id:
            notify_user(
                testimony.user, title='Hali ya ushuhuda wako imebadilika',
                body=f'{testimony.reference} sasa: {testimony.get_status_display()}.',
                category='SYSTEM', related_entity='Testimony',
                related_object_id=testimony.pk, action_url='/testimonies',
            )
        return Response(self.get_serializer(testimony).data)


    @action(detail=True, methods=['post'], permission_classes=[IsBranchStaff])
    def feature(self, request, pk=None):
        """Toggle the featured flag used by the public website (SRS 34)."""
        testimony = self.get_object()
        testimony.is_featured = not testimony.is_featured
        testimony.save(update_fields=['is_featured', 'updated_at'])
        log_action(request=request, action='UPDATE', instance=testimony,
                   new_value={'is_featured': testimony.is_featured},
                   description=f'Testimony {testimony.reference} featured={testimony.is_featured}.')
        return Response(self.get_serializer(testimony).data)

    @action(detail=False, methods=['get'], permission_classes=[AllowAny])
    def public(self, request):
        """Published testimonies for the public website (SRS 34, 37)."""
        queryset = self.get_queryset().order_by('-is_featured', '-published_at', '-id')
        limit = request.query_params.get('limit')
        if limit and limit.isdigit():
            queryset = list(queryset[:int(limit)])
        return Response({
            'count': len(queryset) if isinstance(queryset, list) else queryset.count(),
            'results': TestimonyPublicSerializer(queryset, many=True).data,
        })

    @action(detail=False, methods=['get'])
    def mine(self, request):
        """``GET /api/testimonies/mine/`` - my own submissions (SRS 6.2)."""
        queryset = self.filter_queryset(self.get_queryset()).order_by('-created_at')
        return Response(self.get_serializer(queryset, many=True).data)

