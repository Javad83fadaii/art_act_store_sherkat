from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .forms import CustomUserCreationForm, CustomUserChangeForm
from .models import CustomUser, CreditIncreaseRequest


class CustomUserAdmin(UserAdmin):
    model = CustomUser
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    list_display = ("username", "email", "full_name")


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
