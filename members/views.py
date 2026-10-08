"""
Membership API (SRS 20, 21, 37, 54, 64).

Endpoints
    /api/members/                 member register (branch scoped)
    /api/members/transfers/       member transfer workflow (SRS 64)
    /api/members/applications/    Join CASFETA applications (SRS 37)
    /api/members/<id>/card/       digital membership card (SRS 21)
    /api/verify/member/<token>/   public QR verification (SRS 21, 46)
"""

from django.db.models import Q
from django.utils import timezone
from django_filters import rest_framework as filters
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import log_action, model_snapshot
from core import access
from core.permissions import IsBranchLeaderOrAbove, IsBranchStaff, IsJimboAdmin
from core.qr import qr_png

from .models import Member, MembershipApplication, MemberTransfer
from .serializers import (
    MemberCardSerializer,
    MemberSerializer,
    MembershipApplicationSerializer,
    MemberTransferSerializer,
)


class MemberFilter(filters.FilterSet):
    """Member search and filtering (SRS 70)."""

    member_id = filters.CharFilter(field_name='member_id', lookup_expr='icontains')
    name = filters.CharFilter(method='filter_name')
    study_year = filters.NumberFilter()

    class Meta:
        model = Member
        fields = ['branch', 'institution', 'gender', 'district', 'status', 'study_year']

    def filter_name(self, queryset, name, value):
        return queryset.filter(
            Q(first_name__icontains=value) | Q(last_name__icontains=value)
            | Q(other_names__icontains=value),
        )


class MemberViewSet(viewsets.ModelViewSet):
    """Member register (SRS 20), branch scoped (SRS 79)."""

    queryset = Member.objects.select_related('branch', 'institution', 'district', 'user').all()
    serializer_class = MemberSerializer
    filterset_class = MemberFilter
    search_fields = ['first_name', 'last_name', 'other_names', 'member_id', 'email', 'phone']
    ordering_fields = ['first_name', 'last_name', 'created_at', 'status', 'membership_start_date']

    def get_permissions(self):
        if self.action in {'create', 'update', 'partial_update', 'approve', 'suspend', 'activate'}:
            return [IsBranchStaff()]
        if self.action == 'destroy':
            return [IsJimboAdmin()]
        return super().get_permissions()

    def get_queryset(self):
        return access.apply_branch_scope(super().get_queryset(), self.request.user)

    def perform_create(self, serializer):
        member = serializer.save()
        log_action(request=self.request, action='CREATE', instance=member,
                   description=f'Member {member.member_id} created.')

    def perform_update(self, serializer):
        old_value = model_snapshot(serializer.instance, exclude=('updated_at', 'qr_token'))
        member = serializer.save()
        log_action(request=self.request, action='UPDATE', instance=member, old_value=old_value,
                   description=f'Member {member.member_id} updated.')

    def perform_destroy(self, instance):
        """Members are deactivated, never deleted (SRS 18, 68)."""
        instance.deactivate(self.request.user, self.request.data.get('reason', ''))
        log_action(self.request, action='DEACTIVATE', instance=instance,
                   reason=self.request.data.get('reason', ''),
                   description=f'Member {instance.member_id} deactivated.')

    # -- actions -----------------------------------------------------------

    @action(detail=True, methods=['post'], permission_classes=[IsBranchLeaderOrAbove])
    def approve(self, request, pk=None):
        member = self.get_object()
        member.approve(request.user)
        member.card_issued_at = timezone.now()
        member.save(update_fields=['card_issued_at', 'updated_at'])
        log_action(request=request, action='APPROVE', instance=member,
                   description=f'Membership {member.member_id} approved by {request.user.username}.')
        return Response(MemberSerializer(member, context={'request': request}).data)

    @action(detail=True, methods=['post'], permission_classes=[IsBranchStaff])
    def suspend(self, request, pk=None):
        member = self.get_object()
        member.status = 'SUSPENDED'
        member.status_reason = request.data.get('reason', '')
        member.save(update_fields=['status', 'status_reason', 'updated_at'])
        log_action(request=request, action='UPDATE', instance=member,
                   reason=request.data.get('reason', ''),
                   description=f'Member {member.member_id} suspended.')
        return Response(MemberSerializer(member, context={'request': request}).data)

    @action(detail=True, methods=['post'], permission_classes=[IsBranchStaff])
    def activate(self, request, pk=None):
        member = self.get_object()
        member.status = 'ACTIVE'
        member.save(update_fields=['status', 'updated_at'])
        log_action(request=request, action='UPDATE', instance=member,
                   description=f'Member {member.member_id} reactivated.')
        return Response(MemberSerializer(member, context={'request': request}).data)

    @action(detail=True, methods=['get'])
    def card(self, request, pk=None):
        """Digital membership card payload (SRS 21, 72)."""
        member = self.get_object()
        payload = MemberCardSerializer({
            'member_id': member.member_id,
            'full_name': member.full_name,
            'photo': member.photo.url if member.photo else None,
            'branch': member.branch.name if member.branch_id else None,
            'institution': getattr(member.institution, 'name', None),
            'study_year': member.study_year,
            'status': member.status,
            'status_display': member.get_status_display(),
            'membership_start_date': member.membership_start_date,
            'membership_expiry_date': member.membership_expiry_date,
            'card_valid': member.is_card_valid,
            'qr_payload': f'/verify/member/{member.qr_token}/',
        }).data
        payload['qr_token'] = member.qr_token
        return Response(payload)

    @action(detail=True, methods=['get'], url_path='card-qr')
    def card_qr(self, request, pk=None):
        """PNG QR code of the membership card (SRS 21, 72)."""
        from django.http import HttpResponse

        member = self.get_object()
        response = HttpResponse(qr_png(f'/verify/member/{member.qr_token}'), content_type='image/png')
        response['Content-Disposition'] = f'inline; filename="card-{member.member_id}.png"'
        return response

class MembershipApplicationViewSet(viewsets.ModelViewSet):
    """
    Join CASFETA applications (SRS 37, 20).

    Anonymous visitors may submit an application; branch and Jimbo staff may
    list, review, approve or reject it.
    """

    queryset = MembershipApplication.objects.select_related('branch', 'institution', 'user').all()
    serializer_class = MembershipApplicationSerializer
    filterset_fields = ['status', 'branch', 'institution']
    search_fields = ['first_name', 'last_name', 'email', 'phone', 'application_number']
    ordering_fields = ['created_at', 'status']

    def get_permissions(self):
        if self.action == 'create':
            return [AllowAny()]
        return [IsBranchStaff()]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.method in {'GET', 'HEAD', 'OPTIONS'}:
            queryset = access.apply_branch_scope(queryset, self.request.user, 'branch')
        return queryset

    def perform_create(self, serializer):
        application = serializer.save()
        log_action(request=self.request, action='CREATE', instance=application,
                   description=f'Membership application {application.application_number} submitted.')

    @action(detail=True, methods=['post'], permission_classes=[IsBranchLeaderOrAbove])
    def approve(self, request, pk=None):
        application = self.get_object()
        if application.status == 'APPROVED':
            raise ValidationError({'detail': ['This application was already approved.']})
        member = application.approve(request.user, notes=request.data.get('notes', ''))

        log_action(request=request, action='APPROVE', instance=application,
                   description=f'Application {application.application_number} approved '
                               f'(member {member.member_id} created).')
        try:
            from notifications.services import notify_user

            if application.user:
                notify_user(
                    application.user,
                    title='MEMBERSHIP APPROVED - Uanachama Umekubaliwa',
                    body=(
                        f'Habari {member.full_name},\n\n'
                        f'Ombi lako la uanachama wa CASFETA limekubaliwa.\n'
                        f'Member ID: {member.member_id}\n'
                        f'Tawi (Branch): {member.branch.name}\n'
                        f'Status: ACTIVE\n\nKaribu CASFETA Zanzibar.'
                    ),
                    category='MEMBERSHIP', action_url='/membership/card',
                )
        except Exception:  # pragma: no cover - notification must not break approval
            pass

        return Response({
            'detail': 'Membership approved.',
            'member': MemberSerializer(member, context={'request': request}).data,
            'application': MembershipApplicationSerializer(application).data,
        })

    @action(detail=True, methods=['post'], permission_classes=[IsBranchLeaderOrAbove])
    def reject(self, request, pk=None):
        application = self.get_object()
        application.status = 'REJECTED'
        application.reviewed_by = request.user
        application.reviewed_at = timezone.now()
        application.review_notes = request.data.get('reason', '')
        application.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_notes', 'updated_at'])

        log_action(request=request, action='REJECT', instance=application,
                   reason=application.review_notes,
                   description=f'Application {application.application_number} rejected.')
        return Response(MembershipApplicationSerializer(application).data)

    @action(detail=True, methods=['post'])
    def under_review(self, request, pk=None):
        application = self.get_object()
        application.status = 'UNDER_REVIEW'
        application.save(update_fields=['status', 'updated_at'])
        return Response(MembershipApplicationSerializer(application).data)

class MemberTransferViewSet(viewsets.ModelViewSet):
    """Member transfer between branches (SRS 64). History stays intact."""

    queryset = MemberTransfer.objects.select_related(
        'member', 'from_branch', 'to_branch', 'requested_by',
    ).all()
    serializer_class = MemberTransferSerializer
    filterset_fields = ['status', 'from_branch', 'to_branch', 'member']
    ordering_fields = ['created_at', 'status']

    def get_permissions(self):
        if self.action in {'approve', 'complete'}:
            return [IsBranchLeaderOrAbove()]
        return [IsBranchStaff()]

    def get_queryset(self):
        return access.apply_branch_scope(super().get_queryset(), self.request.user, 'from_branch')

    def perform_create(self, serializer):
        transfer = serializer.save(requested_by=self.request.user)
        log_action(request=self.request, action='UPDATE', instance=transfer,
                   description=f'Transfer requested for {transfer.member.member_id}.')

    @action(detail=True, methods=['post'], permission_classes=[IsBranchLeaderOrAbove])
    def approve(self, request, pk=None):
        transfer = self.get_object()
        if transfer.status not in {'REQUESTED', 'APPROVED'}:
            raise ValidationError({'detail': [f'Transfer is already {transfer.get_status_display()}.']})
        transfer.status = 'APPROVED'
        transfer.approved_by = request.user
        transfer.approved_at = timezone.now()
        transfer.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
        log_action(request=request, action='APPROVE', instance=transfer,
                   description='Member transfer approved.')
        return Response(MemberTransferSerializer(transfer).data)

    @action(detail=True, methods=['post'], permission_classes=[IsBranchLeaderOrAbove])
    def complete(self, request, pk=None):
        transfer = self.get_object()
        if transfer.status != 'APPROVED':
            raise ValidationError({'detail': ['Approve the transfer before completing it.']})
        transfer.complete(request.user)
        log_action(request=request, action='UPDATE', instance=transfer,
                   description=f'Member moved to {transfer.to_branch.code}.')
        return Response(MemberTransferSerializer(transfer).data)


class PublicMemberVerifyView(APIView):
    """
    ``GET /api/verify/member/<token>/`` - public QR verification (SRS 21, 46).

    Returns only the fields approved for public verification: no phone
    numbers, no email addresses and no financial data.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = 'public_join'

    def get(self, request, token):
        member = Member.objects.filter(qr_token=token, is_active=True).select_related(
            'branch', 'institution',
        ).first()
        if member is None:
            from rest_framework.exceptions import NotFound

            raise NotFound('No membership record matches this QR code.')
        payload = member.public_verification_payload()
        payload['verified_at'] = timezone.now()
        payload['platform'] = 'CASFETA ZANZIBAR DIGITAL PLATFORM'
        return Response(payload)


class MyMembershipView(APIView):
    """``GET /api/members/me/`` - the logged-in user's own membership card."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        member = getattr(request.user, 'member_profile', None)
        if member is None:
            return Response(
                {'detail': 'You do not have an approved CASFETA membership yet.', 'has_membership': False},
                status=status.HTTP_404_NOT_FOUND,
            )
        payload = MemberCardSerializer({
            'member_id': member.member_id,
            'full_name': member.full_name,
            'photo': member.photo.url if member.photo else None,
            'branch': member.branch.name if member.branch_id else None,
            'institution': getattr(member.institution, 'name', None),
            'study_year': member.study_year,
            'status': member.status,
            'status_display': member.get_status_display(),
            'membership_start_date': member.membership_start_date,
            'membership_expiry_date': member.membership_expiry_date,
            'card_valid': member.is_card_valid,
            'qr_payload': f'/verify/member/{member.qr_token}/',
        }).data
        payload['qr_token'] = member.qr_token
        payload['has_membership'] = True
        payload['member'] = MemberSerializer(member, context={'request': request}).data
        return Response(payload)

