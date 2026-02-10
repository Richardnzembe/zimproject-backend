from django.urls import path
from .views import (
    ShareLinkCreateView,
    ShareLinkListView,
    ShareLinkDetailView,
    ShareLinkRevokeView,
    ShareMembersView,
    SharedChatView,
    SharedNoteView,
    ShareInviteCreateView,
    ShareInviteListView,
    ShareInviteActionView,
)

urlpatterns = [
    path("links/", ShareLinkListView.as_view(), name="share-links"),
    path("links/create/", ShareLinkCreateView.as_view(), name="share-link-create"),
    path("links/<uuid:token>/", ShareLinkDetailView.as_view(), name="share-link-detail"),
    path("links/<uuid:token>/revoke/", ShareLinkRevokeView.as_view(), name="share-link-revoke"),
    path("links/<uuid:token>/members/", ShareMembersView.as_view(), name="share-link-members"),
    path("links/<uuid:token>/members/<int:user_id>/", ShareMembersView.as_view(), name="share-link-members-remove"),
    path("links/<uuid:token>/chat/", SharedChatView.as_view(), name="shared-chat"),
    path("links/<uuid:token>/note/", SharedNoteView.as_view(), name="shared-note"),
    path("links/<uuid:token>/invite/", ShareInviteCreateView.as_view(), name="share-invite-create"),
    path("invites/", ShareInviteListView.as_view(), name="share-invite-list"),
    path("invites/<int:invite_id>/", ShareInviteActionView.as_view(), name="share-invite-action"),
]
