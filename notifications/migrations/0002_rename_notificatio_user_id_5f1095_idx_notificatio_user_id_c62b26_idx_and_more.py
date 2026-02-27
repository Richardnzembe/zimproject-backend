from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0001_initial"),
    ]

    operations = [
        migrations.RenameIndex(
            model_name="notification",
            new_name="notificatio_user_id_c62b26_idx",
            old_name="notificatio_user_id_5f1095_idx",
        ),
        migrations.RenameIndex(
            model_name="notification",
            new_name="notificatio_user_id_47e85c_idx",
            old_name="notificatio_user_id_84a7ca_idx",
        ),
    ]
