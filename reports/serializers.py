"""Report serializers (SRS 28, 29, 30)."""

from rest_framework import serializers

from .models import BranchReport, ReportType


class ReportTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReportType
        fields = [
            'id', 'code', 'name', 'name_sw', 'frequency', 'deadline_day',
            'requires_financial_summary', 'is_active', 'description', 'created_at',
        ]
        read_only_fields = ['created_at']


class BranchReportSerializer(serializers.ModelSerializer):
    """The monthly branch report of SRS 29."""

    branch_name = serializers.CharField(source='branch.name', read_only=True, default=None)
    branch_code = serializers.CharField(source='branch.code', read_only=True, default=None)
    report_type_name = serializers.CharField(source='report_type.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    submitted_by_name = serializers.CharField(source='submitted_by.username', read_only=True, default=None)
    deadline = serializers.DateField(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)

    class Meta:
        model = BranchReport
        fields = [
            'id', 'report_number', 'report_type', 'report_type_name', 'branch', 'branch_name',
            'branch_code', 'period_year', 'period_month', 'period_label', 'total_members',
            'new_members', 'inactive_members', 'fellowships', 'bible_studies',
            'evangelism_activities', 'outreach_activities', 'academic_activities',
            'leadership_activities', 'events_conducted', 'attendance_total', 'challenges',
            'achievements', 'recommendations', 'financial_summary', 'financial_income',
            'financial_expenses', 'financial_jimbo_contributed', 'status', 'status_display',
            'submitted_by_name', 'submitted_at', 'reviewed_at', 'review_notes', 'attachments',
            'deadline', 'is_overdue', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'report_number', 'submitted_by', 'submitted_at', 'reviewed_by', 'reviewed_at',
            'review_notes', 'created_at', 'updated_at', 'deadline', 'is_overdue',
        ]

    def validate(self, attrs):
        report_type = attrs.get('report_type') or getattr(self.instance, 'report_type', None)
        period_year = attrs.get('period_year') or getattr(self.instance, 'period_year', None)
        period_month = attrs.get('period_month')
        if period_month is None:
            period_month = getattr(self.instance, 'period_month', None)
        branch = attrs.get('branch') or getattr(self.instance, 'branch', None)
        if report_type and report_type.frequency == 'MONTHLY' and branch and period_year and period_month:
            existing = BranchReport.objects.filter(
                branch=branch, report_type=report_type, period_year=period_year, period_month=period_month,
            )
            if self.instance:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise serializers.ValidationError(
                    {'period_month': 'A report for this branch, type and period already exists.'}
                )
        return attrs

