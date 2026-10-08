"""
Branch and Jimbo reporting (SRS 28, 29, 30, 59).

A branch submits periodic reports with the metrics listed in SRS 29; the
Jimbo sees consolidated reports and the system reminds branches that have not
submitted yet (SRS 59).
"""

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

from core.models import SoftDeleteModel, TimeStampedModel


class ReportType(TimeStampedModel):
    """Catalogue of report types (SRS 28) with their cadence and deadline."""

    FREQUENCY_CHOICES = [
        ('WEEKLY', 'Weekly'),
        ('MONTHLY', 'Monthly'),
        ('QUARTERLY', 'Quarterly'),
        ('ANNUAL', 'Annual'),
        ('EVENT', 'Event'),
        ('MINISTRY', 'Ministry'),
        ('FINANCIAL', 'Financial'),
        ('EVANGELISM', 'Evangelism'),
    ]

    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    name_sw = models.CharField(max_length=120, blank=True)
    frequency = models.CharField(max_length=12, choices=FREQUENCY_CHOICES, default='MONTHLY')
    deadline_day = models.PositiveSmallIntegerField(
        default=5, help_text='Day of the following month when the report is due (SRS 59).',
    )
    requires_financial_summary = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Report type'
        verbose_name_plural = 'Report types'

    def __str__(self):
        return self.name

    @classmethod
    def seed_defaults(cls):
        defaults = [
            ('WEEKLY', 'Weekly Report', 'Taarifa ya Wiki', 'WEEKLY', 3),
            ('MONTHLY', 'Monthly Report', 'Taarifa ya Mwezi', 'MONTHLY', 5),
            ('QUARTERLY', 'Quarterly Report', 'Taarifa ya Robo', 'QUARTERLY', 10),
            ('ANNUAL', 'Annual Report', 'Taarifa ya Mwa', 'ANNUAL', 31),
            ('EVENT', 'Event Report', 'Taarifa ya Tukio', 'EVENT', 7),
            ('MINISTRY', 'Ministry Report', 'Taarifa ya Huduma', 'MONTHLY', 5),
            ('FINANCIAL', 'Financial Report', 'Taarifa ya Fedha', 'MONTHLY', 5),
            ('EVANGELISM', 'Evangelism Report', 'Taarifa ya Uinjilisti', 'MONTHLY', 5),
        ]
        created = 0
        for code, name, name_sw, frequency, deadline in defaults:
            _, was_created = cls.objects.get_or_create(
                code=code,
                defaults={
                    'name': name, 'name_sw': name_sw, 'frequency': frequency, 'deadline_day': deadline,
                },
            )
            created += 1 if was_created else 0
        return created

class BranchReport(SoftDeleteModel):
    """
    A report submitted by a branch (SRS 29).

    One row per branch, report type and period; re-submitting updates the
    same row so the history stays clean.
    """

    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('SUBMITTED', 'Submitted'),
        ('UNDER_REVIEW', 'Under review'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('LATE', 'Late submission'),
    ]

    report_number = models.CharField(max_length=40, unique=True, blank=True)
    report_type = models.ForeignKey(ReportType, on_delete=models.PROTECT, related_name='reports')
    branch = models.ForeignKey('branches.Branch', on_delete=models.CASCADE, related_name='reports')
    period_year = models.PositiveSmallIntegerField(db_index=True)
    period_month = models.PositiveSmallIntegerField(null=True, blank=True, db_index=True)
    period_label = models.CharField(max_length=60, blank=True, help_text='e.g. August 2026 or Q1 2026')

    # --- metrics listed in SRS 29 ---
    total_members = models.PositiveIntegerField(default=0)
    new_members = models.PositiveIntegerField(default=0)
    inactive_members = models.PositiveIntegerField(default=0)
    fellowships = models.PositiveIntegerField(default=0)
    bible_studies = models.PositiveIntegerField(default=0)
    evangelism_activities = models.PositiveIntegerField(default=0)
    outreach_activities = models.PositiveIntegerField(default=0)
    academic_activities = models.PositiveIntegerField(default=0)
    leadership_activities = models.PositiveIntegerField(default=0)
    events_conducted = models.PositiveIntegerField(default=0)
    attendance_total = models.PositiveIntegerField(default=0)

    challenges = models.TextField(blank=True)
    achievements = models.TextField(blank=True)
    recommendations = models.TextField(blank=True)
    financial_summary = models.TextField(blank=True)
    financial_income = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    financial_expenses = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    financial_jimbo_contributed = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='DRAFT', db_index=True)
    submitted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='submitted_branch_reports',
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_branch_reports',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)
    attachments = models.FileField(upload_to='reports/', blank=True, null=True)

    class Meta:
        ordering = ['-period_year', '-period_month', '-created_at']
        verbose_name = 'Branch report'
        verbose_name_plural = 'Branch reports'
        constraints = [
            models.UniqueConstraint(
                fields=['branch', 'report_type', 'period_year', 'period_month'],
                name='unique_report_per_branch_period',
            ),
        ]

    def __str__(self):
        return f'{self.branch.code} - {self.report_type.code} {self.period_label or self.period_year}'

    @property
    def deadline(self):
        """Deadline date used by the submission reminders (SRS 59)."""
        from datetime import date

        if self.report_type.frequency == 'MONTHLY' and self.period_month:
            import calendar

            last_day = calendar.monthrange(self.period_year, self.period_month)[1]
            day = min(self.report_type.deadline_day, last_day)
            return date(self.period_year, self.period_month, day)
        if self.report_type.frequency == 'WEEKLY' and self.period_month:
            return timezone.localdate()
        return timezone.localdate()

    @property
    def is_overdue(self):
        return self.status in {'DRAFT', 'REJECTED', 'LATE'} and self.deadline < timezone.localdate()

    def submit(self, user=None):
        self.status = 'SUBMITTED'
        self.submitted_by = user if getattr(user, 'is_authenticated', False) else None
        self.submitted_at = timezone.now()
        self.save(update_fields=['status', 'submitted_by', 'submitted_at', 'updated_at'])
        return self

    def review(self, user, approved=True, notes=''):
        self.status = 'APPROVED' if approved else 'REJECTED'
        self.reviewed_by = user
        self.reviewed_at = timezone.now()
        self.review_notes = notes
        self.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_notes', 'updated_at'])
        return self

