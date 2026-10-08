"""Resource library, news CMS and category administration (SRS 47, 49)."""

from django.contrib import admin

from core.admin import SoftDeleteAdmin

from .models import NewsArticle, Resource, ResourceCategory


@admin.register(ResourceCategory)
class ResourceCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'name_sw', 'group', 'is_active')
    list_filter = ('group', 'is_active')
    search_fields = ('name', 'name_sw', 'description')
    actions = ['seed_defaults']

    @admin.action(description='Restore the default resource categories')
    def seed_defaults(self, request, queryset):
        created = ResourceCategory.seed_defaults()
        self.message_user(request, f'{created} default categor(ies) created.')


@admin.register(Resource)
class ResourceAdmin(SoftDeleteAdmin):
    list_display = (
        'title', 'resource_type', 'category', 'access_level', 'status', 'is_featured', 'download_count',
    )
    list_filter = ('resource_type', 'access_level', 'status', 'category', 'is_featured', 'is_active')
    search_fields = ('title', 'description', 'tags', 'organisation', 'location')
    # slug is generated in Resource.save(); download_count is runtime data.
    readonly_fields = ('slug', 'download_count', 'created_at', 'updated_at')
    autocomplete_fields = ('category', 'author')


@admin.register(NewsArticle)
class NewsArticleAdmin(SoftDeleteAdmin):
    list_display = ('title', 'status', 'published_at', 'author_name', 'is_featured', 'views_count')
    list_filter = ('status', 'is_featured', 'is_active')
    search_fields = ('title', 'excerpt', 'body', 'author_name')
    # slug is generated in NewsArticle.save(); published_at is set on publish.
    readonly_fields = ('slug', 'views_count', 'created_at', 'updated_at')
