"""Ministry serializers (SRS 24)."""

from rest_framework import serializers

from .models import Ministry, MinistryMembership


class MinistrySerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source='branch.name', read_only=True, default=None)
    leader_name = serializers.SerializerMethodField()
    member_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Ministry
        fields = [
            'id', 'name', 'code', 'level', 'branch', 'branch_name', 'leader', 'leader_name',
            'description', 'objectives', 'is_active', 'member_count', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at', 'member_count']

    def get_leader_name(self, obj):
        if obj.leader_id:
            return obj.leader.get_full_name() or obj.leader.username
        leader = obj.memberships.filter(role_in_ministry='LEADER', is_active=True).select_related('member').first()
        if leader and leader.member:
            return leader.member.full_name
        return None

    def validate(self, attrs):
        level = attrs.get('level') or getattr(self.instance, 'level', 'BRANCH')
        branch = attrs.get('branch') or getattr(self.instance, 'branch', None)
        if level == 'BRANCH' and not branch:
            raise serializers.ValidationError({'branch': 'A branch ministry must be linked to a branch.'})
        if level == 'JIMBO' and branch:
            raise serializers.ValidationError({'branch': 'A Jimbo ministry must not be linked to a branch.'})
        return attrs


class MinistryMembershipSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source='member.full_name', read_only=True)
    member_id = serializers.CharField(source='member.member_id', read_only=True)
    ministry_name = serializers.CharField(source='ministry.name', read_only=True)
    role_display = serializers.CharField(source='get_role_in_ministry_display', read_only=True)

    class Meta:
        model = MinistryMembership
        fields = [
            'id', 'ministry', 'ministry_name', 'member', 'member_name', 'member_id',
            'role_in_ministry', 'role_display', 'joined_date', 'is_active', 'notes', 'created_at',
        ]
        read_only_fields = ['created_at']

    def validate(self, attrs):
        ministry = attrs.get('ministry') or getattr(self.instance, 'ministry', None)
        member = attrs.get('member') or getattr(self.instance, 'member', None)
        if ministry and member and ministry.branch_id and member.branch_id != ministry.branch_id:
            # Rule 1: a member belongs to one branch; ministry membership must be
            # in the member's own branch (Jimbo level ministries accept anyone).
            raise serializers.ValidationError(
                {'member': 'This member belongs to another branch.'}
            )
        return attrs

