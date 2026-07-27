from django.urls import path
from django.contrib.auth import views as auth_views

from . import views

urlpatterns = [
    # مسیرهای ورود و خروج
    path('login/', views.CustomLoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='home'), name='logout'),
    path(
        'password_reset/',
        auth_views.PasswordResetView.as_view(
            form_class=views.CustomPasswordResetForm,
        ),
        name='password_reset',
    ),
    path(
        'password_change/',
        views.CustomPasswordChangeView.as_view(),
        name='password_change',
    ),

    # مسیر ثبت‌نام
    path('signup/', views.SignupView.as_view(), name='signup'),

    # مسیرهای پروفایل کاربری
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('profile/live-state/', views.profile_live_state, name='profile_live_state'),
    path('profile/edit/', views.EditProfileView.as_view(), name='update_profile'),
    # مسیر درخواست تایید حساب کاربری برای شرکت در مزایده
    path('verification/request/', views.request_auction_verification, name='request_auction_verification'),

    # مسیرهای تایید ایمیل
    path('verification/email/', views.EmailVerificationView.as_view(), name='email_verification'),
    path('verification/send-email-code/', views.send_email_verification, name='send_email_verification'),
    path('verification/verify-email-code/', views.verify_email_code, name='verify_email_code'),

    path('credit/requests/', views.credit_increase_requests, name='credit_increase_requests'),
]
