"""
Uniform API error handling for CZDMP.

Errors are returned in one predictable shape so that the React frontend can
always display a Kiswahili/English friendly message (SRS 78, 79):

    {
        "detail": "You are not authorized to access this financial record.",
        "errors": {"amount": ["Amount must be greater than zero."]},
        "code": "permission_denied"
    }
"""

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, Throttled, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


DEFAULT_MESSAGES = {
    400: 'The submitted data is not valid. Please check and try again.',
    401: 'Authentication is required to access this resource.',
    403: 'You are not authorized to access this record.',
    404: 'The requested record was not found.',
    405: 'This action is not allowed.',
    429: 'Too many requests. Please try again later.',
    500: 'An unexpected error occurred. Please try again.',
}


def _flatten(errors, prefix=''):
    """Flatten nested serializer errors into {'field': ['message']}."""
    flat = {}
    if isinstance(errors, dict):
        for key, value in errors.items():
            flat.update(_flatten(value, f'{prefix}{key}.' if prefix else f'{key}.'))
    elif isinstance(errors, list):
        if errors and isinstance(errors[0], (dict, list)):
            for index, item in enumerate(errors):
                flat.update(_flatten(item, f'{prefix}{index}.'))
        else:
            flat[prefix.rstrip('.') or 'detail'] = [str(item) for item in errors]
    else:
        flat[prefix.rstrip('.') or 'detail'] = [str(errors)]
    return flat


def czdmp_exception_handler(exc, context):
    """DRF exception handler returning the CZDMP error envelope."""
    if isinstance(exc, DjangoValidationError):
        exc = ValidationError(detail=getattr(exc, 'message_dict', {'detail': exc.messages}))

    response = drf_exception_handler(exc, context)

    if response is None:
        if isinstance(exc, (Http404, DjangoPermissionDenied)):
            return response
        return response

    data = response.data
    detail = None
    errors = {}

    if isinstance(data, dict) and 'detail' in data and len(data) == 1:
        detail = str(data['detail'])
    elif isinstance(data, list):
        errors = _flatten(data)
    elif isinstance(data, dict):
        errors = _flatten(data)

    code = 'error'
    if isinstance(exc, PermissionDenied):
        code = 'permission_denied'
    elif isinstance(exc, ValidationError):
        code = 'validation_error'
    elif isinstance(exc, Throttled):
        code = 'throttled'
        wait = getattr(exc, 'wait', None)
        detail = detail or f'Too many requests. Please try again in {int(wait) if wait else 60} seconds.'
    elif response.status_code == status.HTTP_401_UNAUTHORIZED:
        code = 'not_authenticated'
        detail = detail or DEFAULT_MESSAGES[401]
    elif response.status_code == status.HTTP_403_FORBIDDEN:
        code = 'permission_denied'
        detail = detail or DEFAULT_MESSAGES[403]
    elif response.status_code == status.HTTP_404_NOT_FOUND:
        code = 'not_found'
        detail = detail or DEFAULT_MESSAGES[404]

    if detail is None:
        first_key = next(iter(errors), None)
        if first_key:
            detail = errors[first_key][0] if isinstance(errors[first_key], list) else str(errors[first_key])
        else:
            detail = DEFAULT_MESSAGES.get(response.status_code, DEFAULT_MESSAGES[400])

    response.data = {'detail': detail, 'code': code, 'errors': errors}
    return response
