from django.db import models
from django.contrib.auth.models import User
from cryptography.fernet import Fernet
from django.conf import settings


class ChatHistory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    mode = models.CharField(max_length=20)
    input_data = models.JSONField()
    response_text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)


class UserAIKey(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="ai_key")
    encrypted_api_key = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)

    def set_api_key(self, api_key):
        fernet = Fernet(settings.AI_KEY_ENCRYPTION_SECRET.encode("utf-8"))
        self.encrypted_api_key = fernet.encrypt(api_key.encode("utf-8")).decode("utf-8")

    def get_api_key(self):
        fernet = Fernet(settings.AI_KEY_ENCRYPTION_SECRET.encode("utf-8"))
        return fernet.decrypt(self.encrypted_api_key.encode("utf-8")).decode("utf-8")
