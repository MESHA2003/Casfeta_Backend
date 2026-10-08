"""
Attendance API with QR scanning (SRS 27, 54, 72).

    /api/attendance/sessions/          register of sessions
    /api/attendance/records/           manual attendance entries
    /api/attendance/scan/              QR scan (registration or member QR)
    /api/attendance/my/                my attendance (SRS 6.2)
    /api/attendance/verify/<token>/    resolve a scanned QR token
"""

from django.db.models import Count, Q
from django.utils import timezone
from django_filters import rest_framework as filters
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from audit.services import log_action
from core import access
from core.permissions import IsBranchStaff
from events.models import Event, EventRegistration
from members.models import Member

from .models import AttendanceRecord, AttendanceSession
from .serializers import AttendanceRecordSerializer, AttendanceSessionSerializer


class AttendanceSessionViewSet(viewsets.ModelViewSet):
    """Open/close attendance registers (SRS 27)."""

    queryset = AttendanceSession.objects.select_related('event', 'branch', 'opened_by').all()
    serializer_class = AttendanceSessionSerializer
    filterset_fields = ['event', 'branch', 'is_open', 'session_date']
    ordering_fields = ['session_date', 'created_at']

    def get_permissions(self):
        if self.action in {'create', 'update', 'partial_update', 'close', 'destroy'}:
            return [IsBranchStaff()]
        return super().get_permissions()

    def get_queryset(self):
        return access.apply_branch_scope(super().get_queryset(), self.request.user)

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        session = self.get_object()
        session.close()
        log_action(request=request, action='UPDATE', instance=session,
                   description=f'Attendance session "{session}" closed.')
        return Response(AttendanceSessionSerializer(session, context={'request': request}).data)


class AttendanceRecordViewSet(viewsets.ModelViewSet):
    """Manual attendance entry (SRS 27)."""

    queryset = AttendanceRecord.objects.select_related(
        'session', 'event', 'member', 'branch', 'recorded_by',
    ).all()
    serializer_class = AttendanceRecordSerializer
    filterset_fields = ['event', 'session', 'branch', 'status', 'attendance_date', 'method']
    search_fields = ['guest_name', 'member__first_name', 'member__last_name', 'member__member_id']
    ordering_fields = ['attendance_date', 'check_in_time']

    def get_permissions(self):
        if self.action in {'create', 'update', 'partial_update', 'destroy'}:
            return [IsBranchStaff()]
        return [IsAuthenticated()]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == 'mine':
            return queryset.filter(member__user=self.request.user)
        return access.apply_branch_scope(queryset, self.request.user)

    def perform_create(self, serializer):
        record = serializer.save(method='MANUAL')
        log_action(request=self.request, action='CREATE', instance=record,
                   description=f'Attendance recorded manually: {record.person_name} ({record.status}).')

    @action(detail=False, methods=['get'])
    def mine(self, request):
        """My attendance history (SRS 6.2)."""
        queryset = self.filter_queryset(self.get_queryset())
        return Response(AttendanceRecordSerializer(queryset, many=True).data)

    @action(detail=False, methods=['get'], url_path='summary')
    def summary(self, request):
        """Attendance statistics used by the dashboards (SRS 40)."""
        queryset = access.apply_branch_scope(self.get_queryset(), request.user)
        rows = (
            queryset.values('status')
            .annotate(total=Count('id'))
            .order_by('status')
        )
        total = queryset.count()
        present = queryset.filter(status__in=['PRESENT', 'LATE']).count()
        rate = round((present * 100) / total, 2) if total else 0
        return Response({
            'total_records': total,
            'by_status': {row['status']: row['total'] for row in rows},
            'attendance_rate': rate,
        })

class QRScanView(APIView):
    """
    ``POST /api/attendance/scan/`` - record attendance from a scanned QR code
    (SRS 27, 72).

    Accepts an event registration QR ticket or a membership card QR. Scanning
    the same QR twice does not create a duplicate row - it reports
    ALREADY RECORDED.
    """

    permission_classes = [IsBranchStaff]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'qr_scan'

    def post(self, request):
        token = (request.data.get('token') or request.data.get('qr_token') or '').strip()
        if not token:
            raise ValidationError({'token': ['A scanned QR token is required.']})

        session = None
        event = None
        if request.data.get('session'):
            session = AttendanceSession.objects.filter(pk=request.data['session']).first()
        if request.data.get('event'):
            event = Event.objects.filter(pk=request.data['event']).first()

        registration = EventRegistration.objects.filter(qr_token=token).select_related(
            'event', 'member', 'branch',
        ).first()
        member = None

        if registration is None:
            member = Member.objects.filter(qr_token=token, is_active=True).select_related('branch').first()
            if member is None:
                return Response(
                    {'detail': 'Unknown QR code.', 'recorded': False},
                    status=status.HTTP_404_NOT_FOUND,
                )
            if session is None and event is None and member.branch_id:
                session = AttendanceSession.objects.filter(
                    is_open=True, branch=member.branch_id, session_date=timezone.localdate(),
                ).first()
        else:
            event = event or registration.event
            member = registration.member
            if session is None:
                lookup = Q(event=event)
                if event.branch_id:
                    lookup = lookup | Q(branch=event.branch, event__isnull=True)
                session = AttendanceSession.objects.filter(lookup, is_open=True).order_by(
                    '-created_at',
                ).first()
                if session is None and event.branch_id:
                    session = AttendanceSession.objects.create(
                        event=event, branch=event.branch, opened_by=request.user,
                        title=f'Attendance: {event.title}',
                    )

        branch = event.branch if event and event.branch_id else (member.branch if member else None)
        if branch and not access.can_access_branch(request.user, branch.id):
            raise PermissionDenied('You are not authorized to record attendance for this branch.')

        if member is None:
            return Response(
                {'detail': 'This registration has no member record.', 'recorded': False},
                status=status.HTTP_400_BAD_REQUEST,
            )

        existing_qs = AttendanceRecord.objects.filter(member=member)
        if session is not None:
            existing_qs = existing_qs.filter(session=session)
        elif event is not None:
            existing_qs = existing_qs.filter(event=event)
        else:
            existing_qs = existing_qs.filter(attendance_date=timezone.localdate())
        existing = existing_qs.first()
        if existing:
            return Response(
                {
                    'detail': 'ALREADY RECORDED',
                    'recorded': False,
                    'record': AttendanceRecordSerializer(existing).data,
                },
                status=status.HTTP_200_OK,
            )

        new_status = request.data.get('status', 'PRESENT')
        if new_status not in dict(AttendanceRecord.STATUS_CHOICES):
            new_status = 'PRESENT'

        record = AttendanceRecord.objects.create(
            session=session,
            event=event,
            registration=registration,
            member=member,
            branch=branch,
            attendance_date=timezone.localdate(),
            check_in_time=timezone.now(),
            status=new_status,
            method='QR',
            recorded_by=request.user,
            remarks=request.data.get('remarks', ''),
        )
        if registration and new_status in {'PRESENT', 'LATE'}:
            registration.mark_attended()

        log_action(request=request, action='ATTENDANCE_SCAN', instance=record,
                   description=f'QR scan: {member.full_name} marked {new_status}.')
        return Response(
            {
                'detail': 'Attendance recorded.',
                'recorded': True,
                'record': AttendanceRecordSerializer(record).data,
            },
            status=status.HTTP_201_CREATED,
        )

class RegistrationVerifyView(APIView):
    """``GET /api/attendance/verify/<token>/`` - resolve a scanned QR (SRS 72)."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, token):
        registration = EventRegistration.objects.filter(qr_token=token).select_related(
            'event', 'member', 'branch',
        ).first()
        if registration is None:
            member = Member.objects.filter(qr_token=token, is_active=True).first()
            if member is None:
                return Response({'valid': False, 'detail': 'Unknown QR code.'}, status=404)
            return Response({
                'valid': True,
                'type': 'membership',
                'member_id': member.member_id,
                'name': member.full_name,
                'branch': member.branch.name if member.branch_id else None,
                'status': member.status,
                'card_valid': member.is_card_valid,
            })
        return Response({
            'valid': registration.status != 'CANCELLED',
            'type': 'event_registration',
            'registration_id': registration.registration_id,
            'event': registration.event.title,
            'event_date': registration.event.start_date,
            'name': registration.registrant_name,
            'branch': registration.branch.name if registration.branch_id else None,
            'status': registration.status,
            'payment_status': registration.payment_status,
        })

