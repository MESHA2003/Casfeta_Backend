"""
File upload validation helpers (SRS 45 - file validation).

Used by receipts/evidence uploads, the digital resource library and the
document repository.
"""

import os

from django.conf import settings
from rest_framework import serializers


def validate_upload(file_object, allowed_extensions=None):
    """
    Validate size and extension of an uploaded file.

    Raises ``serializers.ValidationError`` so the API answers with a clear,
    translated error message.
    """
    if file_object is None:
        return file_object

    max_size = getattr(settings, 'MAX_UPLOAD_SIZE_BYTES', 20 * 1024 * 1024)
    if file_object.size > max_size:
        limit_mb = round(max_size / (1024 * 1024), 1)
        raise serializers.ValidationError(
            f'File is too large. Maximum allowed size is {limit_mb} MB.'
        )

    extensions = allowed_extensions or getattr(settings, 'ALLOWED_UPLOAD_EXTENSIONS', [])
    if extensions:
        extension = os.path.splitext(file_object.name or '')[1].lower().lstrip('.')
        allowed = {item.lower().lstrip('.') for item in extensions}
        if extension and extension not in allowed:
            raise serializers.ValidationError(
                f'File type ".{extension}" is not allowed. Allowed types: {", ".join(sorted(allowed))}.'
            )
    return file_object


class ValidatedFileField(serializers.FileField):
    """FileField that enforces the CZDMP upload policy."""

    def __init__(self, *args, allowed_extensions=None, **kwargs):
        self.allowed_extensions = allowed_extensions
        super().__init__(*args, **kwargs)

    def to_internal_value(self, data):
        validate_upload(data, self.allowed_extensions)
        return super().to_internal_value(data)


class EvidenceFileField(ValidatedFileField):
    """Receipt / bank slip / mobile money confirmation upload (SRS 62)."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault(
            'allowed_extensions',
            ['pdf', 'png', 'jpg', 'jpeg', 'webp', 'doc', 'docx'],
        )
        super().__init__(*args, **kwargs)
