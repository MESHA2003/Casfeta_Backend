"""
Audit trail models (SRS 18, 48, 83 Rule 13).

Records answer WHO / WHAT / WHEN / WHERE / OLD VALUE / NEW VALUE for every
important action in the platform. Financial records are never silently
deleted; deactivations, reversals and approvals are all captured here.
"""

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class AuditLog(models.Model):
    ACTIONS = [
        ('LOGIN', 'Login'),
        ('LOGIN_FAILED', 'Failed login'),
        ('LOGOUT', 'Logout'),
        ('CREATE', 'Create'),
        ('UPDATE', 'Update'),
        ('DEACTIVATE', 'Deactivate'),
        ('DELETE', 'Delete'),
        ('APPROVE', 'Approve'),
        ('REJECT', 'Reject'),
        ('PAYMENT', 'Payment'),
        ('REVERSAL', 'Reversal'),
        ('RECONCILE', 'Reconcile'),
        ('ROLE_CHANGE', 'Role change'),
        ('PASSWORD_CHANGE', 'Password change'),
        ('REPORT_SUBMISSION', 'Report submission'),
        ('FINANCIAL_APPROVAL', 'Financial approval'),
        ('PUBLISH', 'Publish'),
        ('ATTENDANCE_SCAN', 'Attendance scan'),
        ('EXPORT', 'Export'),
        ('SYSTEM', 'System action'),
    ]

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs')
    username_snapshot = models.CharField(max_length=150, blank=True)
    role_snapshot = models.CharField(max_length=150, blank=True, help_text='Roles held when the action happened.')

    action = models.CharField(max_length=30, choices=ACTIONS, db_index=True)
    entity = models.CharField(max_length=120, blank=True, db_index=True)
    entity_id = models.CharField(max_length=64, blank=True)
    branch = models.ForeignKey(
        'branches.Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs',
    )

    description = models.TextField(blank=True)
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)
    reason = models.TextField(blank=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    request_path = models.CharField(max_length=255, blank=True)
    method = models.CharField(max_length=10, blank=True)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-created_at', '-id']
        verbose_name = 'Audit log'
        verbose_name_plural = 'Audit logs'
        indexes = [
            models.Index(fields=['entity', 'entity_id']),
            models.Index(fields=['action', 'created_at']),
        ]

    def __str__(self):
        who = self.username_snapshot or 'system'
        return f'{self.created_at:%Y-%m-%d %H:%M} {who} {self.action} {self.entity}#{self.entity_id}'

    @property
    def summary(self):
        """Human readable one liner used by dashboards and reports."""
        return f'{self.get_action_display()} on {self.entity or "record"} {self.entity_id}'.strip()
