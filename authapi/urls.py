from django.urls import path
from .views import RegisterView, PasswordResetRequestView, PasswordResetConfirmView, SetPasswordView, DeleteUserView, UserProfileView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('password-reset/', PasswordResetRequestView.as_view(), name='password_reset'),
    path('password-reset/confirm/', PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('me/', UserProfileView.as_view(), name='user_profile'),
    path('users/<int:pk>/set_password/', SetPasswordView.as_view(), name='set_password'),
    path('users/<int:pk>/delete/', DeleteUserView.as_view(), name='delete_user'),
]
