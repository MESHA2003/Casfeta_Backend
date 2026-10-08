"""
Attendance management (SRS 27, 52, 72).

Attendance can be recorded by scanning the QR ticket of a registration or
manually by an event leader. Statuses: PRESENT, ABSENT, LATE, EXCUSED.
"""

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.models import SoftDeleteModel, TimeStampedModel


class AttendanceSession(TimeStampedModel):
    """
    One attendance taking occasion - normally a part of an event (SRS 27).

    A session is opened by the event leader so that scanning is only possible
    while the register is open.
    """

    event = models.ForeignKey(
        'events.Event', on_delete=models.CASCADE, null=True, blank=True, related_name='attendance_sessions',
    )
    branch = models.ForeignKey(
        'branches.Branch', on_delete=models.CASCADE, null=True, blank=True, related_name='attendance_sessions',
    )
    title = models.CharField(max_length=200, blank=True)
    session_date = models.DateField(default=timezone.localdate, db_index=True)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    is_open = models.BooleanField(default=True)
    opened_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='opened_attendance_sessions',
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-session_date', '-created_at']
        verbose_name = 'Attendance session'
        verbose_name_plural = 'Attendance sessions'

    def __str__(self):
        label = self.title or (self.event.title if self.event_id else 'Attendance session')
        return f'{label} ({self.session_date})'

    def clean(self):
        if not self.event_id and not self.branch_id:
            raise ValidationError('An attendance session must be linked to an event or to a branch.')

    def close(self):
        self.is_open = False
        self.closed_at = timezone.now()
        self.save(update_fields=['is_open', 'closed_at', 'updated_at'])
        return self

    @property
    def present_count(self):
        return self.records.filter(status__in=['PRESENT', 'LATE']).count()

    @property
    def total_count(self):
        return self.records.count()


class AttendanceRecord(TimeStampedModel):
    """
    Attendance of one person in one session (SRS 27).

    Stores the member, event, date, time, branch and attendance status, plus
    whether it was captured by QR scan or manually.
    """

    STATUS_CHOICES = [
        ('PRESENT', 'Yupo (Present)'),
        ('ABSENT', 'Hayupo (Absent)'),
        ('LATE', 'Amechelewa (Late)'),
        ('EXCUSED', 'Ameidhinishwa kutokuwepo (Excused)'),
    ]

    METHOD_CHOICES = [
        ('QR', 'QR scan'),
        ('MANUAL', 'Manual entry'),
        ('SELF', 'Self check-in'),
    ]

    session = models.ForeignKey(
        AttendanceSession, on_delete=models.CASCADE, null=True, blank=True, related_name='records',
    )
    event = models.ForeignKey(
        'events.Event', on_delete=models.CASCADE, null=True, blank=True, related_name='attendance_records',
    )
    registration = models.ForeignKey(
        'events.EventRegistration', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='attendance_records',
    )
    member = models.ForeignKey(
        'members.Member', on_delete=models.CASCADE, null=True, blank=True, related_name='attendance_records',
    )
    branch = models.ForeignKey(
        'branches.Branch', on_delete=models.CASCADE, null=True, blank=True, related_name='attendance_records',
    )
    attendance_date = models.DateField(default=timezone.localdate, db_index=True)
    check_in_time = models.DateTimeField(null=True, blank=True)
    check_out_time = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PRESENT', db_index=True)
    method = models.CharField(max_length=10, choices=METHOD_CHOICES, default='QR')
    recorded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='recorded_attendance',
    )
    remarks = models.TextField(blank=True)
    guest_name = models.CharField(max_length=150, blank=True)

    class Meta:
        ordering = ['-attendance_date', '-created_at']
        verbose_name = 'Attendance record'
        verbose_name_plural = 'Attendance records'
        constraints = [
            models.UniqueConstraint(
                fields=['session', 'member'], name='unique_member_per_session',
                condition=models.Q(member__isnull=False),
            ),
        ]
        indexes = [models.Index(fields=['branch', 'attendance_date', 'status'])]

    def __str__(self):
        who = self.member.full_name if self.member_id else (self.guest_name or 'Guest')
        return f'{who} - {self.get_status_display()} ({self.attendance_date})'

    @property
    def person_name(self):
        if self.member_id:
            return self.member.full_name
        return self.guest_name or 'Guest'

    @property
    def was_present(self):
        return self.status in {'PRESENT', 'LATE'}

