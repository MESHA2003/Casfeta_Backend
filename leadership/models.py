"""
Leadership management (SRS 23, 65, 66).

Positions (President, Secretary, Cashier, Ministry Leader...) are held by a
person for a term. When a term ends the record is kept as history - the
succession flow is ACTIVE -> TERM COMPLETED -> FORMER LEADER (SRS 65).
"""

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.models import SoftDeleteModel, TimeStampedModel


class LeadershipPosition(TimeStampedModel):
    """A leadership position inside the Jimbo, a branch or a ministry."""

    LEVEL_CHOICES = [('JIMBO', 'Jimbo'), ('BRANCH', 'Tawi (branch)'), ('MINISTRY', 'Huduma (ministry)')]

    title = models.CharField(max_length=120)
    title_sw = models.CharField(max_length=120, blank=True, verbose_name='Cheo kwa Kiswahili')
    code = models.CharField(max_length=40, blank=True)
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, default='BRANCH')
    rank = models.PositiveSmallIntegerField(default=10, help_text='Order used when displaying leadership.')
    description = models.TextField(blank=True)
    is_finance_position = models.BooleanField(default=False)
    is_public = models.BooleanField(
        default=True, help_text='Show this position in the public leadership directory (SRS 66).',
    )
    is_hod = models.BooleanField(default=False, verbose_name='Head of department')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['level', 'rank', 'title']
        constraints = [
            models.UniqueConstraint(fields=['title', 'level'], name='unique_position_per_level'),
        ]

    def __str__(self):
        return f'{self.title} ({self.get_level_display()})'

    def clean(self):
        if self.level == 'MINISTRY' and not self.is_hod:
            # Ministry leadership positions are heads of department by default.
            self.is_hod = True


class LeadershipTerm(SoftDeleteModel):
    """
    One person serving in one position for a period (SRS 23).

    Historical records stay available forever (SRS 65).
    """

    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('TERM_COMPLETED', 'Term completed'),
        ('FORMER', 'Former leader'),
        ('SUSPENDED', 'Suspended'),
        ('PENDING', 'Pending appointment'),
    ]

    APPOINTMENT_CHOICES = [
        ('APPOINTED', 'Appointed'),
        ('ELECTED', 'Elected'),
        ('ACTING', 'Acting'),
        ('CARE_TAKER', 'Caretaker'),
    ]

    position = models.ForeignKey(LeadershipPosition, on_delete=models.PROTECT, related_name='terms')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='leadership_terms')
    branch = models.ForeignKey(
        'branches.Branch', on_delete=models.CASCADE, null=True, blank=True, related_name='leadership_terms',
    )
    ministry = models.ForeignKey(
        'ministries.Ministry', on_delete=models.CASCADE, null=True, blank=True, related_name='leadership_terms',
    )
    term_name = models.CharField(max_length=60, blank=True, help_text='e.g. 2026-2028')
    term_start = models.DateField()
    term_end = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='ACTIVE')
    appointment_status = models.CharField(max_length=12, choices=APPOINTMENT_CHOICES, default='APPOINTED')
    is_public = models.BooleanField(default=True, help_text='Include in the public leadership directory.')
    appointed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='appointments_made',
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['position__rank', '-term_start']
        verbose_name = 'Leadership term'
        verbose_name_plural = 'Leadership terms'
        constraints = [
            models.UniqueConstraint(
                fields=['position', 'user', 'branch', 'ministry', 'term_start'],
                name='unique_leadership_term',
            ),
        ]

    def __str__(self):
        scope = self.branch.code if self.branch_id else (self.ministry.name if self.ministry_id else 'Jimbo')
        return f'{self.position.title} - {self.user.get_full_name() or self.user.username} ({scope})'

    def clean(self):
        if self.position_id:
            if self.position.level == 'BRANCH' and not self.branch_id:
                raise ValidationError({'branch': 'A branch position must be linked to a branch.'})
            if self.position.level == 'MINISTRY' and not self.ministry_id:
                raise ValidationError({'ministry': 'A ministry position must be linked to a ministry.'})
        if self.term_end and self.term_start and self.term_end < self.term_start:
            raise ValidationError({'term_end': 'The end of the term must be after its start.'})

    @property
    def is_current(self):
        if self.status != 'ACTIVE':
            return False
        if self.term_start and self.term_start > timezone.localdate():
            return False
        if self.term_end and self.term_end < timezone.localdate():
            return False
        return True

    def complete_term(self, user=None, notes=''):
        """ACTIVE -> TERM COMPLETED -> FORMER LEADER (SRS 65)."""
        self.status = 'TERM_COMPLETED'
        if not self.term_end:
            self.term_end = timezone.localdate()
        if notes:
            self.notes = (self.notes + '\n' + notes).strip()
        self.save(update_fields=['status', 'term_end', 'notes', 'updated_at'])
        return self

    def mark_former(self):
        self.status = 'FORMER'
        self.save(update_fields=['status', 'updated_at'])
        return self

