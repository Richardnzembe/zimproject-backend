from rest_framework import serializers
from .models import Note


class NoteSerializer(serializers.ModelSerializer):
    tags = serializers.ListField(child=serializers.CharField(), required=False)

    class Meta:
        model = Note
        fields = ["id", "client_id", "title", "subject", "category", "tags", "content", "created_at"]
        read_only_fields = ["id", "created_at"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        raw_tags = (instance.tags or "").strip()
        if raw_tags:
            data["tags"] = [t for t in (tag.strip() for tag in raw_tags.split(",")) if t]
        else:
            data["tags"] = []
        return data

    def validate_tags(self, value):
        return [str(tag).strip() for tag in value if str(tag).strip()]

    def validate_client_id(self, value):
        value = str(value).strip() if value is not None else None
        return value or None

    def create(self, validated_data):
        tags = validated_data.pop("tags", [])
        client_id = validated_data.get("client_id")
        validated_data["tags"] = ", ".join(tags)

        if client_id:
            user = validated_data.get("user")
            # Security: Always filter by user to prevent cross-user data access
            note = Note.objects.filter(user=user, client_id=client_id).first()
            if note:
                # Update existing note owned by this user
                for attr, value in validated_data.items():
                    setattr(note, attr, value)
                note.save()
                return note
            # Create new note
            validated_data["user"] = user
            return Note.objects.create(**validated_data)

        return Note.objects.create(**validated_data)

    def update(self, instance, validated_data):
        tags = validated_data.pop("tags", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if tags is not None:
            instance.tags = ", ".join(tags)
        instance.save()
        return instance
