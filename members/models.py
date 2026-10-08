"""
Membership management (SRS 20, 21, 52, 64).

Member statuses: PENDING, ACTIVE, INACTIVE, SUSPENDED, TRANSFERRED, ALUMNI.
Each member belongs to one branch (SRS 83 Rule 1) and carries a unique
member id plus a QR token for the digital membership card (SRS 21).
"""

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.models import SoftDeleteModel, TimeStampedModel
from core.qr import generate_token


class Member(SoftDeleteModel):
    """An approved CASFETA member (SRS 20)."""

    STATUS_CHOICES = [
        ('PENDING', 'Inasubiri (Pending)'),
        ('ACTIVE', 'Hai (Active)'),
        ('INACTIVE', 'Haitumiki (Inactive)'),
        ('SUSPENDED', 'Imesimamishwa (Suspended)'),
        ('TRANSFERRED', 'Amehamishwa (Transferred)'),
        ('ALUMNI', 'Alumni'),
    ]

    GENDER_CHOICES = [('MALE', 'Mwanaume (Male)'), ('FEMALE', 'Mwanamke (Female)')]

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, null=True, blank=True, related_name='member_profile',
    )
    member_id = models.CharField(
        max_length=30, unique=True, blank=True, help_text='Digital membership id, e.g. CZ-2026-000145.',
    )

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    other_names = models.CharField(max_length=150, blank=True)
    email = models.EmailField(blank=True, default='')
    phone = models.CharField(max_length=30)
    alternative_phone = models.CharField(max_length=30, blank=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES)
    date_of_birth = models.DateField(null=True, blank=True)
    national_id = models.CharField(max_length=50, blank=True)
    photo = models.ImageField(upload_to='member_photos/', blank=True, null=True)

    branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT, related_name='members')
    institution = models.ForeignKey(
        'core.Institution', on_delete=models.SET_NULL, null=True, blank=True, related_name='members',
    )
    course_programme = models.CharField(max_length=150, blank=True, help_text='Programme / course of study.')
    study_year = models.PositiveSmallIntegerField(null=True, blank=True)
    academic_year = models.ForeignKey(
        'core.AcademicYear', on_delete=models.SET_NULL, null=True, blank=True, related_name='members',
    )
    district = models.ForeignKey(
        'core.District', on_delete=models.SET_NULL, null=True, blank=True, related_name='members',
    )
    address = models.CharField(max_length=255, blank=True)
    emergency_contact_name = models.CharField(max_length=150, blank=True)
    emergency_contact_phone = models.CharField(max_length=30, blank=True)

    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='PENDING', db_index=True)
    membership_start_date = models.DateField(null=True, blank=True)
    membership_expiry_date = models.DateField(null=True, blank=True)
    is_baptised = models.BooleanField(null=True, blank=True)

    qr_token = models.CharField(max_length=64, unique=True, blank=True)
    card_issued_at = models.DateTimeField(null=True, blank=True)

    approved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_members',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    status_reason = models.TextField(blank=True)

    class Meta:
        ordering = ['first_name', 'last_name']
        indexes = [models.Index(fields=['branch', 'status'])]

    def __str__(self):
        return f'{self.full_name} ({self.member_id or "no id"})'

    def save(self, *args, **kwargs):
        if not self.qr_token:
            self.qr_token = generate_token()
        if not self.member_id:
            self.member_id = self._generate_member_id()
        return super().save(*args, **kwargs)

    def _generate_member_id(self):
        year = (self.membership_start_date or timezone.localdate()).year
        prefix = f'CZ-{year}-'
        last = (
            Member.objects.filter(member_id__startswith=prefix)
            .order_by('-member_id')
            .values_list('member_id', flat=True)
            .first()
        )
        sequence = int(last.split('-')[-1]) + 1 if last else 1
        candidate = f'{prefix}{sequence:06d}'
        while Member.objects.filter(member_id=candidate).exists():
            sequence += 1
            candidate = f'{prefix}{sequence:06d}'
        return candidate

    @property
    def full_name(self):
        parts = [self.first_name, self.other_names, self.last_name]
        return ' '.join(part for part in parts if part)

    @property
    def is_active_member(self):
        return self.status == 'ACTIVE'

    @property
    def is_card_valid(self):
        if self.status != 'ACTIVE':
            return False
        if self.membership_expiry_date and self.membership_expiry_date < timezone.localdate():
            return False
        return True

    def approve(self, user=None):
        """Approve a pending membership (SRS 20, 6.3)."""
        self.status = 'ACTIVE'
        if not self.membership_start_date:
            self.membership_start_date = timezone.localdate()
        self.approved_by = user if getattr(user, 'is_authenticated', False) else None
        self.approved_at = timezone.now()
        self.save(update_fields=[
            'status', 'membership_start_date', 'approved_by', 'approved_at', 'updated_at',
        ])
        return self

    def public_verification_payload(self):
        """
        Data exposed by QR verification (SRS 21, 46).

        Only information approved for public verification: no phone numbers,
        no email addresses and no financial data.
        """
        return {
            'member_id': self.member_id,
            'full_name': self.full_name,
            'branch': self.branch.name if self.branch_id else None,
            'institution': getattr(self.institution, 'name', None),
            'study_year': self.study_year,
            'status': self.status,
            'status_display': self.get_status_display(),
            'membership_start_date': self.membership_start_date,
            'membership_expiry_date': self.membership_expiry_date,
            'card_valid': self.is_card_valid,
            'photo': self.photo.url if self.photo else None,
        }


class MembershipApplication(TimeStampedModel):
    """
    Public application to join CASFETA (SRS 20, 37 - Join CASFETA).

    Applications are reviewed and approved by the branch leadership.
    """

    STATUS_CHOICES = [
        ('SUBMITTED', 'Imewasilishwa (Submitted)'),
        ('UNDER_REVIEW', 'Inafanyiwa ukaguzi (Under review)'),
        ('APPROVED', 'Imeidhinishwa (Approved)'),
        ('REJECTED', 'Imekataliwa (Rejected)'),
        ('WITHDRAWN', 'Imeondolewa (Withdrawn)'),
    ]

    application_number = models.CharField(max_length=30, unique=True, blank=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    other_names = models.CharField(max_length=150, blank=True)
    email = models.EmailField(blank=True, default='')
    phone = models.CharField(max_length=30)
    gender = models.CharField(max_length=10, choices=Member.GENDER_CHOICES)
    date_of_birth = models.DateField(null=True, blank=True)
    district = models.ForeignKey(
        'core.District', on_delete=models.SET_NULL, null=True, blank=True, related_name='applications',
    )
    branch = models.ForeignKey(
        'branches.Branch', on_delete=models.PROTECT, related_name='membership_applications',
        help_text='Branch the applicant wants to join.',
    )
    institution = models.ForeignKey(
        'core.Institution', on_delete=models.SET_NULL, null=True, blank=True, related_name='applications',
    )
    course_programme = models.CharField(max_length=150, blank=True)
    study_year = models.PositiveSmallIntegerField(null=True, blank=True)
    address = models.CharField(max_length=255, blank=True)
    emergency_contact_name = models.CharField(max_length=150, blank=True)
    emergency_contact_phone = models.CharField(max_length=30, blank=True)
    motivation = models.TextField(blank=True, help_text='Kwa nini unataka kujiunga na CASFETA?')

    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='membership_applications',
        help_text='Platform account linked to the application, when the applicant created one.',
    )
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='SUBMITTED')
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_applications',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)
    created_member = models.OneToOneField(
        Member, on_delete=models.SET_NULL, null=True, blank=True, related_name='application',
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.application_number or "APP"} - {self.full_name}'

    def save(self, *args, **kwargs):
        if not self.application_number:
            year = timezone.localdate().year
            prefix = f'APP-{year}-'
            count = MembershipApplication.objects.filter(application_number__startswith=prefix).count() + 1
            candidate = f'{prefix}{count:05d}'
            while MembershipApplication.objects.filter(application_number=candidate).exists():
                count += 1
                candidate = f'{prefix}{count:05d}'
            self.application_number = candidate
        return super().save(*args, **kwargs)

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'.strip()

    def approve(self, user=None, notes=''):
        """
        Approve the application and create the member record (SRS 20).

        The applicant becomes an ACTIVE member of the selected branch; the
        linked platform account receives the MEMBER role.
        """
        from accounts.models import Role, RoleAssignment
        from core import roles as role_codes

        member = self.created_member or Member(
            first_name=self.first_name,
            last_name=self.last_name,
            other_names=self.other_names,
            email=self.email,
            phone=self.phone,
            gender=self.gender,
            date_of_birth=self.date_of_birth,
            district=self.district,
            branch=self.branch,
            institution=self.institution,
            course_programme=self.course_programme,
            study_year=self.study_year,
            address=self.address,
            emergency_contact_name=self.emergency_contact_name,
            emergency_contact_phone=self.emergency_contact_phone,
            user=self.user,
        )
        member.status = 'ACTIVE'
        member.membership_start_date = member.membership_start_date or timezone.localdate()
        member.approved_by = user if getattr(user, 'is_authenticated', False) else None
        member.approved_at = timezone.now()
        member.save()

        if self.user is not None:
            role = Role.objects.filter(code=role_codes.MEMBER).first()
            if role is not None:
                RoleAssignment.objects.update_or_create(
                    user=self.user, role=role, branch=self.branch, ministry=None,
                    defaults={'is_active': True},
                )

        self.status = 'APPROVED'
        self.reviewed_by = user if getattr(user, 'is_authenticated', False) else None
        self.reviewed_at = timezone.now()
        self.review_notes = notes or self.review_notes
        self.created_member = member
        self.save(update_fields=[
            'status', 'reviewed_by', 'reviewed_at', 'review_notes', 'created_member', 'updated_at',
        ])
        return member


class MemberTransfer(TimeStampedModel):
    """Member transfer between branches (SRS 64). Membership history survives."""

    STATUS_CHOICES = [
        ('REQUESTED', 'Imeombwa (Requested)'),
        ('APPROVED', 'Imeidhinishwa (Approved)'),
        ('REJECTED', 'Imekataliwa (Rejected)'),
        ('COMPLETED', 'Imekamilika (Completed)'),
        ('CANCELLED', 'Imesitishwa (Cancelled)'),
    ]

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name='transfers')
    from_branch = models.ForeignKey(
        'branches.Branch', on_delete=models.PROTECT, related_name='transfers_out',
    )
    to_branch = models.ForeignKey(
        'branches.Branch', on_delete=models.PROTECT, related_name='transfers_in',
    )
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='REQUESTED')
    requested_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='requested_transfers',
    )
    approved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_transfers',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.member} {self.from_branch.code} -> {self.to_branch.code}'

    def clean(self):
        if self.from_branch_id and self.to_branch_id and self.from_branch_id == self.to_branch_id:
            raise ValidationError({'to_branch': 'The receiving branch must be different from the current branch.'})

    def complete(self, user=None):
        """Move the member and keep the history intact (SRS 64, 83 Rule 13)."""
        self.member.branch = self.to_branch
        self.member.status = 'ACTIVE'
        self.member.save(update_fields=['branch', 'status', 'updated_at'])
        self.status = 'COMPLETED'
        self.approved_by = user if getattr(user, 'is_authenticated', False) else self.approved_by
        self.approved_at = self.approved_at or timezone.now()
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'approved_by', 'approved_at', 'completed_at', 'updated_at'])
        return self

