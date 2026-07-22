from types import MethodType

from django import forms
from django.contrib import admin
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth.admin import UserAdmin

from django.shortcuts import render
from django.http import HttpResponseRedirect
from django.core.mail import send_mail
from django.conf import settings
from django.contrib import messages
from .forms import CustomUserCreationForm, CustomUserChangeForm, SendCustomEmailForm
from .models import CustomUser, CreditIncreaseRequest


class CustomUserAdmin(UserAdmin):
    model = CustomUser
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    list_display = ("username", "email", "full_name")
    actions = ['send_custom_email_action']

    @admin.action(description='ارسال ایمیل سفارشی (Send Custom Email)')
    def send_custom_email_action(self, request, queryset):
        if 'apply' in request.POST:
            form = SendCustomEmailForm(request.POST)
            if form.is_valid():
                subject = form.cleaned_data['subject']
                message = form.cleaned_data['message']
                
                # filter out users without email
                valid_users = queryset.exclude(email__isnull=True).exclude(email__exact='')
                emails = list(valid_users.values_list('email', flat=True))
                
                if emails:
                    send_mail(
                        subject,
                        message,
                        settings.DEFAULT_FROM_EMAIL,
                        emails,
                        fail_silently=True,
                    )
                    self.message_user(request, f"ایمیل با موفقیت به {len(emails)} کاربر ارسال شد.", messages.SUCCESS)
                else:
                    self.message_user(request, "هیچ کاربری با ایمیل معتبر یافت نشد.", messages.WARNING)
                
                return HttpResponseRedirect(request.get_full_path())
        else:
            form = SendCustomEmailForm(initial={'_selected_action': request.POST.getlist(admin.ACTION_CHECKBOX_NAME)})
            
        context = {
            'users': queryset,
            'form': form,
            'title': 'ارسال ایمیل سفارشی',
            **self.admin_site.each_context(request),
        }
        return render(request, 'admin/send_custom_email.html', context)


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
