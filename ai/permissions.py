from rest_framework.permissions import BasePermission


class CanUseAI(BasePermission):
    """
    Placeholder permission for AI access.
    Adjust logic later (e.g., subscription checks).
    """

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)
