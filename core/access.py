"""
Role and scope resolution helpers (SRS sections 6, 7, 83).

These helpers read the accounts.RoleAssignment table and answer the two
questions the whole platform depends on:

1. Which roles does this user hold?           -> user_role_codes()
2. Which branches is this user allowed to see? -> branch_scope()

``branch_scope()`` returns ``None`` for Jimbo level users, which means "all
branches". Branch level users receive a set of branch ids, so a Branch A
cashier can never read Branch B records (SRS 79, 83 Rule 14).
"""

from django.utils import timezone

from core import roles as role_codes


def _accounts_models():
    """Import accounts models lazily to avoid circular imports."""
    from accounts.models import RoleAssignment

    return RoleAssignment


def is_authenticated_user(user):
    return bool(user and getattr(user, 'is_authenticated', False))


def user_assignments(user, on_date=None):
    """Active, not yet expired role assignments of a user."""
    if not is_authenticated_user(user):
        return []
    assignments = (
        _accounts_models().objects
        .filter(user=user, is_active=True, role__is_active=True)
        .select_related('role', 'branch')
    )
    target = on_date or timezone.localdate()
    valid = []
    for assignment in assignments:
        if assignment.start_date and assignment.start_date > target:
            continue
        if assignment.end_date and assignment.end_date < target:
            continue
        valid.append(assignment)
    return valid


def user_role_codes(user):
    """Set of role codes held by the user (empty for anonymous users)."""
    if not is_authenticated_user(user):
        return set()
    return {assignment.role.code for assignment in user_assignments(user)}


def user_roles(user):
    """Full role objects held by the user."""
    return [assignment.role for assignment in user_assignments(user)]


def user_level(user):
    """Highest hierarchy level of the user's roles (SRS 7)."""
    if not is_authenticated_user(user):
        return role_codes.level_of(role_codes.PUBLIC_USER)
    if user.is_superuser:
        return role_codes.level_of(role_codes.SUPER_ADMIN)
    codes = user_role_codes(user)
    if not codes:
        return role_codes.level_of(role_codes.PUBLIC_USER)
    return max(role_codes.level_of(code) for code in codes)


def has_role(user, *codes):
    """True when the user holds at least one of the given role codes."""
    if not is_authenticated_user(user):
        return False
    if user.is_superuser:
        return True
    return bool(user_role_codes(user).intersection(set(codes)))


def has_level_at_least(user, level):
    return user_level(user) >= level


def is_jimbo_level(user):
    """True when the user may see the whole Jimbo (all branches)."""
    if not is_authenticated_user(user):
        return False
    if user.is_superuser:
        return True
    return has_level_at_least(user, role_codes.level_of(role_codes.JIMBO_CASHIER))


def is_super_admin(user):
    if not is_authenticated_user(user):
        return False
    return bool(user.is_superuser) or has_role(user, role_codes.SUPER_ADMIN)


def branch_scope(user):
    """
    Branch ids the user may access.

    Returns ``None`` when the user has Jimbo wide access (all branches) and a
    (possibly empty) set of branch ids otherwise.
    """
    if not is_authenticated_user(user):
        return set()
    if is_jimbo_level(user):
        return None

    branch_ids = {
        assignment.branch_id
        for assignment in user_assignments(user)
        if assignment.branch_id
    }

    # A member without an explicit branch role still belongs to a branch.
    member = getattr(user, 'member_profile', None)
    if member is not None and getattr(member, 'branch_id', None):
        branch_ids.add(member.branch_id)

    return branch_ids


def can_access_branch(user, branch_id):
    """Branch level restriction check (SRS 79, 83 Rule 4/14)."""
    scope = branch_scope(user)
    if scope is None:
        return True
    if branch_id is None:
        return False
    return int(branch_id) in scope


def primary_branch(user):
    """Default branch used when a branch level user creates a record."""
    scope = branch_scope(user)
    if scope:
        selected = getattr(user, 'user_profile', None)
        if selected is not None and selected.primary_branch_id in scope:
            return selected.primary_branch
        from branches.models import Branch

        return Branch.objects.filter(id__in=scope).order_by('name').first()
    member = getattr(user, 'member_profile', None)
    return getattr(member, 'branch', None)


def apply_branch_scope(queryset, user, branch_field='branch'):
    """Restrict a queryset to the branches the user may access."""
    scope = branch_scope(user)
    if scope is None:
        return queryset
    if not scope:
        return queryset.none()
    return queryset.filter(**{f'{branch_field}__in': list(scope)})


def user_permission_codes(user):
    """Flattened permission codes from all roles held by the user."""
    codes = set()
    for role in user_roles(user):
        codes.update(role.permission_codes or [])
    if user.is_superuser:
        codes.add('*')
    return codes


def has_permission_code(user, code):
    if not is_authenticated_user(user):
        return False
    if user.is_superuser:
        return True
    codes = user_permission_codes(user)
    return code in codes or '*' in codes
