"""
Certificate management (SRS 42).

Certificates (leadership training, conferences, seminars, volunteer service,
ministry training, participation) carry a certificate id, recipient, programme,
date, issuer and a QR verification token (SRS 42, 72).
"""

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

from core.models import SoftDeleteModel, TimeStampedModel
from core.qr import generate_token


class CertificateTemplate(TimeStampedModel):
    """Design/template used when issuing certificates (SRS 42)."""

    name = models.CharField(max_length=150)
    title = models.CharField(max_length=200, default='Cheti cha Ushiriki')
    issuer_name = models.CharField(max_length=200, default='CASFETA Jimbo la Zanzibar')
    body = models.TextField(
        blank=True,
        help_text='Certificate wording. Use {recipient}, {programme}, {date} and {issuer}.',
    )
    logo = models.ImageField(upload_to='certificates/logos/', blank=True, null=True)
    accent_color = models.CharField(max_length=7, default='#0B5ED7')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Certificate(SoftDeleteModel):
    """An issued certificate with QR verification (SRS 42, 72)."""

    STATUS_CHOICES = [('ISSUED', 'Issued'), ('REVOKED', 'Revoked'), ('EXPIRED', 'Expired')]

    CERTIFICATE_TYPES = [
        ('LEADERSHIP_TRAINING', 'Leadership training'),
        ('CONFERENCE', 'Conference'),
        ('SEMINAR', 'Seminar'),
        ('VOLUNTEER_SERVICE', 'Volunteer service'),
        ('MINISTRY_TRAINING', 'Ministry training'),
        ('PARTICIPATION', 'Participation'),
        ('ACADEMIC', 'Academic'),
        ('OTHER', 'Other'),
    ]

    certificate_id = models.CharField(max_length=40, unique=True, blank=True, db_index=True)
    certificate_type = models.CharField(max_length=30, choices=CERTIFICATE_TYPES, default='PARTICIPATION')
    recipient_name = models.CharField(max_length=200)
    recipient_member = models.ForeignKey(
        'members.Member', on_delete=models.SET_NULL, null=True, blank=True, related_name='certificates',
    )
    recipient_user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='certificates',
    )
    programme = models.CharField(max_length=220)
    description = models.TextField(blank=True)
    issued_date = models.DateField(default=timezone.localdate)
    expiry_date = models.DateField(null=True, blank=True)
    issuer_name = models.CharField(max_length=200, blank=True, default='CASFETA Jimbo la Zanzibar')
    issued_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='issued_certificates',
    )
    template = models.ForeignKey(
        CertificateTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name='certificates',
    )
    qr_token = models.CharField(max_length=64, unique=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='ISSUED')
    revoked_reason = models.TextField(blank=True)
    verification_count = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-issued_date', '-id']
        indexes = [models.Index(fields=['recipient_name'])]

    def __str__(self):
        return f'{self.certificate_id} - {self.recipient_name}'

    def save(self, *args, **kwargs):
        if not self.qr_token:
            self.qr_token = generate_token()
        if not self.certificate_id:
            year = self.issued_date.year if self.issued_date else timezone.localtime().year
            prefix = f'CZ-CERT-{year}-'
            count = Certificate.objects.filter(certificate_id__startswith=prefix).count() + 1
            candidate = f'{prefix}{count:05d}'
            while Certificate.objects.filter(certificate_id=candidate).exists():
                count += 1
                candidate = f'{prefix}{count:05d}'
            self.certificate_id = candidate
        super().save(*args, **kwargs)

    @property
    def is_valid(self):
        if self.status != 'ISSUED':
            return False
        if self.expiry_date and self.expiry_date < timezone.localdate():
            return False
        return True

    def revoke(self, user=None, reason=''):
        self.status = 'REVOKED'
        self.revoked_reason = reason or self.revoked_reason
        self.save(update_fields=['status', 'revoked_reason', 'updated_at'])
        return self

    def public_verification_payload(self):
        """Data returned by the public QR verification endpoint (SRS 42, 46)."""
        return {
            'certificate_id': self.certificate_id,
            'recipient_name': self.recipient_name,
            'programme': self.programme,
            'certificate_type': self.get_certificate_type_display(),
            'issued_date': self.issued_date,
            'expiry_date': self.expiry_date,
            'issuer': self.issuer_name,
            'status': self.status,
            'valid': self.is_valid,
            'verification_count': self.verification_count,
        }

