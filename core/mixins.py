"""
Reusable viewset mixins for CZDMP.

* ``BranchScopedViewSetMixin`` - enforces branch level restrictions (SRS 79).
* ``AuditLoggingViewSetMixin`` - writes WHO/WHAT/WHEN/WHERE/OLD/NEW (SRS 18, 48).
* ``SoftDeleteViewSetMixin``  - financial and historical records are never
  deleted, they are deactivated (SRS 18, 68, 83 Rule 7).
"""

from core import access


class BranchScopedViewSetMixin:
    """
    Restrict every queryset to the branches the requesting user may access and
    stamp the branch on newly created records.
    """

    branch_field = 'branch'
    branch_query_param = 'branch'

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        queryset = access.apply_branch_scope(queryset, user, self.branch_field)

        requested = self.request.query_params.get(self.branch_query_param)
        if requested:
            if access.can_access_branch(user, requested):
                queryset = queryset.filter(**{f'{self.branch_field}_id': requested})
            else:
                queryset = queryset.none()
        return queryset

    def resolve_branch(self, serializer):
        """Branch to store on the new record."""
        user = self.request.user
        provided = serializer.validated_data.get(self.branch_field)
        if provided is not None:
            if not access.can_access_branch(user, getattr(provided, 'id', provided)):
                from rest_framework.exceptions import PermissionDenied

                raise PermissionDenied('You are not authorized to record data for another branch.')
            return provided
        if access.is_jimbo_level(user):
            return None
        return access.primary_branch(user)

    def perform_create(self, serializer):
        if self.branch_field in [f.name for f in serializer.Meta.model._meta.fields]:
            if serializer.validated_data.get(self.branch_field) is None:
                branch = self.resolve_branch(serializer)
                if branch is not None:
                    serializer.save(**{self.branch_field: branch})
                    return
        serializer.save()


class AuditLoggingViewSetMixin:
    """
    Automatic audit trail for create / update / deactivate actions.

    Explicit business actions (approve, payment, reversal, ...) call
    ``audit.services.log_action`` directly.
    """

    audit_entity = None
    audit_exclude_fields = ('updated_at',)

    def get_audit_entity(self, instance=None):
        if self.audit_entity:
            return self.audit_entity
        if instance is not None:
            return instance.__class__.__name__
        return self.get_queryset().model.__name__

    def perform_create(self, serializer):
        super().perform_create(serializer)
        instance = serializer.instance
        if instance is not None:
            self.log_audit('CREATE', instance, new_value=self.snapshot(instance))

    def perform_update(self, serializer):
        old_value = self.snapshot(serializer.instance)
        super().perform_update(serializer)
        instance = serializer.instance
        new_value = self.snapshot(instance)
        changes = {key: value for key, value in new_value.items() if old_value.get(key) != value}
        if changes:
            self.log_audit('UPDATE', instance, old_value=old_value, new_value=changes)

    def snapshot(self, instance):
        from audit.services import model_snapshot

        return model_snapshot(instance, exclude=self.audit_exclude_fields)

    def log_audit(self, action, instance, old_value=None, new_value=None, reason=''):
        from audit.services import log_action

        return log_action(
            request=getattr(self, 'request', None),
            action=action,
            instance=instance,
            entity=self.get_audit_entity(instance),
            old_value=old_value,
            new_value=new_value,
            reason=reason,
        )


class SoftDeleteViewSetMixin:
    """
    Replaces DELETE with deactivation for records that must be preserved.
    """

    soft_delete_reason_required = False

    def perform_destroy(self, instance):
        reason = ''
        if hasattr(self.request, 'data'):
            reason = self.request.data.get('reason', '') or ''
        if self.soft_delete_reason_required and not reason:
            from rest_framework.exceptions import ValidationError

            raise ValidationError({'reason': 'A reason is required for this action.'})

        old_value = None
        if hasattr(self, 'snapshot'):
            old_value = self.snapshot(instance)

        if hasattr(instance, 'deactivate'):
            instance.deactivate(self.request.user, reason)
        else:
            instance.delete()
        if hasattr(self, 'log_audit'):
            self.log_audit('DEACTIVATE', instance, old_value=old_value, reason=reason)
