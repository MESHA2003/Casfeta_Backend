"""
Accounts: users, roles and role assignments (SRS 6, 7, 45).

CZDMP keeps Django's ``auth.User`` as the login identity (so the existing
CASFETA data and admin keep working) and adds:

* ``Role``            - the configurable role catalogue (SRS 6).
* ``RoleAssignment``  - which role a user holds, optionally within one branch,
                        which is what makes branch level restrictions possible
                        (SRS 79, 83 Rule 3/4).
* ``UserProfile``     - personal data, preferences and primary branch.
"""

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

from core.models import TimeStampedModel
from core import roles as role_codes


class Role(TimeStampedModel):
    """A role from the CZDMP role catalogue (SRS 6, 7)."""

    SCOPE_CHOICES = [
        ('SYSTEM', 'System'),
        ('JIMBO', 'Jimbo'),
        ('BRANCH', 'Branch'),
        ('MINISTRY', 'Ministry'),
        ('SELF', 'Self'),
        ('PUBLIC', 'Public'),
    ]

    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    name_sw = models.CharField(max_length=100, blank=True, verbose_name='Jina kwa Kiswahili')
    scope = models.CharField(max_length=15, choices=SCOPE_CHOICES, default='BRANCH')
    level = models.PositiveSmallIntegerField(
        default=0, help_text='Hierarchy level used for "at least this role" checks.',
    )
    description = models.TextField(blank=True)
    permission_codes = models.JSONField(
        default=list, blank=True,
        help_text='Optional fine grained permission codes granted by this role.',
    )
    is_active = models.BooleanField(default=True)
    is_system = models.BooleanField(
        default=False, help_text='System roles cannot be deleted, only deactivated.',
    )

    class Meta:
        ordering = ['-level', 'name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.level:
            self.level = role_codes.level_of(self.code)
        return super().save(*args, **kwargs)

    @property
    def is_branch_scoped(self):
        return self.scope in {'BRANCH', 'MINISTRY', 'SELF'}

    def delete(self, *args, **kwargs):
        if self.is_system:
            raise ValidationError('System roles cannot be deleted; deactivate them instead.')
        return super().delete(*args, **kwargs)


class RoleAssignment(TimeStampedModel):
    """
    Grants a role to a user, optionally scoped to a branch or ministry.

    Branch scoped roles (cashier, secretary, branch leader, member) must carry a
    branch: that is what restricts a Branch A cashier from Branch B data
    (SRS 79, 83 Rule 4).
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='role_assignments')
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name='assignments')
    branch = models.ForeignKey(
        'branches.Branch', on_delete=models.CASCADE, null=True, blank=True, related_name='role_assignments',
    )
    ministry = models.ForeignKey(
        'ministries.Ministry', on_delete=models.CASCADE, null=True, blank=True, related_name='role_assignments',
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    assigned_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='role_assignments_made',
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'role', 'branch', 'ministry'],
                name='unique_role_assignment_per_scope',
            ),
        ]

    def __str__(self):
        scope = self.branch.name if self.branch_id else (self.ministry.name if self.ministry_id else 'Jimbo')
        return f'{self.user.username} - {self.role.name} ({scope})'

    def clean(self):
        if self.role_id and self.role.is_branch_scoped and not self.branch_id:
            raise ValidationError({'branch': 'This role must be linked to a branch.'})
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({'end_date': 'End date must be after the start date.'})

    @property
    def is_current(self):
        from django.utils import timezone

        today = timezone.localdate()
        if not self.is_active:
            return False
        if self.start_date and self.start_date > today:
            return False
        if self.end_date and self.end_date < today:
            return False
        return True


class UserProfile(TimeStampedModel):
    """Personal data and preferences of a platform user (SRS 6.2, 46)."""

    GENDER_CHOICES = [('MALE', 'Mwanaume (Male)'), ('FEMALE', 'Mwanamke (Female)')]
    LANGUAGE_CHOICES = [('sw', 'Kiswahili'), ('en', 'English')]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='user_profile')
    phone = models.CharField(max_length=30, blank=True)
    alternative_phone = models.CharField(max_length=30, blank=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    photo = models.ImageField(upload_to='user_photos/', blank=True, null=True)
    district = models.ForeignKey(
        'core.District', on_delete=models.SET_NULL, null=True, blank=True, related_name='user_profiles',
    )
    address = models.CharField(max_length=255, blank=True)
    primary_branch = models.ForeignKey(
        'branches.Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='primary_users',
    )
    preferred_language = models.CharField(max_length=5, choices=LANGUAGE_CHOICES, default='sw')
    is_phone_verified = models.BooleanField(default=False)
    is_email_verified = models.BooleanField(default=False)
    must_change_password = models.BooleanField(default=False)
    password_changed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = 'User profile'
        verbose_name_plural = 'User profiles'

    def __str__(self):
        return f'Profile of {self.user.username}'

    @property
    def full_name(self):
        name = self.user.get_full_name()
        return name or self.user.username

    @property
    def role_codes(self):
        return [assignment.role.code for assignment in self.user.role_assignments.filter(is_active=True)]


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Every user gets a profile row automatically."""
    if created:
        UserProfile.objects.get_or_create(user=instance)
