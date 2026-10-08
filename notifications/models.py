"""
Notification centre and announcements (SRS 11, 35, 36, 44, 59, 60, 69).

Notifications are the in-system channel; email, SMS and WhatsApp are optional
integrations that use the same templates (SRS 44).
"""

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

from core.models import SoftDeleteModel, TimeStampedModel


class NotificationTemplate(TimeStampedModel):
    """
    Reusable message template (SRS 44).

    Templates avoid typing the same message again for every branch; the body
    supports ``{placeholders}`` filled in by ``notifications.services``.
    """

    CHANNEL_CHOICES = [
        ('IN_SYSTEM', 'In-system'),
        ('EMAIL', 'Email'),
        ('SMS', 'SMS'),
        ('WHATSAPP', 'WhatsApp'),
    ]

    code = models.CharField(max_length=80, unique=True)
    name = models.CharField(max_length=150)
    channel = models.CharField(max_length=12, choices=CHANNEL_CHOICES, default='IN_SYSTEM')
    language = models.CharField(max_length=5, default='sw', choices=[('sw', 'Kiswahili'), ('en', 'English')])
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField()
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['code']
        verbose_name = 'Notification template'
        verbose_name_plural = 'Notification templates'

    def __str__(self):
        return f'{self.code} ({self.get_channel_display()})'

    def render(self, context=None):
        context = context or {}
        subject = self.subject
        body = self.body
        for key, value in context.items():
            subject = subject.replace('{' + key + '}', str(value))
            body = body.replace('{' + key + '}', str(value))
        return subject, body


class Notification(TimeStampedModel):
    """A message for one user (SRS 36, 69). Unread notifications are flagged."""

    CATEGORY_CHOICES = [
        ('MEMBERSHIP', 'Membership'),
        ('EVENT', 'Event'),
        ('ANNOUNCEMENT', 'Announcement'),
        ('FINANCE', 'Financial'),
        ('REPORT', 'Report'),
        ('LEADERSHIP', 'Leadership'),
        ('PRAYER', 'Prayer request'),
        ('CERTIFICATE', 'Certificate'),
        ('SYSTEM', 'System alert'),
    ]

    PRIORITY_CHOICES = [('LOW', 'Low'), ('NORMAL', 'Normal'), ('HIGH', 'High'), ('URGENT', 'Urgent')]

    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    category = models.CharField(max_length=15, choices=CATEGORY_CHOICES, default='SYSTEM', db_index=True)
    priority = models.CharField(max_length=8, choices=PRIORITY_CHOICES, default='NORMAL')
    channel = models.CharField(max_length=12, default='IN_SYSTEM')

    branch = models.ForeignKey(
        'branches.Branch', on_delete=models.CASCADE, null=True, blank=True, related_name='notifications',
    )
    related_entity = models.CharField(max_length=80, blank=True)
    related_object_id = models.CharField(max_length=64, blank=True)
    action_url = models.CharField(max_length=255, blank=True, help_text='Frontend route to open.')
    payload = models.JSONField(null=True, blank=True)

    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    email_sent = models.BooleanField(default=False)
    sms_sent = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['recipient', 'is_read'])]

    def __str__(self):
        return f'{self.title} -> {self.recipient.username}'

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at', 'updated_at'])
        return self

class Announcement(SoftDeleteModel):
    """
    Announcement published by the Jimbo or by a branch (SRS 35, 67).

    Audience targeting: all members, a specific branch, a specific ministry,
    leaders, cashiers or finance officers. A branch may only publish to users
    inside its own scope.
    """

    AUDIENCE_CHOICES = [
        ('ALL_MEMBERS', 'All members'),
        ('BRANCH', 'Specific branch'),
        ('MINISTRY', 'Specific ministry'),
        ('LEADERS', 'Leaders'),
        ('CASHIERS', 'Cashiers'),
        ('FINANCE', 'Finance officers'),
        ('PUBLIC', 'Public (website)'),
    ]

    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('SCHEDULED', 'Scheduled'),
        ('PUBLISHED', 'Published'),
        ('ARCHIVED', 'Archived'),
    ]

    title = models.CharField(max_length=200)
    summary = models.CharField(max_length=300, blank=True)
    body = models.TextField()
    audience = models.CharField(max_length=15, choices=AUDIENCE_CHOICES, default='ALL_MEMBERS')
    branch = models.ForeignKey(
        'branches.Branch', on_delete=models.CASCADE, null=True, blank=True, related_name='announcements',
    )
    ministry = models.ForeignKey(
        'ministries.Ministry', on_delete=models.SET_NULL, null=True, blank=True, related_name='announcements',
    )
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='DRAFT', db_index=True)
    publish_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_public = models.BooleanField(default=False, help_text='Also show this announcement on the public website.')
    attachment = models.FileField(upload_to='announcements/', blank=True, null=True)
    posted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='announcements',
    )
    posted_by_name = models.CharField(max_length=150, blank=True)
    views_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-publish_at', '-created_at']

    def __str__(self):
        return self.title

    @property
    def is_live(self):
        now = timezone.now()
        if self.status != 'PUBLISHED':
            return False
        if self.publish_at and self.publish_at > now:
            return False
        if self.expires_at and self.expires_at < now:
            return False
        return True

    def publish(self, user=None):
        self.status = 'PUBLISHED'
        if not self.publish_at:
            self.publish_at = timezone.now()
        if user is not None and getattr(user, 'is_authenticated', False):
            self.posted_by = user
        self.save(update_fields=['status', 'publish_at', 'posted_by', 'updated_at'])
        return self


class NotificationPreference(TimeStampedModel):
    """Per-user channel preferences (SRS 44)."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='notification_preference')
    in_system = models.BooleanField(default=True)
    email = models.BooleanField(default=False)
    sms = models.BooleanField(default=False)
    whatsapp = models.BooleanField(default=False)
    event_reminders = models.BooleanField(default=True)
    finance_alerts = models.BooleanField(default=True)
    report_reminders = models.BooleanField(default=True)
    announcements = models.BooleanField(default=True)

    def __str__(self):
        return f'Preferences of {self.user.username}'

