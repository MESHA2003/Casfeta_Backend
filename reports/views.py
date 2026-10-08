"""
Branch and Jimbo reporting API (SRS 28, 29, 30, 54, 59).

    /api/reports/types/        report catalogue (SRS 28)
    /api/reports/              branch reports (SRS 29)
    /api/reports/<id>/submit/  submit for a period
    /api/reports/reminders/    send submission reminders (SRS 59)
    /api/reports/consolidated/ Jimbo consolidated report (SRS 30)
"""

from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from audit.services import log_action
from core import access
from core.permissions import IsBranchLeaderOrAbove, IsBranchStaff, IsJimboAdmin, IsJimboFinance

from .models import BranchReport, ReportType
from .serializers import BranchReportSerializer, ReportTypeSerializer


class ReportTypeViewSet(viewsets.ModelViewSet):
    """Report catalogue (SRS 28)."""

    queryset = ReportType.objects.all()
    serializer_class = ReportTypeSerializer
    filterset_fields = ['frequency', 'is_active']
    search_fields = ['code', 'name', 'name_sw']

    def get_permissions(self):
        if self.action in {'list', 'retrieve'}:
            return [IsAuthenticated()]
        return [IsJimboAdmin()]


class BranchReportViewSet(viewsets.ModelViewSet):
    """Branch reports (SRS 29), branch scoped (SRS 79)."""

    queryset = BranchReport.objects.select_related('branch', 'report_type', 'submitted_by').all()
    serializer_class = BranchReportSerializer
    filterset_fields = ['branch', 'report_type', 'status', 'period_year', 'period_month']
    search_fields = ['report_number', 'branch__name', 'branch__code']
    ordering_fields = ['period_year', 'period_month', 'status', 'submitted_at']

    def get_permissions(self):
        if self.action in {'review', 'reminders'}:
            return [IsJimboAdmin()]
        if self.action in {'consolidated', 'summary'}:
            return [IsJimboFinance()]
        return [IsBranchStaff()]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action in {'consolidated', 'summary', 'reminders'}:
            return queryset
        return access.apply_branch_scope(queryset, self.request.user)

    def perform_create(self, serializer):
        report = serializer.save()
        if not report.report_number:
            report.save(update_fields=['report_number'])
        log_action(request=self.request, action='CREATE', instance=report,
                   description=f'Report {report.report_number} created (draft).')

    @action(detail=True, methods=['post'], permission_classes=[IsBranchLeaderOrAbove])
    def submit(self, request, pk=None):
        """Submit the report to the Jimbo (SRS 29, 48 - REPORT SUBMISSION)."""
        report = self.get_object()
        if report.status in {'APPROVED', 'SUBMITTED', 'UNDER_REVIEW'}:
            raise ValidationError({'detail': [f'This report is already {report.get_status_display()}.']})
        report.submit(request.user)
        log_action(request=request, action='REPORT_SUBMISSION', instance=report,
                   new_value={'status': 'SUBMITTED'},
                   description=f'Report {report.report_number} submitted by {request.user.username}.')
        return Response(BranchReportSerializer(report).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], permission_classes=[IsJimboAdmin])
    def review(self, request, pk=None):
        report = self.get_object()
        approved = request.data.get('approved', True)
        report.review(request.user, approved=bool(approved), notes=request.data.get('notes', ''))
        log_action(request=request, action='APPROVE' if approved else 'REJECT', instance=report,
                   reason=request.data.get('notes', ''),
                   description=f'Report {report.report_number} reviewed.')
        return Response(BranchReportSerializer(report).data)

    @action(detail=False, methods=['get'], permission_classes=[IsJimboFinance])
    def summary(self, request):
        """Submission statistics for the dashboard (SRS 40, 41)."""
        queryset = access.apply_branch_scope(self.get_queryset(), request.user)
        year = int(request.query_params.get('year') or timezone.localdate().year)
        month = request.query_params.get('month')
        queryset = queryset.filter(period_year=year)
        if month:
            queryset = queryset.filter(period_month=int(month))

        submitted = queryset.filter(status__in=['SUBMITTED', 'UNDER_REVIEW', 'APPROVED']).count()
        total = queryset.count()
        return Response({
            'period_year': year,
            'reports_total': total,
            'submitted': submitted,
            'pending': max(total - submitted, 0),
            'compliance_rate': round((submitted * 100) / total, 2) if total else 0,
            'by_status': {
                row['status']: row['total']
                for row in queryset.values('status').annotate(total=Count('id'))
            },
        })

    @action(detail=False, methods=['post'], permission_classes=[IsJimboAdmin])
    def reminders(self, request):
        """
        SRS 59 - remind branches that did not submit their report.

        Notifies the branch secretary and branch leader of every branch in
        scope: "SUZA Branch has not submitted the August Monthly Report."
        """
        from notifications.services import notify_report_reminder, recipients_for_role

        year = int(request.data.get('year') or timezone.localdate().year)
        month = int(request.data.get('month') or timezone.localdate().month)
        report_type = ReportType.objects.filter(pk=request.data.get('report_type')).first()
        if report_type is None:
            report_type = ReportType.objects.filter(frequency='MONTHLY', is_active=True).first()
        if report_type is None:
            raise ValidationError({'report_type': ['No active report type available.']})

        from branches.models import Branch

        sent = 0
        for branch in access.apply_branch_scope(Branch.objects.filter(is_active=True), request.user):
            report, _ = BranchReport.objects.get_or_create(
                branch=branch,
                report_type=report_type,
                period_year=year,
                period_month=month if report_type.frequency == 'MONTHLY' else None,
                defaults={'period_label': f'{year}-{month:02d}'},
            )
            if report.status in {'SUBMITTED', 'UNDER_REVIEW', 'APPROVED'}:
                continue
            recipients = recipients_for_role('BRANCH_SECRETARY', branch=branch)
            recipients += recipients_for_role('BRANCH_LEADER', branch=branch)
            sent += len(notify_report_reminder(report, recipients))

        log_action(request=request, action='SYSTEM', entity='BranchReport',
                   description=f'Report reminders sent for {year}-{month:02d} ({sent} notifications).')
        return Response({'detail': f'{sent} reminders sent.', 'notifications': sent})

    @action(detail=False, methods=['get'], permission_classes=[IsJimboFinance])
    def consolidated(self, request):
        """Consolidated Jimbo report (SRS 30)."""
        from branches.models import Branch
        from events.models import Event
        from finance.services import jimbo_finance_summary
        from members.models import Member

        year = int(request.query_params.get('year') or timezone.localdate().year)
        month = request.query_params.get('month')
        month_filter = {'period_month': int(month)} if month else {}

        reports = BranchReport.objects.filter(period_year=year, **month_filter)
        submitted = reports.filter(status__in=['SUBMITTED', 'UNDER_REVIEW', 'APPROVED'])
        total_branches = Branch.objects.filter(is_active=True).count()

        events_qs = Event.objects.filter(start_date__year=year, status__in=['PUBLISHED', 'ONGOING', 'COMPLETED'])
        if month:
            events_qs = events_qs.filter(start_date__month=int(month))

        finance_summary = jimbo_finance_summary(year, int(month) if month else None)

        return Response({
            'title': 'CASFETA ZANZIBAR REPORT',
            'period': f'{year}-{int(month):02d}' if month else str(year),
            'branches': total_branches,
            'members': Member.objects.filter(status='ACTIVE').count(),
            'new_members': submitted.aggregate(total=Sum('new_members'))['total'] or 0,
            'events': events_qs.count(),
            'evangelism_activities': submitted.aggregate(total=Sum('evangelism_activities'))['total'] or 0,
            'reports_submitted': f'{submitted.count()}/{total_branches}',
            'financial_contributions': finance_summary['received'],
            'financial_pending': finance_summary['pending'],
            'reports': BranchReportSerializer(submitted.order_by('-period_year')[:100], many=True).data,
        })

