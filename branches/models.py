"""
Branch (Tawi) management (SRS 22, 41).

Every branch belongs to CASFETA Jimbo la Zanzibar (SRS 83 Rule 2) and carries
a unique branch code such as BR-SUZA-001.
"""

import re

from django.contrib.auth.models import User
from django.db import models

from core.models import SoftDeleteModel, TimeStampedModel


def generate_branch_code(name, model=None):
    """
    Build a unique branch code from the branch name.

    Example: "SUZA" -> BR-SUZA-001
    """
    model = model or Branch
    letters = re.sub(r'[^A-Za-z]', '', name or '').upper()[:4] or 'TAWI'
    sequence = model.objects.count() + 1
    code = f'BR-{letters}-{sequence:03d}'
    while model.objects.filter(code=code).exists():
        sequence += 1
        code = f'BR-{letters}-{sequence:03d}'
    return code


class Branch(SoftDeleteModel):
    """A CASFETA Zanzibar branch (tawi)."""

    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('PENDING', 'Pending activation'),
        ('INACTIVE', 'Inactive'),
        ('SUSPENDED', 'Suspended'),
    ]

    DAY_CHOICES = [
        ('MONDAY', 'Monday'), ('TUESDAY', 'Tuesday'), ('WEDNESDAY', 'Wednesday'),
        ('THURSDAY', 'Thursday'), ('FRIDAY', 'Friday'), ('SATURDAY', 'Saturday'), ('SUNDAY', 'Sunday'),
    ]

    name = models.CharField(max_length=150, unique=True)
    code = models.CharField(max_length=30, unique=True, blank=True)
    slug = models.SlugField(max_length=160, unique=True, blank=True)

    organization = models.ForeignKey(
        'core.Organization', on_delete=models.PROTECT, null=True, blank=True, related_name='branches',
    )
    district = models.ForeignKey(
        'core.District', on_delete=models.SET_NULL, null=True, blank=True, related_name='branches',
    )
    institution = models.ForeignKey(
        'core.Institution', on_delete=models.SET_NULL, null=True, blank=True, related_name='branches',
        help_text='Main institution of the branch, when applicable.',
    )
    location = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='ACTIVE')
    founded_year = models.PositiveSmallIntegerField(null=True, blank=True)

    meeting_day = models.CharField(max_length=12, choices=DAY_CHOICES, blank=True)
    meeting_time = models.TimeField(null=True, blank=True)
    meeting_venue = models.CharField(max_length=200, blank=True)

    contact_email = models.EmailField(blank=True, default='')
    contact_phone = models.CharField(max_length=30, blank=True, default='')
    description = models.TextField(blank=True)

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_branches',
    )

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Branches'

    def __str__(self):
        return f'{self.name} ({self.code})'

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = generate_branch_code(self.name)
        if not self.slug:
            from django.utils.text import slugify

            base = slugify(self.name) or self.code.lower()
            slug = base
            counter = 1
            while Branch.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                counter += 1
                slug = f'{base}-{counter}'
            self.slug = slug
        return super().save(*args, **kwargs)

    # -- convenience used by dashboards (SRS 40, 41) ------------------------

    @property
    def member_count(self):
        return self.members.count()

    @property
    def active_member_count(self):
        return self.members.filter(status='ACTIVE').count()

    def assigned_leaders(self):
        from leadership.models import LeadershipTerm

        return LeadershipTerm.objects.filter(branch=self, status='ACTIVE').select_related('position', 'user')


class BranchStatistics(TimeStampedModel):
    """
    Period snapshot of a branch, used by the performance dashboard (SRS 41).

    Values are recalculated from the source modules so the numbers always
    reconcile with members, events, attendance and finance.
    """

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='statistics')
    period_year = models.PositiveSmallIntegerField()
    period_month = models.PositiveSmallIntegerField()

    total_members = models.PositiveIntegerField(default=0)
    new_members = models.PositiveIntegerField(default=0)
    inactive_members = models.PositiveIntegerField(default=0)
    events_conducted = models.PositiveIntegerField(default=0)
    attendance_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    report_submitted = models.BooleanField(default=False)
    financial_report_compliance = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    class Meta:
        ordering = ['-period_year', '-period_month']
        verbose_name = 'Branch statistics'
        verbose_name_plural = 'Branch statistics'
        constraints = [
            models.UniqueConstraint(fields=['branch', 'period_year', 'period_month'],
                                    name='unique_branch_statistics_per_month'),
        ]

    def __str__(self):
        return f'{self.branch.name} {self.period_year}-{self.period_month:02d}'

    @property
    def label(self):
        return f'{self.period_year}-{self.period_month:02d}'
