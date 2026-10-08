"""Event and registration administration (SRS 25)."""

from django.contrib import admin

from .models import Event, EventCategory, EventRegistration


@admin.register(EventCategory)
class EventCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'name_sw', 'is_active', 'updated_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'name_sw')


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'category', 'level', 'branch', 'start_date', 'status', 'is_public', 'is_active',
    )
    list_filter = ('status', 'level', 'category', 'branch', 'is_public', 'is_active')
    search_fields = ('title', 'venue', 'organizer_name', 'description', 'objectives')
    date_hierarchy = 'start_date'
    # slug is generated from the title in Event.save().
    readonly_fields = ('slug', 'created_at', 'updated_at')
    autocomplete_fields = ('category', 'branch', 'ministry', 'organizer')


@admin.register(EventRegistration)
class EventRegistrationAdmin(admin.ModelAdmin):
    list_display = (
        'registration_id', 'event', 'member', 'guest_name', 'status', 'payment_status', 'created_at',
    )
    list_filter = ('status', 'payment_status', 'event', 'branch')
    search_fields = (
        'registration_id', 'member__first_name', 'member__last_name',
        'guest_name', 'guest_phone', 'guest_email',
    )
    # registration_id and qr_token are generated in EventRegistration.save().
    readonly_fields = ('registration_id', 'qr_token', 'created_at', 'updated_at')
    autocomplete_fields = ('event', 'member', 'branch')
