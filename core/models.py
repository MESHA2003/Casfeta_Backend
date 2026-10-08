"""
Core models for CZDMP.

Covers SRS sections 52 (core entities), 85 (configurable financial policy)
and 86 (system configuration).
"""

from datetime import date

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


# ---------------------------------------------------------------------------
# Abstract building blocks
# ---------------------------------------------------------------------------

class TimeStampedModel(models.Model):
    """Every CZDMP record keeps its creation and last change time (SRS 14)."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SoftDeleteModel(TimeStampedModel):
    """
    Records that must never be silently deleted (SRS 18, 83 Rule 7/8).

    Deactivation replaces deletion: the record is kept for history and only
    marked as inactive.
    """

    is_active = models.BooleanField(default=True, db_index=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)
    deactivated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='%(app_label)s_%(class)s_deactivations',
    )
    deactivation_reason = models.TextField(blank=True)

    class Meta:
        abstract = True

    def deactivate(self, user=None, reason=''):
        """Soft delete: keep history, mark the record inactive (SRS 68)."""
        self.is_active = False
        self.deactivated_at = timezone.now()
        self.deactivated_by = user if getattr(user, 'is_authenticated', False) else None
        self.deactivation_reason = reason
        self.save(update_fields=[
            'is_active', 'deactivated_at', 'deactivated_by', 'deactivation_reason', 'updated_at',
        ])
        return self

    def reactivate(self, user=None):
        self.is_active = True
        self.deactivated_at = None
        self.deactivated_by = None
        self.deactivation_reason = ''
        self.save(update_fields=[
            'is_active', 'deactivated_at', 'deactivated_by', 'deactivation_reason', 'updated_at',
        ])
        return self


# ---------------------------------------------------------------------------
# Organisation / configuration  (SRS 86)
# ---------------------------------------------------------------------------

class Organization(TimeStampedModel):
    """
    CASFETA Jimbo la Zanzibar - the highest authority represented in CZDMP
    (SRS 2.1). The system is Zanzibar only, therefore a single Jimbo record
    is normally used.
    """

    LEVEL_CHOICES = [('JIMBO', 'Jimbo'), ('TAWI', 'Tawi (branch level grouping)')]

    name = models.CharField(max_length=200, default='CASFETA Jimbo la Zanzibar')
    short_name = models.CharField(max_length=100, default='CASFETA Zanzibar')
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES, default='JIMBO')
    region_scope = models.CharField(max_length=100, default='Zanzibar')

    motto = models.CharField(max_length=200, blank=True, default='Kujenga Imani, Kukuza Taaluma, Kuhudumia Jamii')
    vision = models.TextField(blank=True)
    mission = models.TextField(blank=True)
    about = models.TextField(blank=True)
    core_values = models.TextField(blank=True)

    logo = models.ImageField(upload_to='organization/', blank=True, null=True)
    address = models.CharField(max_length=255, blank=True)
    contact_email = models.EmailField(blank=True, default='')
    contact_phone = models.CharField(max_length=30, blank=True, default='')
    whatsapp = models.CharField(max_length=30, blank=True, default='')
    website = models.URLField(blank=True, default='')
    facebook = models.URLField(blank=True, default='')
    instagram = models.URLField(blank=True, default='')
    youtube = models.URLField(blank=True, default='')

    currency = models.CharField(max_length=10, default='TZS')
    default_language = models.CharField(max_length=5, default='sw', choices=[('sw', 'Kiswahili'), ('en', 'English')])
    financial_year_start_month = models.PositiveSmallIntegerField(default=1)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Organization (Jimbo)'
        verbose_name_plural = 'Organization (Jimbo)'

    def __str__(self):
        return self.name

    @classmethod
    def get_solo(cls):
        """Return the Jimbo record, creating the default one when missing."""
        organization = cls.objects.order_by('id').first()
        if organization is None:
            organization = cls.objects.create()
        return organization


class SystemSetting(TimeStampedModel):
    """Key/value configuration editable by administrators (SRS 86)."""

    VALUE_TYPES = [
        ('STRING', 'Text'),
        ('INT', 'Integer'),
        ('DECIMAL', 'Decimal'),
        ('BOOL', 'Yes/No'),
        ('JSON', 'JSON'),
        ('DATE', 'Date'),
    ]

    key = models.CharField(max_length=120, unique=True)
    value = models.TextField(blank=True, default='')
    value_type = models.CharField(max_length=10, choices=VALUE_TYPES, default='STRING')
    group = models.CharField(max_length=60, default='general')
    label = models.CharField(max_length=150, blank=True)
    description = models.TextField(blank=True)
    is_public = models.BooleanField(
        default=False,
        help_text='Expose this value on the public website configuration endpoint.',
    )

    class Meta:
        ordering = ['group', 'key']

    def __str__(self):
        return f'{self.key} = {self.value}'

    def typed_value(self):
        raw = (self.value or '').strip()
        try:
            if self.value_type == 'INT':
                return int(raw or 0)
            if self.value_type == 'DECIMAL':
                from decimal import Decimal
                return Decimal(raw or '0')
            if self.value_type == 'BOOL':
                return raw.lower() in {'1', 'true', 'yes', 'on'}
            if self.value_type == 'JSON':
                import json
                return json.loads(raw or 'null')
        except (ValueError, TypeError):
            return raw
        return raw

    @classmethod
    def get_value(cls, key, default=None):
        setting = cls.objects.filter(key=key).first()
        return setting.typed_value() if setting else default

    @classmethod
    def set_value(cls, key, value, value_type='STRING', group='general', label=''):
        import json
        setting, _ = cls.objects.get_or_create(
            key=key,
            defaults={'value_type': value_type, 'group': group, 'label': label},
        )
        if value_type == 'JSON':
            setting.value = json.dumps(value)
        elif value_type == 'DATE':
            setting.value = value.isoformat() if hasattr(value, 'isoformat') else str(value)
        else:
            setting.value = '' if value is None else str(value)
        setting.value_type = value_type
        setting.save()
        return setting


class District(TimeStampedModel):
    """
    Configurable geographical grouping inside Zanzibar (SRS 2.1).

    Records can be nested through ``parent`` so that the Jimbo can organise
    branches by region, district or area without code changes.
    """

    name = models.CharField(max_length=120)
    code = models.CharField(max_length=30, blank=True)
    region = models.CharField(max_length=120, default='Zanzibar')
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['region', 'name']
        constraints = [models.UniqueConstraint(fields=['name', 'region'], name='unique_district_per_region')]

    def __str__(self):
        return self.name


class Institution(TimeStampedModel):
    """Institution a member is studying at (SRS 20, 52)."""

    TYPE_CHOICES = [
        ('UNIVERSITY', 'Chuo Kikuu (University)'),
        ('COLLEGE', 'Chuo (College)'),
        ('INSTITUTE', 'Taasisi (Institute)'),
        ('SECONDARY', 'Sekondari (Secondary school)'),
        ('OTHER', 'Nyingine (Other)'),
    ]

    name = models.CharField(max_length=200, unique=True)
    code = models.CharField(max_length=30, blank=True)
    institution_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='UNIVERSITY')
    district = models.ForeignKey(District, on_delete=models.SET_NULL, null=True, blank=True, related_name='institutions')
    location = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class AcademicYear(TimeStampedModel):
    """Academic / membership year (SRS 86)."""

    name = models.CharField(max_length=20, unique=True, help_text='e.g. 2025/2026')
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)
    is_membership_year = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        return self.name

    def clean(self):
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({'end_date': 'End date must be after the start date.'})

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_current:
            AcademicYear.objects.exclude(pk=self.pk).update(is_current=False)
        return self

    @classmethod
    def current(cls):
        return cls.objects.filter(is_current=True, is_active=True).first()


# ---------------------------------------------------------------------------
# Financial policy  (SRS 85 - the 10% must never be hard coded)
# ---------------------------------------------------------------------------

class FinancialPolicy(TimeStampedModel):
    """
    Configurable financial policy such as the Jimbo branch contribution.

    The percentage is data, not code: administrators add a new policy with a
    new effective date instead of changing the system. Historical transactions
    keep the percentage that applied when they were recorded (SRS 85).
    """

    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('INACTIVE', 'Inactive'),
        ('SUPERSEDED', 'Superseded'),
    ]

    name = models.CharField(max_length=150, default='Jimbo Branch Contribution')
    contribution_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=10,
        help_text='Percentage of eligible branch income that belongs to the Jimbo (e.g. 10.00).',
    )
    effective_date = models.DateField(default=date.today, db_index=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='ACTIVE')
    description = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_policies',
    )

    class Meta:
        ordering = ['-effective_date', '-id']
        verbose_name = 'Financial policy'
        verbose_name_plural = 'Financial policies'
        constraints = [
            models.UniqueConstraint(fields=['name', 'effective_date'], name='unique_policy_name_per_date'),
        ]

    def __str__(self):
        return f'{self.name} ({self.contribution_percentage}% from {self.effective_date})'

    def clean(self):
        if self.contribution_percentage is None or not (0 <= self.contribution_percentage <= 100):
            raise ValidationError({'contribution_percentage': 'Percentage must be between 0 and 100.'})

    # -- resolution helpers -------------------------------------------------

    @classmethod
    def default_percentage(cls):
        """Fallback percentage used when no policy row exists yet."""
        return settings.CZDMP['DEFAULT_JIMBO_CONTRIBUTION_PERCENTAGE']

    @classmethod
    def resolve_for_date(cls, on_date=None):
        """
        Return the policy that applies on ``on_date`` (defaults to today).

        The policy with the most recent effective date that is not in the
        future is used, so historical transactions keep their own percentage.
        """
        target = on_date or timezone.localdate()
        if hasattr(target, 'date'):
            target = target.date()
        return (
            cls.objects.filter(status='ACTIVE', effective_date__lte=target)
            .order_by('-effective_date', '-id')
            .first()
        )

    @classmethod
    def current_percentage(cls, on_date=None):
        """Percentage to apply for a transaction recorded on ``on_date``."""
        policy = cls.resolve_for_date(on_date)
        if policy is not None:
            return policy.contribution_percentage
        from decimal import Decimal
        return Decimal(str(cls.default_percentage()))

    @classmethod
    def current(cls):
        return cls.resolve_for_date(timezone.localdate())

    def supersede(self, user=None):
        self.status = 'SUPERSEDED'
        if user is not None:
            self.approved_by = user
        self.save(update_fields=['status', 'approved_by', 'updated_at'])
        return self


# ---------------------------------------------------------------------------
# Public website messages  (SRS 37)
# ---------------------------------------------------------------------------

class ContactMessage(TimeStampedModel):
    """Message submitted through the public "Contact CASFETA" form."""

    STATUS_CHOICES = [
        ('NEW', 'New'),
        ('IN_PROGRESS', 'In progress'),
        ('RESOLVED', 'Resolved'),
    ]

    full_name = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True)
    subject = models.CharField(max_length=200)
    message = models.TextField()
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='NEW')
    handled_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='handled_contact_messages',
    )
    response_notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.subject} ({self.full_name})'
