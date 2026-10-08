"""Certificate serializers (SRS 42)."""

from rest_framework import serializers

from .models import Certificate, CertificateTemplate


class CertificateTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CertificateTemplate
        fields = ['id', 'name', 'title', 'issuer_name', 'accent_color', 'is_active']


class CertificateSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    certificate_type_display = serializers.CharField(
        source='get_certificate_type_display', read_only=True,
    )
    is_valid = serializers.BooleanField(read_only=True)

    class Meta:
        model = Certificate
        fields = [
            'id', 'certificate_id', 'certificate_type', 'certificate_type_display',
            'recipient_name', 'recipient_member', 'programme', 'description',
            'issued_date', 'expiry_date', 'issuer_name', 'template',
            'status', 'status_display', 'is_valid', 'verification_count',
            'created_at',
        ]
        read_only_fields = ['certificate_id', 'verification_count', 'created_at']



