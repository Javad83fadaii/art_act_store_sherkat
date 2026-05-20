from types import MethodType

from django import forms
from django.contrib import admin
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth.admin import UserAdmin

from .forms import CustomUserCreationForm, CustomUserChangeForm
from .models import CustomUser, CreditIncreaseRequest


class CustomUserAdmin(UserAdmin):
    model = CustomUser
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    list_display = ("username", "email", "full_name")


class SuperuserFriendlyAdminAuthenticationForm(AdminAuthenticationForm):
    def confirm_login_allowed(self, user):
        if not user.is_active:
            raise forms.ValidationError(self.error_messages["inactive"], code="inactive")

        if not (user.is_staff or user.is_superuser):
            raise forms.ValidationError(
                self.error_messages["invalid_login"],
                code="invalid_login",
                params={"username": self.username_field.verbose_name},
            )


def _has_admin_permission(self, request):
    user = request.user
    return user.is_active and (user.is_staff or user.is_superuser)


admin.site.login_form = SuperuserFriendlyAdminAuthenticationForm
admin.site.has_permission = MethodType(_has_admin_permission, admin.site)
admin.site.register(CustomUser, CustomUserAdmin)


@admin.register(CreditIncreaseRequest)
class CreditIncreaseRequestAdmin(admin.ModelAdmin):
    # فیلدهای status و requested_amount حذف شدند
    list_display = ("id", "user", "current_credit", "created_at")
    
    # فیلتر status حذف شد
    list_filter = ("created_at",)
    
    search_fields = ("user__phone_number", "user__username", "user__email", "id")
    readonly_fields = ("current_credit", "created_at", "updated_at")
    
    # اکشن‌های تایید و رد درخواست به دلیل تغییر ماهیت جدول حذف شدند
