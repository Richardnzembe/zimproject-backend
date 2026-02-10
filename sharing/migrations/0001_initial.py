from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("notes", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.CreateModel(
            name="ShareLink",
            fields=[
                ("token", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("resource_type", models.CharField(choices=[("chat", "Chat"), ("note", "Note")], max_length=12)),
                ("session_id", models.CharField(blank=True, db_index=True, max_length=64, null=True)),
                ("permission", models.CharField(choices=[("read", "Read"), ("collab", "Collaborate")], default="read", max_length=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="share_links", to="auth.user")),
                ("note", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to="notes.note")),
            ],
        ),
        migrations.CreateModel(
            name="ShareMember",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(default="collaborator", max_length=20)),
                ("added_at", models.DateTimeField(auto_now_add=True)),
                ("added_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="added_members", to="auth.user")),
                ("share", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="members", to="sharing.sharelink")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="auth.user")),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("share", "user"), name="uniq_share_member"),
                ],
            },
        ),
        migrations.AddIndex(
            model_name="sharelink",
            index=models.Index(fields=["resource_type", "session_id"], name="sharing_sh_resource_4f0b96_idx"),
        ),
    ]
