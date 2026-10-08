"""
Ministry management (SRS 24, 52).

CASFETA Zanzibar ministries (Evangelism, Prayer, Discipleship, Academic,
Leadership, Worship, Media, Missions, Community Outreach, Talent Development)
can exist at Jimbo level or inside a branch.
"""

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models

from core.models import SoftDeleteModel, TimeStampedModel


class Ministry(SoftDeleteModel):
    """A ministry / department of CASFETA Zanzibar."""

    LEVEL_CHOICES = [('JIMBO', 'Jimbo'), ('BRANCH', 'Tawi (branch)')]

    name = models.CharField(max_length=150)
    code = models.CharField(max_length=30, blank=True)
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, default='BRANCH')
    branch = models.ForeignKey(
        'branches.Branch', on_delete=models.CASCADE, null=True, blank=True, related_name='ministries',
    )
    leader = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='led_ministries',
    )
    description = models.TextField(blank=True)
    objectives = models.TextField(blank=True, help_text='Malengo ya huduma (objectives).')
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_ministries',
    )

    class Meta:
        ordering = ['level', 'name']
        verbose_name_plural = 'Ministries'
        constraints = [
            models.UniqueConstraint(fields=['name', 'branch'], name='unique_ministry_name_per_branch'),
        ]

    def __str__(self):
        scope = self.branch.name if self.branch_id else 'Jimbo'
        return f'{self.name} ({scope})'

    def clean(self):
        if self.level == 'BRANCH' and not self.branch_id:
            raise ValidationError({'branch': 'A branch ministry must be linked to a branch.'})
        if self.level == 'JIMBO' and self.branch_id:
            raise ValidationError({'branch': 'A Jimbo level ministry must not be linked to a branch.'})

    @property
    def member_count(self):
        return self.memberships.filter(is_active=True).count()


class MinistryMembership(TimeStampedModel):
    """Membership of a person in a ministry (SRS 24)."""

    ROLE_CHOICES = [
        ('MEMBER', 'Mwanachama (Member)'),
        ('ASSISTANT', 'Msaidizi (Assistant)'),
        ('DEPUTY', 'Naibu (Deputy)'),
        ('LEADER', 'Kiongozi (Leader)'),
    ]

    ministry = models.ForeignKey(Ministry, on_delete=models.CASCADE, related_name='memberships')
    member = models.ForeignKey('members.Member', on_delete=models.CASCADE, related_name='ministry_memberships')
    role_in_ministry = models.CharField(max_length=12, choices=ROLE_CHOICES, default='MEMBER')
    joined_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['ministry', 'role_in_ministry']
        constraints = [
            models.UniqueConstraint(fields=['ministry', 'member'], name='unique_member_per_ministry'),
        ]

    def __str__(self):
        return f'{self.member} in {self.ministry.name}'

