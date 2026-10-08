from rest_framework import serializers

from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    action_display = serializers.CharField(source='get_action_display', read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True, default=None)

    class Meta:
        model = AuditLog
        fields = [
            'id', 'user', 'username_snapshot', 'role_snapshot', 'action', 'action_display',
            'entity', 'entity_id', 'branch', 'branch_name', 'description',
            'old_value', 'new_value', 'reason', 'ip_address', 'request_path', 'method',
            'created_at',
        ]
        read_only_fields = fields
