from rest_framework import serializers

from .models import Task


class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = [
            "id",
            "client_id",
            "title",
            "description",
            "is_completed",
            "priority",
            "due_date",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_client_id(self, value):
        value = str(value).strip() if value is not None else None
        return value or None

    def create(self, validated_data):
        client_id = validated_data.get("client_id")
        if client_id:
            user = validated_data.get("user")
            task = Task.objects.filter(user=user, client_id=client_id).first()
            if task:
                for attr, value in validated_data.items():
                    setattr(task, attr, value)
                task.save()
                return task
        return Task.objects.create(**validated_data)

