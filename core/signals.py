from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver
from .models import ActivityLog

@receiver(user_logged_in)
def log_user_login(sender, request, user, **kwargs):
    ActivityLog.objects.create(
        user=user,
        action='Login',
        details=f'User logged in from IP: {request.META.get("REMOTE_ADDR")}'
    )

@receiver(user_logged_out)
def log_user_logout(sender, request, user, **kwargs):
    if user:
        ActivityLog.objects.create(
            user=user,
            action='Logout',
            details=f'User logged out'
        )

@receiver(user_login_failed)
def log_login_failed(sender, credentials, request, **kwargs):
    ActivityLog.objects.create(
        action='Login Failed',
        details=f'Login failed for username: {credentials.get("username")} from IP: {request.META.get("REMOTE_ADDR")}'
    )
