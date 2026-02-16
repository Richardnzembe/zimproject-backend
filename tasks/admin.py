from django.contrib import admin

from .models import Task


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "title", "is_completed", "priority", "due_date", "updated_at")
    list_filter = ("is_completed", "priority")
    search_fields = ("title", "description", "client_id", "user__username")

