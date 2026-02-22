from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "kind", "title", "read_at", "created_at")
    list_filter = ("kind", "read_at", "created_at")
    search_fields = ("title", "message", "user__username", "source_key")
    ordering = ("-created_at",)

