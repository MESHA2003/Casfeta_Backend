"""
Prayer request system (SRS 33, 83 Rule 11).

Privacy is mandatory: a prayer request is private by default and never
becomes public unless the member explicitly gives permission.
"""

from django.contrib.auth.models import User
from django.db import models

from core.models import TimeStampedModel


class PrayerRequest(TimeStampedModel):
    """
    Private prayer request (SRS 33, 83 Rule 11).

    Privacy is mandatory: a request stays private unless the member
    explicitly allows publication.
    """

    CATEGORY_CHOICES = [
        ('ACADEMIC', 'Academic (Taaluma)'),
        ('SPIRITUAL', 'Spiritual (Kiroho)'),
        ('FAMILY', 'Family (Familia)'),
        ('FINANCIAL', 'Financial (Fedha)'),
        ('PERSONAL', 'Personal (Binafsi)'),
        ('CAREER', 'Career (Kazi)'),
        ('HEALTH', 'Health (Afya)'),
        ('OTHER', 'Other (Nyingine)'),
    ]

    STATUS_CHOICES = [
        ('OPEN', 'Open'),
        ('IN_PROGRESS', 'In prayer'),
        ('ANSWERED', 'Answered'),
        ('CLOSED', 'Closed'),
    ]

    reference = models.CharField(max_length=30, unique=True, blank=True)
    member = models.ForeignKey(
        'members.Member', on_delete=models.CASCADE, null=True, blank=True, related_name='prayer_requests',
    )
    user = models.ForeignKey(
        'auth.User', on_delete=models.CASCADE, null=True, blank=True, related_name='prayer_requests',
    )
    branch = models.ForeignKey(
        'branches.Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='prayer_requests',
    )
    category = models.CharField(max_length=12, choices=CATEGORY_CHOICES, default='PERSONAL')
    subject = models.CharField(max_length=200)
    details = models.TextField()
    is_private = models.BooleanField(default=True, help_text='SRS 33 / Rule 11: private by default.')
    allow_public = models.BooleanField(default=False, help_text='Only when the member explicitly allows it.')
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='OPEN')
    assigned_to = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='prayer_assignments',
    )
    follow_up_notes = models.TextField(blank=True)
    answered_note = models.TextField(blank=True)
    is_team_request = models.BooleanField(default=False, help_text='Prayer team only (never public).')

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Prayer request'
        verbose_name_plural = 'Prayer requests'

    def __str__(self):
        return f'{self.reference or "PR"} - {self.subject}'

    def save(self, *args, **kwargs):
        if not self.reference:
            from django.utils import timezone as tz
            year = tz.localtime().year
            count = PrayerRequest.objects.filter(reference__startswith=f'PR-{year}-').count() + 1
            self.reference = f'PR-{year}-{count:05d}'
        super().save(*args, **kwargs)

    @property
    def is_visible_to_member(self):
        return True

    @property
    def is_publicly_visible(self):
        """Only when the member explicitly allowed publication (SRS 33)."""
        return (not self.is_private) and self.allow_public and self.status in {'ANSWERED', 'CLOSED'}


class PrayerFollowUp(TimeStampedModel):
    """Follow-up entry recorded by the prayer / pastoral team (SRS 33)."""

    prayer_request = models.ForeignKey(
        PrayerRequest, on_delete=models.CASCADE, related_name='follow_ups',
    )
    handled_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='prayer_follow_ups',
    )
    note = models.TextField()
    is_private = models.BooleanField(default=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Prayer follow-up'
        verbose_name_plural = 'Prayer follow-ups'

    def __str__(self):
        return f'Follow-up {self.prayer_request_id}'

