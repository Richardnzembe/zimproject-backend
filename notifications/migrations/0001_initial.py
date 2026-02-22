from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.db.models.expressions
from django.db.models import Q


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("share_invite", "Share invite"),
                            ("task_due", "Task due"),
                            ("task_due_soon", "Task due soon"),
                            ("study_reminder", "Study reminder"),
                            ("system", "System"),
                        ],
                        default="system",
                        max_length=32,
                    ),
                ),
                ("title", models.CharField(max_length=160)),
                ("message", models.TextField(blank=True)),
                ("data", models.JSONField(blank=True, default=dict)),
                ("source_key", models.CharField(blank=True, max_length=160, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("read_at", models.DateTimeField(blank=True, null=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notifications",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at", "-id"),
            },
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["user", "created_at"], name="notificatio_user_id_5f1095_idx"),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["user", "read_at"], name="notificatio_user_id_84a7ca_idx"),
        ),
        migrations.AddConstraint(
            model_name="notification",
            constraint=models.UniqueConstraint(
                condition=Q(("source_key__isnull", False)),
                fields=("user", "source_key"),
                name="uniq_notification_source_per_user",
            ),
        ),
    ]

