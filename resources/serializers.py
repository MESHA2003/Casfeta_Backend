"""Resource, document, news and gallery serializers (SRS 31, 32, 43, 67)."""

from rest_framework import serializers

from core import access
from core.files import validate_upload

from .models import NewsArticle, Resource, ResourceCategory


class ResourceCategorySerializer(serializers.ModelSerializer):
    resource_count = serializers.IntegerField(source='resources.count', read_only=True)

    class Meta:
        model = ResourceCategory
        fields = ['id', 'name', 'name_sw', 'group', 'description', 'is_active', 'resource_count']


class ResourceSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True, default=None)
    author_name = serializers.CharField(source='author.username', read_only=True, default=None)
    file_url = serializers.FileField(source='file', read_only=True, required=False)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Resource
        fields = [
            'id', 'title', 'slug', 'resource_type', 'category', 'category_name', 'description',
            'file', 'file_url', 'external_url', 'thumbnail', 'access_level', 'organisation',
            'deadline', 'amount', 'location', 'author', 'author_name', 'status', 'status_display',
            'is_featured', 'download_count', 'tags', 'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['slug', 'download_count', 'created_at', 'updated_at']

    def validate_file(self, value):
        return validate_upload(value)

    def validate(self, attrs):
        resource_type = attrs.get('resource_type') or getattr(self.instance, 'resource_type', 'DOCUMENT')
        if resource_type != 'LINK' and not (
            attrs.get('file') or getattr(self.instance, 'file', None) or attrs.get('external_url')
        ):
            raise serializers.ValidationError(
                {'file': 'Provide a file or an external link for this resource.'}
            )
        return attrs


class ResourcePublicSerializer(serializers.ModelSerializer):
    """Public library items (SRS 37) - only PUBLIC resources."""

    category_name = serializers.CharField(source='category.name', read_only=True, default=None)

    class Meta:
        model = Resource
        fields = [
            'id', 'title', 'slug', 'resource_type', 'category_name', 'description',
            'external_url', 'thumbnail', 'organisation', 'deadline', 'amount', 'location',
            'created_at',
        ]


class NewsArticleSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    is_live = serializers.BooleanField(read_only=True)

    class Meta:
        model = NewsArticle
        fields = [
            'id', 'title', 'slug', 'excerpt', 'body', 'cover_image', 'author_name', 'status',
            'status_display', 'published_at', 'is_featured', 'views_count', 'is_live', 'is_active',
            'created_at',
        ]
        read_only_fields = ['slug', 'views_count', 'created_at']

    def validate_cover_image(self, value):
        return validate_upload(value, ['png', 'jpg', 'jpeg', 'webp'])


class NewsArticlePublicSerializer(serializers.ModelSerializer):
    """Published news exposed on the public website (SRS 37, 67)."""

    class Meta:
        model = NewsArticle
        fields = [
            'id', 'title', 'slug', 'excerpt', 'body', 'cover_image', 'author_name',
            'published_at', 'is_featured', 'views_count',
        ]



class ResourceAccessCheck:
    """Reusable helper deciding whether a user may open a resource (SRS 43)."""

    @staticmethod
    def can_access(user, resource):
        if resource.access_level == 'PUBLIC':
            return True
        if not access.is_authenticated_user(user):
            return False
        if user.is_superuser:
            return True
        codes = access.user_role_codes(user)
        if resource.access_level == 'MEMBERS':
            return bool(codes.intersection({'MEMBER', 'BRANCH_LEADER', 'BRANCH_SECRETARY',
                                            'BRANCH_CASHIER', 'MINISTRY_LEADER', 'JIMBO_CASHIER',
                                            'JIMBO_FINANCE_OFFICER', 'JIMBO_ADMIN', 'SUPER_ADMIN'}))
        if resource.access_level == 'LEADERS':
            return bool(codes.intersection({'BRANCH_LEADER', 'BRANCH_SECRETARY', 'MINISTRY_LEADER',
                                            'JIMBO_ADMIN', 'SUPER_ADMIN'}))
        if resource.access_level == 'FINANCE':
            return bool(codes.intersection({'JIMBO_CASHIER', 'JIMBO_FINANCE_OFFICER',
                                            'JIMBO_ADMIN', 'SUPER_ADMIN'}))
        if resource.access_level == 'ADMIN':
            return bool(codes.intersection({'JIMBO_ADMIN', 'SUPER_ADMIN'}))
        return False

