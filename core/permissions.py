from rest_framework.permissions import BasePermission


class IsOwner(BasePermission):
    """
    Permission class that ensures users can only access their own data.
    Use this by adding 'owner_field' to the view's queryset or model.
    """

    def has_object_permission(self, request, view, obj):
        # Check if the object has a 'user' field
        if hasattr(obj, 'user'):
            return obj.user == request.user
        # Check if the object has an 'owner' field
        if hasattr(obj, 'owner'):
            return obj.owner == request.user
        return False
