from django.urls import path
from .views import (
    AiApiIndexView,
    StudyModeView,
    ProjectModeView,
    GeneralModeView,
    NotesAIView,
    ChatHistoryListView,
    DeleteAllHistoryView,
    DeleteHistoryItemView,
)

urlpatterns = [
    path("", AiApiIndexView.as_view()),
    path("study/", StudyModeView.as_view()),
    path("project/", ProjectModeView.as_view()),
    path("general/", GeneralModeView.as_view()),
    path("notes/", NotesAIView.as_view()),
    path("history/", ChatHistoryListView.as_view()),
    path("history/delete-all/", DeleteAllHistoryView.as_view()),
    path("history/<int:id>/delete/", DeleteHistoryItemView.as_view()),
]
