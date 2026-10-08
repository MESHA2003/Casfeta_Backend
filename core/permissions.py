"""
DRF permission classes implementing the CZDMP role based access control
(SRS sections 7, 45, 83).

Every backend endpoint must be protected; the frontend is never trusted
(SRS 79: "The backend must enforce this restriction").
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission

from core import access
from core import roles as role_codes


class RolePermission(BasePermission):
    """Base class: satisfy any configured role / minimum hierarchy level."""

    required_roles = ()
    required_level = None
    message = 'You are not authorized to access this record.'

    def has_permission(self, request, view):
        user = request.user
        if not access.is_authenticated_user(user):
            return False
        if user.is_superuser:
            return True
        if self.required_roles:
            if not access.user_role_codes(user).intersection(set(self.required_roles)):
                return False
        if self.required_level is not None:
            if access.user_level(user) < self.required_level:
                return False
        return True


def RequireRoles(*codes, message=None):
    """Factory building a permission class for the given role codes."""
    return type(
        'RequireRoles',
        (RolePermission,),
        {
            'required_roles': codes,
            'message': message or RolePermission.message,
        },
    )


def RequireLevel(level, message=None):
    """Factory building a permission class for a minimum hierarchy level."""
    return type(
        'RequireLevel',
        (RolePermission,),
        {
            'required_level': level,
            'message': message or RolePermission.message,
        },
    )


class IsSuperAdmin(RolePermission):
    required_roles = (role_codes.SUPER_ADMIN,)
    message = 'Only the Super Administrator can perform this action.'


class IsJimboAdmin(RolePermission):
    required_roles = (role_codes.JIMBO_ADMIN, role_codes.SUPER_ADMIN)
    message = 'Only Jimbo administrators can perform this action.'


class IsJimboFinance(RolePermission):
    """Jimbo cashier, finance officer, Jimbo admin or super admin (SRS 6.6, 6.7)."""

    required_roles = (
        role_codes.JIMBO_CASHIER,
        role_codes.JIMBO_FINANCE_OFFICER,
        role_codes.JIMBO_ADMIN,
        role_codes.SUPER_ADMIN,
    )
    message = 'Only authorized Jimbo finance users can access this financial record.'


class IsJimboCashier(RolePermission):
    required_roles = (role_codes.JIMBO_CASHIER, role_codes.JIMBO_ADMIN, role_codes.SUPER_ADMIN)
    message = 'Only the Jimbo Cashier can confirm receipt of Jimbo contributions.'


class IsBranchStaff(RolePermission):
    """Branch leader, secretary, cashier or higher (SRS 6.3 - 6.5)."""

    required_roles = (
        role_codes.BRANCH_LEADER,
        role_codes.BRANCH_SECRETARY,
        role_codes.BRANCH_CASHIER,
        role_codes.MINISTRY_LEADER,
        role_codes.JIMBO_CASHIER,
        role_codes.JIMBO_FINANCE_OFFICER,
        role_codes.JIMBO_ADMIN,
        role_codes.SUPER_ADMIN,
    )
    message = 'Only branch leadership can access this record.'


class IsBranchLeaderOrAbove(RolePermission):
    required_level = role_codes.level_of(role_codes.BRANCH_LEADER)
    message = 'Only the branch leader (or higher) can approve this action.'


class IsBranchCashierOrAbove(RolePermission):
    required_roles = (
        role_codes.BRANCH_CASHIER,
        role_codes.JIMBO_CASHIER,
        role_codes.JIMBO_FINANCE_OFFICER,
        role_codes.JIMBO_ADMIN,
        role_codes.SUPER_ADMIN,
    )
    message = 'Only authorized cashiers can record financial transactions.'


class IsFinancePolicyManager(RolePermission):
    """Only Jimbo administrators may define which categories carry the 10%."""

    required_roles = role_codes.FINANCE_POLICY_ROLES
    message = 'Only Jimbo administrators can change the financial policy.'


class IsMemberOrAbove(RolePermission):
    required_level = role_codes.level_of(role_codes.MEMBER)
    message = 'Only CASFETA members can access this record.'


class ReadOnly(BasePermission):
    def has_permission(self, request, view):
        return request.method in SAFE_METHODS


class IsBranchScopedOrJimbo(RolePermission):
    """
    Object level guard: branch users may only touch their own branch.

    Used together with the queryset scoping performed in the viewsets so that
    direct object access also returns 403 FORBIDDEN (SRS 79).
    """

    message = 'You are not authorized to access records outside your branch.'

    def has_object_permission(self, request, view, obj):
        branch_id = getattr(obj, 'branch_id', None)
        if branch_id is None:
            organization_owner = getattr(obj, 'user_id', None)
            if organization_owner is not None:
                return organization_owner == request.user.id or access.is_jimbo_level(request.user)
            return access.is_jimbo_level(request.user)
        return access.can_access_branch(request.user, branch_id)


class IsSelfOrBranchStaff(BasePermission):
    """Members may read their own record; branch/Jimbo staff may read more."""

    message = 'You are not authorized to access this record.'

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not access.is_authenticated_user(user):
            return False
        owner_id = getattr(obj, 'user_id', None)
        if owner_id and owner_id == user.id:
            return True
        branch_id = getattr(obj, 'branch_id', None)
        if branch_id is None:
            return access.is_jimbo_level(user)
        return access.can_access_branch(user, branch_id) and access.has_level_at_least(
            user, role_codes.level_of(role_codes.BRANCH_SECRETARY)
        )
