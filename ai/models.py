from django.db import models
from django.contrib.auth.models import User


class ChatHistory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    mode = models.CharField(max_length=20)
    input_data = models.JSONField()
    response_text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
