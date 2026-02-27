from django.db import migrations, models
import sharing.models


class Migration(migrations.Migration):

    dependencies = [
        ("sharing", "0004_sharelink_task_and_resource_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="sharelink",
            name="expires_at",
            field=models.DateTimeField(default=sharing.models.default_share_expiry),
        ),
    ]
