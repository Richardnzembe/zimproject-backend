from django.contrib.auth.models import User
from django.db import models
from django.db.models import Q


class Notification(models.Model):
    KIND_SHARE_INVITE = "share_invite"
    KIND_SHARE_ACTIVITY = "share_activity"
    KIND_TASK_DUE = "task_due"
    KIND_TASK_DUE_SOON = "task_due_soon"
    KIND_STUDY_REMINDER = "study_reminder"
    KIND_SYSTEM = "system"

    KIND_CHOICES = (
        (KIND_SHARE_INVITE, "Share invite"),
        (KIND_SHARE_ACTIVITY, "Share activity"),
        (KIND_TASK_DUE, "Task due"),
        (KIND_TASK_DUE_SOON, "Task due soon"),
        (KIND_STUDY_REMINDER, "Study reminder"),
        (KIND_SYSTEM, "System"),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=32, choices=KIND_CHOICES, default=KIND_SYSTEM)
    title = models.CharField(max_length=160)
    message = models.TextField(blank=True)
    data = models.JSONField(default=dict, blank=True)
    source_key = models.CharField(max_length=160, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["user", "read_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "source_key"],
                condition=Q(source_key__isnull=False),
                name="uniq_notification_source_per_user",
            )
        ]
