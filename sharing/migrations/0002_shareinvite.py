from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("sharing", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.CreateModel(
            name="ShareInvite",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("pending", "Pending"), ("accepted", "Accepted"), ("declined", "Declined"), ("revoked", "Revoked")], default="pending", max_length=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("responded_at", models.DateTimeField(blank=True, null=True)),
                ("invited_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sent_invites", to="auth.user")),
                ("invited_user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="share_invites", to="auth.user")),
                ("share", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="invites", to="sharing.sharelink")),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("share", "invited_user"), name="uniq_share_invite"),
                ],
            },
        ),
    ]
