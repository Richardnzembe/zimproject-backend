from django.urls import path
from .views import (
    AuthApiIndexView,
    RegisterView,
    CsrfTokenView,
    CookieTokenObtainPairView,
    GoogleLoginView,
    GoogleOAuthConfigView,
    CookieTokenRefreshView,
    LogoutView,
    PasswordResetRequestView,
    PasswordResetConfirmView,
    SetPasswordView,
    DeleteUserView,
    UserProfileView,
)

urlpatterns = [
    path('', AuthApiIndexView.as_view(), name='auth-root'),
    path('csrf/', CsrfTokenView.as_view(), name='csrf-token'),
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', CookieTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('google/', GoogleLoginView.as_view(), name='google_login'),
    path('google/config/', GoogleOAuthConfigView.as_view(), name='google_oauth_config'),
    path('refresh/', CookieTokenRefreshView.as_view(), name='token_refresh'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('password-reset/', PasswordResetRequestView.as_view(), name='password_reset'),
    path('password-reset/confirm/', PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('me/', UserProfileView.as_view(), name='user_profile'),
    path('users/<int:pk>/set_password/', SetPasswordView.as_view(), name='set_password'),
    path('users/<int:pk>/delete/', DeleteUserView.as_view(), name='delete_user'),
]
