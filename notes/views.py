from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied
from .models import Note
from .serializers import NoteSerializer


class NoteListCreateView(generics.ListCreateAPIView):
    serializer_class = NoteSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Note.objects.filter(user=self.request.user).order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class NoteDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = NoteSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Note.objects.filter(user=self.request.user)

    def perform_update(self, serializer):
        # Extra security: verify the note belongs to the current user
        if serializer.instance.user != self.request.user:
            raise PermissionDenied("You do not have permission to edit this note.")
        serializer.save()

    def perform_destroy(self, instance):
        # Extra security: verify the note belongs to the current user
        if instance.user != self.request.user:
            raise PermissionDenied("You do not have permission to delete this note.")
        instance.delete()
