"""
Audit logging service (SRS 18, 48).

Always call ``log_action`` from business code instead of writing AuditLog
rows directly: it normalises the actor, the branch scope, the request
metadata and the old/new value snapshots.
"""

import logging
from datetime import date, datetime
from decimal import Decimal

from django.db import models

logger = logging.getLogger('czdmp.audit')


def client_ip(request):
    if request is None:
        return None
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip() or None
    return request.META.get('REMOTE_ADDR') or None


def user_agent(request):
    if request is None:
        return ''
    return (request.META.get('HTTP_USER_AGENT') or '')[:500]


def role_snapshot(user):
    """Comma separated list of role codes the actor held at that moment."""
    try:
        from core.access import user_role_codes

        return ','.join(sorted(user_role_codes(user)))
    except Exception:  # pragma: no cover - audit must never break the request
        return ''


def model_snapshot(instance, exclude=()):
    """
    Convert a model instance into a JSON friendly dict.

    Used for the OLD VALUE / NEW VALUE columns of the audit trail (SRS 18).
    """
    if instance is None:
        return None
    data = {}
    for field in instance._meta.fields:
        name = field.name
        if name in exclude:
            continue
        try:
            value = getattr(instance, name)
        except Exception:  # pragma: no cover
            continue
        if value is None:
            data[name] = None
        elif isinstance(value, (datetime, date)):
            data[name] = value.isoformat()
        elif isinstance(value, Decimal):
            data[name] = str(value)
        elif isinstance(value, models.Model):
            data[name] = getattr(value, 'pk', None)
        elif hasattr(value, 'name') and hasattr(value, 'url'):
            data[name] = getattr(value, 'name', '') or ''
        elif isinstance(value, (int, float, bool, str)):
            data[name] = value
        else:
            data[name] = str(value)
    return data


def log_action(request=None, action='UPDATE', instance=None, entity=None, entity_id=None,
               branch=None, old_value=None, new_value=None, reason='', description='',
               user=None, username=None):
    """
    Persist one audit trail entry.

    Never raises: an audit problem must not roll back a financial
    transaction, but it is always logged to the application log.
    """
    from audit.models import AuditLog

    try:
        actor = user if user is not None else getattr(request, 'user', None)
        if actor is not None and not getattr(actor, 'is_authenticated', False):
            actor = None

        if entity is None and instance is not None:
            entity = instance.__class__.__name__
        if entity_id is None and instance is not None:
            entity_id = getattr(instance, 'pk', None)
        if branch is None and instance is not None:
            branch = getattr(instance, 'branch', None)
        if instance is not None and new_value is None:
            new_value = model_snapshot(instance)

        return AuditLog.objects.create(
            user=actor,
            username_snapshot=username or (getattr(actor, 'username', '') or ''),
            role_snapshot=role_snapshot(actor) if actor else '',
            action=action,
            entity=entity or '',
            entity_id='' if entity_id is None else str(entity_id),
            branch=branch if getattr(branch, 'pk', None) else None,
            description=description,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            ip_address=client_ip(request),
            user_agent=user_agent(request),
            request_path=(getattr(request, 'path', '') or '')[:255],
            method=(getattr(request, 'method', '') or '')[:10],
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.error('Failed to write audit log (%s on %s): %s', action, entity, exc)
        return None
