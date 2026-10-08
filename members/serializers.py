"""Membership serializers (SRS 20, 21, 64)."""

from rest_framework import serializers

from core.files import validate_upload

from .models import Member, MembershipApplication, MemberTransfer


class MemberSerializer(serializers.ModelSerializer):
    """Read serializer used across dashboards and directories."""

    full_name = serializers.CharField(read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True, default=None)
    branch_code = serializers.CharField(source='branch.code', read_only=True, default=None)
    institution_name = serializers.CharField(source='institution.name', read_only=True, default=None)
    district_name = serializers.CharField(source='district.name', read_only=True, default=None)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    username = serializers.CharField(source='user.username', read_only=True, default=None)
    is_card_valid = serializers.BooleanField(read_only=True)
    ministries = serializers.SerializerMethodField()
    event_count = serializers.SerializerMethodField()
    attendance_count = serializers.SerializerMethodField()

    class Meta:
        model = Member
        fields = [
            'id', 'user', 'username', 'member_id', 'first_name', 'last_name', 'other_names',
            'full_name', 'email', 'phone', 'alternative_phone', 'gender', 'date_of_birth',
            'national_id', 'photo', 'branch', 'branch_name', 'branch_code', 'institution',
            'institution_name', 'course_programme', 'study_year', 'academic_year', 'district',
            'district_name', 'address', 'emergency_contact_name', 'emergency_contact_phone',
            'status', 'status_display', 'membership_start_date', 'membership_expiry_date',
            'is_baptised', 'qr_token', 'card_issued_at', 'approved_at', 'is_card_valid',
            'is_active', 'ministries', 'event_count', 'attendance_count', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'member_id', 'qr_token', 'card_issued_at', 'approved_at', 'created_at', 'updated_at',
        ]

    def get_ministries(self, obj):
        return [
            {
                'ministry': membership.ministry_id,
                'name': membership.ministry.name,
                'role': membership.get_role_in_ministry_display(),
            }
            for membership in obj.ministry_memberships.select_related('ministry').filter(is_active=True)
        ]

    def get_event_count(self, obj):
        return obj.event_registrations.filter(status__in=['REGISTERED', 'ATTENDED']).count()

    def get_attendance_count(self, obj):
        return obj.attendance_records.filter(status__in=['PRESENT', 'LATE']).count()

    def validate_photo(self, value):
        return validate_upload(value, ['png', 'jpg', 'jpeg', 'webp'])

    def validate_branch(self, value):
        request = self.context.get('request')
        if request and value:
            from core import access

            if not access.can_access_branch(request.user, value.id):
                raise serializers.ValidationError(
                    'You are not authorized to manage members for another branch.'
                )
        return value


class MemberCardSerializer(serializers.Serializer):
    """
    Digital membership card payload (SRS 21).

    Only information approved for public verification is exposed (SRS 46).
    """

    card_title = serializers.SerializerMethodField()
    member_id = serializers.CharField()
    full_name = serializers.CharField()
    photo = serializers.CharField(allow_null=True)
    branch = serializers.CharField(allow_null=True)
    institution = serializers.CharField(allow_null=True)
    study_year = serializers.IntegerField(allow_null=True)
    status = serializers.CharField()
    status_display = serializers.CharField()
    membership_start_date = serializers.DateField(allow_null=True)
    membership_expiry_date = serializers.DateField(allow_null=True)
    card_valid = serializers.BooleanField()
    qr_payload = serializers.CharField()

    def get_card_title(self, obj):
        return 'CASFETA ZANZIBAR - DIGITAL MEMBERSHIP CARD'

class MembershipApplicationSerializer(serializers.ModelSerializer):
    """
    Public application to join CASFETA (SRS 37 - Join CASFETA).

    Access is enforced in the view: anonymous applicants may submit, branch
    staff may list and approve (SRS 6.3).
    """

    full_name = serializers.CharField(read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True, default=None)
    institution_name = serializers.CharField(source='institution.name', read_only=True, default=None)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = MembershipApplication
        fields = [
            'id', 'application_number', 'first_name', 'last_name', 'other_names', 'full_name',
            'email', 'phone', 'gender', 'date_of_birth', 'district', 'branch', 'branch_name',
            'institution', 'institution_name', 'course_programme', 'study_year', 'address',
            'emergency_contact_name', 'emergency_contact_phone', 'motivation', 'user', 'status',
            'status_display', 'reviewed_at', 'review_notes', 'created_member', 'created_at',
        ]
        read_only_fields = [
            'application_number', 'user', 'status', 'reviewed_at', 'review_notes',
            'created_member', 'created_at',
        ]

    def create(self, validated_data):
        request = self.context.get('request')
        if request and getattr(request, 'user', None) and request.user.is_authenticated:
            validated_data.setdefault('user', request.user)
        return super().create(validated_data)


class MemberTransferSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source='member.full_name', read_only=True)
    member_id = serializers.CharField(source='member.member_id', read_only=True)
    from_branch_name = serializers.CharField(source='from_branch.name', read_only=True)
    to_branch_name = serializers.CharField(source='to_branch.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = MemberTransfer
        fields = [
            'id', 'member', 'member_name', 'member_id', 'from_branch', 'from_branch_name',
            'to_branch', 'to_branch_name', 'reason', 'status', 'status_display',
            'requested_by', 'approved_by', 'approved_at', 'completed_at', 'created_at',
        ]
        read_only_fields = ['status', 'requested_by', 'approved_by', 'approved_at', 'completed_at']

    def validate(self, attrs):
        from_branch = attrs.get('from_branch') or getattr(self.instance, 'from_branch', None)
        to_branch = attrs.get('to_branch')
        if from_branch and to_branch and from_branch.id == to_branch.id:
            raise serializers.ValidationError(
                {'to_branch': 'The receiving branch must be different from the current branch.'}
            )
        return attrs

