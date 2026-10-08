from django.contrib import admin
from .models import Member, Announcement,PublicOpinion

@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'last_name', 'email', 'phone', 'gender', 'institution', 'branch_name', 'branch_location', 'date_joined')
    search_fields = ('first_name', 'last_name', 'email', 'phone', 'institution', 'branch_name', 'branch_location')


admin.site.register(Announcement)
@admin.register(PublicOpinion)
class PublicOpinionAdmin(admin.ModelAdmin):
    list_display = ('user', 'content', 'created_at')
    search_fields = ('user__username', 'content')
    list_filter = ('created_at',)
    ordering = ('-created_at',)