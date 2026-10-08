"""
Testimony system (SRS 34).

Only APPROVED and PUBLISHED testimonies appear on the public website; the
workflow is PENDING -> UNDER REVIEW -> APPROVED/PUBLISHED, or REJECTED.
"""

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

from core.models import SoftDeleteModel, TimeStampedModel


class Testimony(SoftDeleteModel):
    """A member's testimony submitted for review (SRS 34)."""

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('UNDER_REVIEW', 'Under review'),
        ('APPROVED', 'Approved'),
        ('PUBLISHED', 'Published'),
        ('REJECTED', 'Rejected'),
    ]

    reference = models.CharField(max_length=30, unique=True, blank=True)
    member = models.ForeignKey(
        'members.Member', on_delete=models.CASCADE, null=True, blank=True, related_name='testimonies',
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, null=True, blank=True, related_name='testimonies',
    )
    branch = models.ForeignKey(
        'branches.Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='testimonies',
    )
    title = models.CharField(max_length=200)
    body = models.TextField()
    category = models.CharField(
        max_length=20, blank=True,
        choices=[('SALVATION', 'Salvation'), ('HEALING', 'Healing'), ('ACADEMIC', 'Academic'),
                 ('FINANCIAL', 'Financial'), ('FAMILY', 'Family'), ('LEADERSHIP', 'Leadership'),
                 ('OTHER', 'Other')],
    )
    allow_public = models.BooleanField(default=True, help_text='Show on the public website when published.')
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='PENDING', db_index=True)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_testimonies',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    is_featured = models.BooleanField(default=False)
    photo = models.ImageField(upload_to='testimonies/', blank=True, null=True)

    class Meta:
        ordering = ['-published_at', '-created_at']
        verbose_name = 'Testimony'
        verbose_name_plural = 'Testimonies'

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.reference:
            year = timezone.localtime().year
            count = Testimony.objects.filter(reference__startswith=f'TST-{year}-').count() + 1
            self.reference = f'TST-{year}-{count:05d}'
        super().save(*args, **kwargs)

    @property
    def is_publicly_visible(self):
        """Only approved and published testimonies appear publicly (SRS 34)."""
        return self.status == 'PUBLISHED' and self.allow_public and self.is_active

    def review(self, user, status='APPROVED', notes=''):
        if status not in dict(self.STATUS_CHOICES):
            raise ValueError(f'Unknown testimony status: {status}')
        self.status = status
        self.reviewed_by = user
        self.reviewed_at = timezone.now()
        self.review_notes = notes or self.review_notes
        if status == 'PUBLISHED':
            self.published_at = timezone.now()
        self.save(update_fields=[
            'status', 'reviewed_by', 'reviewed_at', 'review_notes', 'published_at', 'updated_at',
        ])
        return self

