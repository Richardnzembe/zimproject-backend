from django.urls import path
from .views import NoteListCreateView, NoteDetailView

urlpatterns = [
    path("", NoteListCreateView.as_view()),
    path("<int:pk>/", NoteDetailView.as_view()),
]
