from django.db import models

# Create your models here.
from django.db import models
from django.contrib.auth.models import User

class Note(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    client_id = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    title = models.CharField(max_length=200)
    subject = models.CharField(max_length=100)
    category = models.CharField(max_length=50)
    tags = models.TextField(blank=True)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "client_id"], name="uniq_note_client_per_user")
        ]
