"""
Certificate API (SRS 42, 46, 54, 72).

    /api/certificate-templates/          certificate designs (SRS 42)
    /api/certificates/                   issued certificates register
    /api/certificates/mine/              my own certificates
    /api/certificates/<id>/qr/           QR code PNG for printing
    /api/certificates/<id>/revoke/       revoke an issued certificate
    /api/certificates/verify/<token>/    public QR verification (SRS 46, 72)
"""

from django.db.models import F, Q
from django.http import HttpResponse
from django.utils import timezone
from django_filters import rest_framework as filters
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import log_action, model_snapshot
from core import access
from core.permissions import IsBranchLeaderOrAbove, IsBranchStaff, IsJimboAdmin
from core.qr import build_verification_url, qr_png
from notifications.services import notify_user

from .models import Certificate, CertificateTemplate
from .serializers import CertificateSerializer, CertificateTemplateSerializer


class CertificateFilter(filters.FilterSet):
    issued_from = filters.DateFilter(field_name='issued_date', lookup_expr='gte')
    issued_to = filters.DateFilter(field_name='issued_date', lookup_expr='lte')

    class Meta:
        model = Certificate
        fields = ['certificate_type', 'status', 'issued_date', 'is_active']


class CertificateTemplateViewSet(viewsets.ModelViewSet):
    """Certificate designs (SRS 42) - readable by branch staff, edited by admins."""

    queryset = CertificateTemplate.objects.all()
    serializer_class = CertificateTemplateSerializer
    filterset_fields = ['is_active']
    search_fields = ['name', 'title', 'issuer_name']

    def get_permissions(self):
        if self.action in {'list', 'retrieve'}:
            return [IsBranchStaff()]
        return [IsJimboAdmin()]


class CertificateViewSet(viewsets.ModelViewSet):
    """Issued certificates register (SRS 42), branch scoped (SRS 79)."""

    queryset = Certificate.objects.select_related(
        'recipient_member', 'recipient_user', 'template', 'issued_by',
    ).all()
    serializer_class = CertificateSerializer
    filterset_class = CertificateFilter
    search_fields = ['certificate_id', 'recipient_name', 'programme']
    ordering_fields = ['issued_date', 'created_at', 'certificate_id']

    def get_permissions(self):
        if self.action in {'create', 'update', 'partial_update'}:
            return [IsBranchStaff()]
        if self.action in {'destroy', 'revoke'}:
            return [IsBranchLeaderOrAbove()]
        return super().get_permissions()

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if self.action == 'mine':
            return queryset.filter(Q(recipient_user=user) | Q(recipient_member__user=user))
        if access.is_jimbo_level(user):
            return queryset
        if access.has_role(user, 'BRANCH_LEADER', 'BRANCH_SECRETARY', 'MINISTRY_LEADER'):
            return access.apply_branch_scope(queryset, user, branch_field='recipient_member__branch')
        # Ordinary members only ever see their own certificates.
        return queryset.filter(Q(recipient_user=user) | Q(recipient_member__user=user))


    def perform_create(self, serializer):
        recipient_member = serializer.validated_data.get('recipient_member')
        if recipient_member is not None and not access.can_access_branch(
            self.request.user, recipient_member.branch_id,
        ):
            raise PermissionDenied('You are not authorized to issue certificates for another branch.')

        certificate = serializer.save(issued_by=self.request.user)
        log_action(
            request=self.request, action='CREATE', instance=certificate,
            description=(
                f'Certificate {certificate.certificate_id} issued to '
                f'{certificate.recipient_name} ({certificate.get_certificate_type_display()}).'
            ),
        )
        if certificate.recipient_user_id:
            notify_user(
                certificate.recipient_user, title='Cheti chako kimeandaliwa',
                body=(
                    f'{certificate.certificate_id} - {certificate.programme}\n'
                    f'Tarehe: {certificate.issued_date:%d %B %Y}'
                ),
                category='SYSTEM', related_entity='Certificate',
                related_object_id=certificate.pk, action_url='/certificates',
            )

    def perform_update(self, serializer):
        old_value = model_snapshot(serializer.instance, exclude=('updated_at',))
        certificate = serializer.save()
        log_action(request=self.request, action='UPDATE', instance=certificate, old_value=old_value,
                   description=f'Certificate {certificate.certificate_id} updated.')

    def perform_destroy(self, instance):
        """Certificates are revoked / deactivated, never deleted (SRS 18, 68)."""
        reason = self.request.data.get('reason', '')
        instance.deactivate(self.request.user, reason)
        log_action(request=self.request, action='DEACTIVATE', instance=instance, reason=reason,
                   description=f'Certificate {instance.certificate_id} deactivated.')

    @action(detail=False, methods=['get'])
    def mine(self, request):
        """``GET /api/certificates/mine/`` - my own certificates (SRS 6.2)."""
        queryset = self.filter_queryset(self.get_queryset())
        return Response(self.get_serializer(queryset, many=True).data)

    @action(detail=True, methods=['get'])
    def qr(self, request, pk=None):
        """QR code PNG pointing at the public verification page (SRS 42, 72)."""
        certificate = self.get_object()
        payload = build_verification_url('/verify/certificate/', certificate.qr_token)
        response = HttpResponse(qr_png(payload), content_type='image/png')
        response['Content-Disposition'] = (
            f'inline; filename="certificate-{certificate.certificate_id}.png"'
        )
        return response


    @action(detail=True, methods=['post'], permission_classes=[IsBranchLeaderOrAbove])
    def revoke(self, request, pk=None):
        """Revoke an issued certificate (SRS 42). A reason is mandatory."""
        certificate = self.get_object()
        reason = (request.data.get('reason') or '').strip()
        if not reason:
            raise ValidationError({'reason': ['A reason is required to revoke a certificate.']})
        certificate.revoke(request.user, reason)
        log_action(
            request=request, action='UPDATE', instance=certificate, reason=reason,
            new_value={'status': 'REVOKED'}, description=f'Certificate {certificate.certificate_id} revoked.',
        )
        if certificate.recipient_user_id:
            notify_user(
                certificate.recipient_user, title='Cheti kimestishwa',
                body=f'{certificate.certificate_id} kimestishwa. Sababu: {reason}',
                category='SYSTEM', related_entity='Certificate',
                related_object_id=certificate.pk, action_url='/certificates',
            )
        return Response(self.get_serializer(certificate).data)


class CertificateVerifyView(APIView):
    """
    ``GET /api/certificates/verify/<token>/`` - public QR verification (SRS 42, 46, 72).

    Returns only the fields approved for public verification: no contact
    details and no internal notes.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = 'qr_scan'

    def get(self, request, token):
        certificate = Certificate.objects.filter(qr_token=token).select_related(
            'recipient_member',
        ).first()
        if certificate is None:
            raise NotFound('No certificate matches this QR code.')

        Certificate.objects.filter(pk=certificate.pk).update(
            verification_count=F('verification_count') + 1,
        )
        payload = certificate.public_verification_payload()
        payload['verified_at'] = timezone.now()
        payload['platform'] = 'CASFETA ZANZIBAR DIGITAL PLATFORM'
        return Response(payload)

