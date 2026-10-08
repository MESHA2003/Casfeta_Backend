"""
Branch level calculations (SRS 40, 41).

Branch performance is used for management and improvement, never merely for
punishment: the numbers are computed from the source modules so they always
reconcile with members, events, attendance, reports and finance.
"""

from datetime import date
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone


def _month_bounds(year=None, month=None):
    today = timezone.localdate()
    year = year or today.year
    month = month or today.month
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start, end


def compute_branch_performance(branch, year=None, month=None):
    """
    Return the performance indicators of one branch for a period (SRS 41).

    membership growth, attendance rate, report compliance, event
    participation, evangelism activities and financial reporting compliance.
    """
    from attendance.models import AttendanceRecord
    from events.models import Event
    from finance.services import branch_finance_summary
    from members.models import Member
    from reports.models import BranchReport

    start, end = _month_bounds(year, month)

    members = Member.objects.filter(branch=branch)
    total_members = members.count()
    active_members = members.filter(status='ACTIVE').count()
    new_members = members.filter(created_at__date__gte=start, created_at__date__lt=end).count()

    events_queryset = Event.objects.filter(branch=branch, start_date__gte=start, start_date__lt=end)
    events_conducted = events_queryset.count()

    attendance = AttendanceRecord.objects.filter(
        branch=branch, attendance_date__gte=start, attendance_date__lt=end,
    )
    attendance_total = attendance.count()
    present_total = attendance.filter(status__in=['PRESENT', 'LATE']).count()
    attendance_rate = (
        Decimal(present_total * 100) / Decimal(attendance_total) if attendance_total else Decimal('0')
    )

    reports = BranchReport.objects.filter(branch=branch, period_year=start.year, period_month=start.month)
    report_submitted = reports.exclude(status__in=['DRAFT', 'REJECTED']).exists()
    report_compliance = Decimal('100') if report_submitted else Decimal('0')

    finance = branch_finance_summary(branch, year=start.year, month=start.month)
    income_total = finance.get('total_income') or Decimal('0')
    financial_compliance = Decimal('100') if income_total > 0 or report_submitted else Decimal('0')

    return {
        'branch': branch.id,
        'branch_name': branch.name,
        'branch_code': branch.code,
        'total_members': total_members,
        'active_members': active_members,
        'new_members_this_month': new_members,
        'events_conducted': events_conducted,
        'attendance_rate': attendance_rate.quantize(Decimal('0.01')),
        'report_compliance': report_compliance,
        'financial_reporting_compliance': financial_compliance,
        'total_income': finance.get('total_income', Decimal('0')),
        'jimbo_contribution': finance.get('jimbo_contribution', Decimal('0')),
        'pending_contribution': finance.get('pending_remittance', Decimal('0')),
    }


def recalculate_branch_statistics(period_year, period_month, branch=None):
    """Store/refresh the monthly snapshot used by the analytics dashboard."""
    from branches.models import Branch, BranchStatistics

    queryset = Branch.objects.filter(is_active=True)
    if branch is not None:
        queryset = queryset.filter(pk=getattr(branch, 'pk', branch))

    updated = 0
    for item in queryset:
        performance = compute_branch_performance(item, period_year, period_month)
        BranchStatistics.objects.update_or_create(
            branch=item, period_year=period_year, period_month=period_month,
            defaults={
                'total_members': performance['total_members'],
                'new_members': performance['new_members_this_month'],
                'inactive_members': max(performance['total_members'] - performance['active_members'], 0),
                'events_conducted': performance['events_conducted'],
                'attendance_rate': performance['attendance_rate'],
                'report_submitted': performance['report_compliance'] == 100,
                'financial_report_compliance': performance['financial_reporting_compliance'],
            },
        )
        updated += 1
    return updated


def branch_membership_summary(branch):
    """Member counts per status, used by the branch dashboard."""
    from members.models import Member

    rows = (
        Member.objects.filter(branch=branch)
        .values('status')
        .annotate(total=Count('id'))
        .order_by('status')
    )
    return {row['status']: row['total'] for row in rows}
