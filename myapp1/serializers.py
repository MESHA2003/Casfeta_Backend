from rest_framework import serializers
from django.contrib.auth.models import User
from .models import Member, Announcement, PublicOpinion,Leaderboard

# ------------------ User Serializer ------------------

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email']


# ------------------ Member Serializer ------------------

class MemberSerializer(serializers.ModelSerializer):
    user_detail = UserSerializer(source='user', read_only=True)
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = Member
        exclude = ['user']  # we pass user from the view
        read_only_fields = ['email', 'date_joined', 'full_name', 'user_detail']

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}"

    def validate(self, data):
        # Do not allow email changes
        if self.instance and 'email' in self.initial_data:
            if self.initial_data['email'].lower() != self.instance.email.lower():
                raise serializers.ValidationError({"email": "Email cannot be changed."})
        return data

    def create(self, validated_data):
        user = self.context.get('user')  # passed from the view
        if not user:
            raise serializers.ValidationError("User reference is required.")
        
        # Ensure no existing profile for this user
        if Member.objects.filter(user=user).exists():
            raise serializers.ValidationError("A profile for this user already exists.")

        return Member.objects.create(user=user, email=user.email, **validated_data)

    def update(self, instance, validated_data):
        # Prevent email from being updated
        validated_data.pop('email', None)
        return super().update(instance, validated_data)




class AnnouncementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Announcement
        fields = '__all__'




class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, style={'input_type': 'password'})
    password2 = serializers.CharField(write_only=True, label="Confirm password")

    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'password2']

    def validate(self, data):
        if data['password'] != data['password2']:
            raise serializers.ValidationError("Passwords do not match.")
        return data

    def create(self, validated_data):
        validated_data.pop('password2')
        return User.objects.create_user(**validated_data)
    





class PublicOpinionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PublicOpinion
        fields = '__all__'


class LeaderboardSerializer(serializers.ModelSerializer):
    member_detail = MemberSerializer(source='member', read_only=True)

    class Meta:
        model = Leaderboard
        fields = ['id', 'member', 'member_detail', 'score', 'rank']
        read_only_fields = ['member_detail']

    def validate(self, data):
        if 'member' not in data:
            raise serializers.ValidationError("Member is required.")
        return data

    def create(self, validated_data):
        return Leaderboard.objects.create(**validated_data)