from django.contrib import admin

from .models import Role, RoleAssignment, UserProfile


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'scope', 'level', 'is_active', 'is_system')
    list_filter = ('scope', 'is_active', 'is_system')
    search_fields = ('code', 'name', 'name_sw')
    ordering = ('-level', 'name')


@admin.register(RoleAssignment)
class RoleAssignmentAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'branch', 'ministry', 'is_active', 'start_date', 'end_date')
    list_filter = ('role', 'branch', 'is_active')
    search_fields = ('user__username', 'role__code', 'branch__name')
    autocomplete_fields = ('user',)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'phone', 'primary_branch', 'preferred_language', 'is_email_verified')
    list_filter = ('preferred_language', 'primary_branch', 'is_email_verified')
    search_fields = ('user__username', 'user__email', 'phone')
