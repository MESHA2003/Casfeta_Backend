"""
Create the platform super administrator from a Django shell.

The script is idempotent, so it is safe to run repeatedly::

    python manage.py shell < shell.py
    python shell.py

Credentials: username ``admin`` / password ``admin@123``.
"""

import os

from django.conf import settings

if not settings.configured:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'casfeta_project.settings')
    import django
    django.setup()

from django.contrib.auth.models import User

from accounts.models import Role, RoleAssignment
from core import roles as role_codes

USERNAME = 'admin'
PASSWORD = 'admin@123'


def main():
    # 1. Make sure the SUPER_ADMIN role exists (normally seeded by seed_czdmp).
    entry = next(
        item for item in role_codes.ROLE_CATALOGUE if item['code'] == role_codes.SUPER_ADMIN
    )
    role, _ = Role.objects.get_or_create(
        code=role_codes.SUPER_ADMIN,
        defaults={
            'name': entry['name'],
            'name_sw': entry['name_sw'],
            'scope': entry['scope'],
            'level': role_codes.LEVELS[role_codes.SUPER_ADMIN],
            'description': entry['description'],
            'is_system': True,
        },
    )
    # 2. Create (or refresh) the admin account.
    user, created = User.objects.get_or_create(
        username=USERNAME,
        defaults={'is_staff': True, 'is_superuser': True, 'is_active': True},
    )
    user.is_staff = True
    user.is_superuser = True
    user.is_active = True
    user.set_password(PASSWORD)
    user.save()
    # 3. Grant the SUPER_ADMIN role so /api/auth/me reports it (SRS 6, 7).
    #    SUPER_ADMIN is SYSTEM scoped, so no branch is required.
    assignment, _ = RoleAssignment.objects.get_or_create(
        user=user,
        role=role,
        branch=None,
        ministry=None,
        defaults={'is_active': True, 'notes': 'Initial super administrator (shell.py).'},
    )
    if not assignment.is_active:
        assignment.is_active = True
        assignment.save(update_fields=['is_active'])
    # 4. Verify the result.
    user.refresh_from_db()
    role_list = sorted(
        user.role_assignments.filter(is_active=True).values_list('role__code', flat=True)
    )
    print(f"{'Created' if created else 'Updated'} superuser: {user.username} (id={user.pk})")
    print(
        f'password ok: {user.check_password(PASSWORD)} | '
        f'is_staff: {user.is_staff} | is_superuser: {user.is_superuser}'
    )
    print(f"active roles: {', '.join(role_list) or '(none)'}")


main()
