"""Serializers for users, roles and role assignments (SRS 6, 7, 45)."""

from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from branches.models import Branch
from core import access, roles as role_codes
from core.files import validate_upload
from members.models import MembershipApplication

from .models import Role, RoleAssignment, UserProfile


class RoleSerializer(serializers.ModelSerializer):
    assignment_count = serializers.IntegerField(source='assignments.count', read_only=True)

    class Meta:
        model = Role
        fields = [
            'id', 'code', 'name', 'name_sw', 'scope', 'level', 'description',
            'permission_codes', 'is_active', 'is_system', 'assignment_count',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at', 'assignment_count']


class UserProfileSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    primary_branch_name = serializers.CharField(source='primary_branch.name', read_only=True, default=None)

    class Meta:
        model = UserProfile
        fields = [
            'id', 'phone', 'alternative_phone', 'gender', 'date_of_birth', 'photo',
            'district', 'address', 'primary_branch', 'primary_branch_name',
            'preferred_language', 'is_phone_verified', 'is_email_verified',
            'must_change_password', 'password_changed_at', 'notes', 'full_name',
        ]
        read_only_fields = ['is_phone_verified', 'is_email_verified', 'password_changed_at', 'full_name']

    def validate_photo(self, value):
        return validate_upload(value, ['png', 'jpg', 'jpeg', 'webp'])


class RoleAssignmentSerializer(serializers.ModelSerializer):
    role_detail = RoleSerializer(source='role', read_only=True)
    username = serializers.CharField(source='user.username', read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True, default=None)
    ministry_name = serializers.CharField(source='ministry.name', read_only=True, default=None)
    role_code = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = RoleAssignment
        fields = [
            'id', 'user', 'username', 'role', 'role_detail', 'role_code', 'branch', 'branch_name',
            'ministry', 'ministry_name', 'start_date', 'end_date', 'is_active',
            'assigned_by', 'notes', 'created_at',
        ]
        read_only_fields = ['assigned_by', 'created_at']

    def validate(self, attrs):
        role = attrs.get('role') or getattr(self.instance, 'role', None)
        branch = attrs.get('branch', getattr(self.instance, 'branch', None))
        ministry = attrs.get('ministry', getattr(self.instance, 'ministry', None))

        if role and role.is_branch_scoped and not branch:
            raise serializers.ValidationError(
                {'branch': f'{role.name} is a branch level role and must be linked to a branch.'}
            )
        if role and role.scope in {'JIMBO', 'SYSTEM'} and branch:
            raise serializers.ValidationError(
                {'branch': f'{role.name} works at Jimbo level; a branch scope is not allowed.'}
            )
        if role and role.code == role_codes.MINISTRY_LEADER and not ministry:
            raise serializers.ValidationError({'ministry': 'A ministry leader must be linked to a ministry.'})
        return attrs

    def create(self, validated_data):
        role_code = validated_data.pop('role_code', '')
        if role_code and not validated_data.get('role'):
            role = Role.objects.filter(code=role_code).first()
            if role is None:
                raise serializers.ValidationError({'role_code': f'Unknown role code "{role_code}".'})
            validated_data['role'] = role
        request = self.context.get('request')
        if request is not None and request.user.is_authenticated:
            validated_data.setdefault('assigned_by', request.user)
        return super().create(validated_data)


class UserSerializer(serializers.ModelSerializer):
    """Read serializer with roles, hierarchy level and branch scope."""

    profile = UserProfileSerializer(source='user_profile', read_only=True)
    roles = serializers.SerializerMethodField()
    role_codes = serializers.SerializerMethodField()
    level = serializers.SerializerMethodField()
    branch_scope = serializers.SerializerMethodField()
    member_status = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name', 'is_active',
            'is_staff', 'is_superuser', 'last_login', 'date_joined',
            'profile', 'roles', 'role_codes', 'level', 'branch_scope', 'member_status',
        ]
        read_only_fields = fields

    def get_roles(self, obj):
        return [
            {
                'code': assignment.role.code,
                'name': assignment.role.name,
                'branch': assignment.branch_id,
                'branch_name': assignment.branch.name if assignment.branch_id else None,
            }
            for assignment in access.user_assignments(obj)
        ]

    def get_role_codes(self, obj):
        return sorted(access.user_role_codes(obj))

    def get_level(self, obj):
        return access.user_level(obj)

    def get_branch_scope(self, obj):
        scope = access.branch_scope(obj)
        return None if scope is None else sorted(scope)

    def get_member_status(self, obj):
        member = getattr(obj, 'member_profile', None)
        return getattr(member, 'status', None) if member is not None else None

class UserWriteSerializer(serializers.ModelSerializer):
    """Create / update users and optionally grant their initial role."""

    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    role_code = serializers.CharField(write_only=True, required=False, allow_blank=True)
    branch = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    phone = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name', 'is_active',
            'password', 'role_code', 'branch', 'phone',
        ]

    def validate_password(self, value):
        if value:
            validate_password(value)
        return value

    def validate_email(self, value):
        queryset = User.objects.filter(email__iexact=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value.lower()

    # -- helpers ------------------------------------------------------------

    def _resolve_branch(self, branch_id):
        if branch_id in (None, ''):
            return None
        from branches.models import Branch

        branch = Branch.objects.filter(pk=branch_id).first()
        if branch is None:
            raise serializers.ValidationError({'branch': 'Unknown branch.'})
        return branch

    def _resolve_role(self, role_code):
        if not role_code:
            return None
        role = Role.objects.filter(code=role_code).first()
        if role is None:
            raise serializers.ValidationError({'role_code': f'Unknown role code "{role_code}".'})
        return role

    def _request_user(self):
        request = self.context.get('request')
        return request.user if request is not None and request.user.is_authenticated else None

    # -- write --------------------------------------------------------------

    def create(self, validated_data):
        role_code = validated_data.pop('role_code', '')
        branch = self._resolve_branch(validated_data.pop('branch', None))
        phone = validated_data.pop('phone', '')
        password = validated_data.pop('password', '') or User.objects.make_random_password()

        user = User(**validated_data)
        user.set_password(password)
        user.save()

        profile, _ = UserProfile.objects.get_or_create(user=user)
        if phone:
            profile.phone = phone
        if branch is not None:
            profile.primary_branch = branch
        profile.save()

        role = self._resolve_role(role_code)
        if role is not None:
            RoleAssignment.objects.update_or_create(
                user=user, role=role,
                branch=branch if role.is_branch_scoped else None,
                ministry=None,
                defaults={'is_active': True, 'assigned_by': self._request_user()},
            )
        return user

    def update(self, instance, validated_data):
        role_code = validated_data.pop('role_code', None)
        branch = self._resolve_branch(validated_data.pop('branch', None))
        phone = validated_data.pop('phone', None)
        password = validated_data.pop('password', '')

        for field, value in validated_data.items():
            setattr(instance, field, value)
        if password:
            instance.set_password(password)
        instance.save()

        profile, _ = UserProfile.objects.get_or_create(user=instance)
        if phone is not None:
            profile.phone = phone
        if branch is not None:
            profile.primary_branch = branch
        profile.save()

        if role_code:
            role = self._resolve_role(role_code)
            if role is not None:
                RoleAssignment.objects.update_or_create(
                    user=instance, role=role,
                    branch=branch if role.is_branch_scoped else None,
                    ministry=None,
                    defaults={'is_active': True, 'assigned_by': self._request_user()},
                )
        return instance

class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    def validate_current_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError('The current password is not correct.')
        return value

    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError({'confirm_password': 'The new passwords do not match.'})
        validate_password(attrs['new_password'], self.context['request'].user)
        return attrs


class PublicSignupSerializer(serializers.Serializer):
    """
    Self registration of a platform account (SRS 37 - Join CASFETA).

    The created account only receives the PUBLIC_USER role; membership itself
    is granted per branch after approval (SRS 20, 83 Rule 1).
    """

    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True)
    preferred_language = serializers.ChoiceField(choices=[('sw', 'Kiswahili'), ('en', 'English')], default='en')
    gender = serializers.ChoiceField(choices=[('MALE', 'Male'), ('FEMALE', 'Female')], required=False)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.filter(is_active=True), required=False,
    )
    course_programme = serializers.CharField(max_length=150, required=False, allow_blank=True)
    study_year = serializers.IntegerField(min_value=1, max_value=20, required=False, allow_null=True)
    address = serializers.CharField(max_length=255, required=False, allow_blank=True)
    emergency_contact_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    emergency_contact_phone = serializers.CharField(max_length=30, required=False, allow_blank=True)

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError('This username is already taken.')
        return value

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('An account with this email already exists.')
        return value.lower()

    def validate(self, attrs):
        if attrs['password'] != attrs['confirm_password']:
            raise serializers.ValidationError({'confirm_password': 'Passwords do not match.'})
        if attrs.get('branch') and not attrs.get('gender'):
            raise serializers.ValidationError({'gender': 'Gender is required for a membership application.'})
        if attrs.get('branch') and not attrs.get('phone'):
            raise serializers.ValidationError({'phone': 'Phone number is required for a membership application.'})
        validate_password(attrs['password'])
        return attrs

    def create(self, validated_data):
        validated_data.pop('confirm_password')
        phone = validated_data.pop('phone', '')
        preferred_language = validated_data.pop('preferred_language', 'en')
        branch = validated_data.pop('branch', None)
        gender = validated_data.pop('gender', None)
        application_fields = {
            field: validated_data.pop(field, default)
            for field, default in {
                'date_of_birth': None,
                'course_programme': '',
                'study_year': None,
                'address': '',
                'emergency_contact_name': '',
                'emergency_contact_phone': '',
            }.items()
        }

        with transaction.atomic():
            user = User.objects.create_user(
                username=validated_data['username'],
                email=validated_data['email'],
                password=validated_data['password'],
                first_name=validated_data.get('first_name', ''),
                last_name=validated_data.get('last_name', ''),
            )

            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.phone = phone or profile.phone
            profile.preferred_language = preferred_language
            profile.must_change_password = False
            profile.save()

            public_role = Role.objects.filter(code=role_codes.PUBLIC_USER).first()
            if public_role is not None:
                RoleAssignment.objects.get_or_create(user=user, role=public_role, branch=None, ministry=None)

            if branch is not None:
                MembershipApplication.objects.create(
                    user=user,
                    branch=branch,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    email=user.email,
                    phone=phone,
                    gender=gender,
                    **application_fields,
                )
        return user


class CZDMPTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    JWT login response enriched with roles, level and branch scope so that the
    React app can build the right dashboard immediately (SRS 71).
    """

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['username'] = user.username
        token['role_codes'] = sorted(access.user_role_codes(user))
        token['level'] = access.user_level(user)
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        user = self.user
        scope = access.branch_scope(user)
        member = getattr(user, 'member_profile', None)
        data['user'] = {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'full_name': user.get_full_name() or user.username,
            'role_codes': sorted(access.user_role_codes(user)),
            'level': access.user_level(user),
            'branch_scope': None if scope is None else sorted(scope),
            'primary_branch': getattr(getattr(user, 'user_profile', None), 'primary_branch_id', None),
            'member_id': getattr(member, 'member_id', None),
            'member_status': getattr(member, 'status', None),
        }
        return data
