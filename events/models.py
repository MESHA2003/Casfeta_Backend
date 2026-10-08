"""
Event management and registration (SRS 25, 26, 52, 86).

Events can belong to a branch or to the Jimbo, may be linked to a ministry,
and optionally require registration with a fee. Registration produces a
registration id and a QR ticket used for attendance (SRS 26, 27, 72).
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.models import SoftDeleteModel, TimeStampedModel
from core.qr import generate_token


class EventCategory(TimeStampedModel):
    """Configurable event category (SRS 86)."""

    name = models.CharField(max_length=100, unique=True)
    name_sw = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Event category'
        verbose_name_plural = 'Event categories'

    def __str__(self):
        return self.name

    @classmethod
    def seed_defaults(cls):
        """Standard CASFETA event categories (SRS 25)."""
        defaults = [
            'Conference', 'Seminar', 'Bible Study', 'Fellowship', 'Evangelism Campaign',
            'Leadership Training', 'Academic Event', 'Outreach Programme', 'Worship Night',
            'Sports & Talent',
        ]
        created = 0
        for name in defaults:
            _, was_created = cls.objects.get_or_create(name=name)
            created += 1 if was_created else 0
        return created


class Event(SoftDeleteModel):
    """An event organised by the Jimbo, a branch or a ministry (SRS 25)."""

    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('PUBLISHED', 'Published'),
        ('ONGOING', 'Ongoing'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
        ('ARCHIVED', 'Archived'),
    ]

    LEVEL_CHOICES = [('JIMBO', 'Jimbo'), ('BRANCH', 'Tawi (branch)'), ('MINISTRY', 'Huduma (ministry)')]

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    category = models.ForeignKey(
        EventCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='events',
    )
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, default='BRANCH')
    branch = models.ForeignKey(
        'branches.Branch', on_delete=models.CASCADE, null=True, blank=True, related_name='events',
    )
    ministry = models.ForeignKey(
        'ministries.Ministry', on_delete=models.SET_NULL, null=True, blank=True, related_name='events',
    )
    description = models.TextField(blank=True)
    objectives = models.TextField(blank=True)

    start_date = models.DateField(db_index=True)
    end_date = models.DateField(null=True, blank=True)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    venue = models.CharField(max_length=200, blank=True)
    is_online = models.BooleanField(default=False)
    online_link = models.URLField(blank=True, default='')

    organizer = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='organized_events',
    )
    organizer_name = models.CharField(max_length=150, blank=True, help_text='Used for external organisers.')
    capacity = models.PositiveIntegerField(null=True, blank=True)

    requires_registration = models.BooleanField(default=False)
    fee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    currency = models.CharField(max_length=10, default='TZS')
    poster = models.ImageField(upload_to='events/posters/', blank=True, null=True)

    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='DRAFT', db_index=True)
    is_public = models.BooleanField(default=True, help_text='Show the event on the public website (SRS 37).')

    class Meta:
        ordering = ['-start_date', '-start_time']
        indexes = [models.Index(fields=['status', 'start_date'])]

    def __str__(self):
        return f'{self.title} ({self.start_date})'

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify

            base = slugify(self.title)[:200] or 'event'
            slug = base
            counter = 1
            while Event.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                counter += 1
                slug = f'{base}-{counter}'
            self.slug = slug
        if self.fee and self.fee > 0:
            self.requires_registration = True
        return super().save(*args, **kwargs)

    def clean(self):
        if self.level == 'BRANCH' and not self.branch_id:
            raise ValidationError({'branch': 'A branch event must be linked to a branch.'})
        if self.end_date and self.end_date < self.start_date:
            raise ValidationError({'end_date': 'The end date must be on or after the start date.'})

    @property
    def is_upcoming(self):
        return self.start_date >= timezone.localdate() and self.status in {'PUBLISHED', 'ONGOING'}

    @property
    def is_full(self):
        if not self.capacity:
            return False
        return self.registrations.filter(status__in=['REGISTERED', 'ATTENDED']).count() >= self.capacity

    @property
    def registration_count(self):
        return self.registrations.filter(status__in=['REGISTERED', 'ATTENDED']).count()

    @property
    def is_fee_bearing(self):
        return bool(self.fee and self.fee > 0)

class EventRegistration(TimeStampedModel):
    """
    A member's registration for an event (SRS 26).

    The system generates a registration id, a QR ticket and a confirmation;
    the QR ticket is what the attendance scanning uses (SRS 27, 72).
    """

    STATUS_CHOICES = [
        ('REGISTERED', 'Registered'),
        ('ATTENDED', 'Attended'),
        ('CANCELLED', 'Cancelled'),
        ('WAITLISTED', 'Waitlisted'),
        ('NO_SHOW', 'No show'),
    ]

    PAYMENT_STATUS_CHOICES = [
        ('NOT_REQUIRED', 'Not required'),
        ('PENDING', 'Pending'),
        ('PAID', 'Paid'),
        ('WAIVED', 'Waived'),
    ]

    registration_id = models.CharField(max_length=40, unique=True, blank=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='registrations')
    member = models.ForeignKey(
        'members.Member', on_delete=models.CASCADE, null=True, blank=True, related_name='event_registrations',
    )
    guest_name = models.CharField(max_length=150, blank=True, help_text='For non-member guests.')
    guest_phone = models.CharField(max_length=30, blank=True)
    guest_email = models.EmailField(blank=True, default='')

    branch = models.ForeignKey(
        'branches.Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='event_registrations',
    )
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='REGISTERED', db_index=True)
    payment_status = models.CharField(
        max_length=15, choices=PAYMENT_STATUS_CHOICES, default='NOT_REQUIRED',
    )
    fee_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    payment_reference = models.CharField(max_length=80, blank=True)

    qr_token = models.CharField(max_length=64, unique=True, blank=True)
    attended_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['event', 'member'], name='unique_registration_per_member'),
        ]

    def __str__(self):
        who = self.member.full_name if self.member_id else (self.guest_name or 'Guest')
        return f'{self.registration_id} - {who} @ {self.event.title}'

    def save(self, *args, **kwargs):
        if not self.qr_token:
            self.qr_token = generate_token()
        if not self.registration_id:
            year = timezone.localdate().year
            prefix = f'REG-{year}-'
            count = EventRegistration.objects.filter(registration_id__startswith=prefix).count() + 1
            candidate = f'{prefix}{count:06d}'
            while EventRegistration.objects.filter(registration_id=candidate).exists():
                count += 1
                candidate = f'{prefix}{count:06d}'
            self.registration_id = candidate
        if not self.fee_amount and self.event_id:
            self.fee_amount = self.event.fee or Decimal('0.00')
        if self.fee_amount and self.fee_amount > 0 and self.payment_status == 'NOT_REQUIRED':
            self.payment_status = 'PENDING'
        return super().save(*args, **kwargs)

    @property
    def registrant_name(self):
        if self.member_id:
            return self.member.full_name
        return self.guest_name or 'Guest'

    def mark_attended(self):
        self.status = 'ATTENDED'
        self.attended_at = timezone.now()
        self.save(update_fields=['status', 'attended_at', 'updated_at'])
        return self

