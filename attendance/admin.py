"""Attendance session and record administration (SRS 27)."""

from django.contrib import admin

from .models import AttendanceRecord, AttendanceSession


class AttendanceRecordInline(admin.TabularInline):
    model = AttendanceRecord
    extra = 0
    autocomplete_fields = ('member', 'recorded_by')
    readonly_fields = ('check_in_time', 'check_out_time')


@admin.register(AttendanceSession)
class AttendanceSessionAdmin(admin.ModelAdmin):
    list_display = ('title', 'session_date', 'branch', 'event', 'is_open', 'opened_by', 'closed_at')
    list_filter = ('is_open', 'session_date', 'branch')
    search_fields = ('title', 'notes', 'branch__name', 'event__title')
    date_hierarchy = 'session_date'
    autocomplete_fields = ('event', 'branch', 'opened_by')
    inlines = [AttendanceRecordInline]


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ('member', 'guest_name', 'attendance_date', 'status', 'method', 'session', 'branch')
    list_filter = ('status', 'method', 'attendance_date', 'branch')
    search_fields = (
        'member__first_name', 'member__last_name', 'member__member_id',
        'guest_name', 'remarks',
    )
    autocomplete_fields = ('session', 'event', 'registration', 'member', 'branch', 'recorded_by')
