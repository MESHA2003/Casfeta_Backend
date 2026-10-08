"""
QR code generation for CZDMP (SRS 21, 26, 27, 42, 72).

QR codes are used for membership verification, event registration tickets,
QR attendance, certificates and receipt verification. They always contain a
random, non-guessable token rather than a sequential id.
"""

import io
import secrets
import uuid

import qrcode
from django.conf import settings
from django.core.files.base import ContentFile


def generate_token():
    """Random verification token used inside QR codes."""
    return secrets.token_urlsafe(18)


def build_verification_url(path, token):
    """
    Absolute URL encoded inside the QR code.

    ``path`` is the frontend/back-end verification path, e.g.
    ``/verify/member/``.
    """
    base = getattr(settings, 'PUBLIC_BASE_URL', '') or ''
    if not base:
        base = f"http://{'127.0.0.1' if settings.DEBUG else 'casfeta-zanzibar.or.tz'}:8000"
    return f"{base.rstrip('/')}{path}{token}"


def qr_png(payload, box_size=10, border=2):
    """Return a PNG image (as bytes) for the given payload."""
    image = qrcode.make(payload, box_size=box_size, border=border)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()


def qr_content_file(payload, filename=None, box_size=10, border=2):
    """Return a Django ContentFile ready to be stored in a FileField."""
    if filename is None:
        filename = f'qr-{uuid.uuid4().hex[:12]}.png'
    return ContentFile(qr_png(payload, box_size=box_size, border=border), name=filename)
