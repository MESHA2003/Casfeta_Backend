"""Testimony moderation administration (SRS 18 - moderated content)."""

from django.contrib import admin

from core.admin import SoftDeleteAdmin

from .models import Testimony


@admin.register(Testimony)
class TestimonyAdmin(SoftDeleteAdmin):
    list_display = (
        'reference', 'title', 'category', 'branch', 'status', 'is_featured', 'published_at',
    )
    list_filter = ('status', 'category', 'is_featured', 'branch', 'is_active')
    search_fields = ('reference', 'title', 'body', 'review_notes')
    # reference and review timestamps are set by the review workflow.
    readonly_fields = ('reference', 'reviewed_at', 'published_at', 'created_at', 'updated_at')
    autocomplete_fields = ('member', 'user', 'branch', 'reviewed_by')
    actions = ['approve_and_publish', 'reject_selected']

    @admin.action(description='Approve and publish selected testimonies')
    def approve_and_publish(self, request, queryset):
        count = 0
        for testimony in queryset:
            if testimony.status not in ('APPROVED', 'PUBLISHED'):
                testimony.review(request.user, 'APPROVED', 'Approved from the Django admin.')
                count += 1
        self.message_user(request, f'{count} testimonie(s) approved and published.')

    @admin.action(description='Reject selected testimonies')
    def reject_selected(self, request, queryset):
        count = 0
        for testimony in queryset:
            if testimony.status != 'REJECTED':
                testimony.review(request.user, 'REJECTED', 'Rejected from the Django admin.')
                count += 1
        self.message_user(request, f'{count} testimonie(s) rejected.')
