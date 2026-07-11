from urllib.parse import urlencode
from decimal import Decimal

from django.shortcuts import render, redirect
from django.urls import reverse
from django.http import JsonResponse
from django.views.generic import View, TemplateView
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.views import LoginView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserChangeForm
from django.contrib import messages 
from core.notification_messages import get_notification
from store.models import SiteVisitLog

from auction.models import AuctionCartItem, Bid
from .realtime import build_profile_live_context, build_profile_live_payload
from .models import CustomUser, VerificationRequest, CreditIncreaseRequest
from .forms import (
    CustomUserCreationForm, 
    PublicSignupForm, 
    CustomLoginForm, 
    CustomUserChangeForm, 
    PublicProfileUpdateForm,
)

from auction.models import Bid


class CustomLoginView(LoginView):
    template_name = 'registration/login.html'
    form_class = CustomLoginForm  
    redirect_authenticated_user = True  

    def form_valid(self, form):
        previous_session_key = self.request.session.session_key
        response = super().form_valid(form)
        current_session_key = self.request.session.session_key
        logged_in_user = form.get_user()

        if previous_session_key:
            guest_visit_log = (
                SiteVisitLog.objects
                .filter(
                    session_key=previous_session_key,
                    is_closed=False,
                    user__isnull=True,
                )
                .order_by('-last_activity')
                .first()
            )

            if guest_visit_log:
                guest_visit_log.user = logged_in_user
                if current_session_key:
                    guest_visit_log.session_key = current_session_key
                guest_visit_log.save(update_fields=['user', 'session_key'])

        return response


class EditProfileView(LoginRequiredMixin, View):
    
    def get(self, request, *args, **kwargs):
        return redirect("profile")

    def post(self, request, *args, **kwargs):
        has_auction_opt_in = (
            int(getattr(request.user, "is_verified", 0) or 0) == 1
            or request.user.has_pending_auction_request
        )
        
        form = PublicProfileUpdateForm(
            request.POST,
            request.FILES,
            instance=request.user,
            has_auction_opt_in=has_auction_opt_in,
        )
        
        next_url = request.POST.get("next") or request.META.get('HTTP_REFERER') or reverse("profile")

        if form.is_valid():
            user = form.save(commit=False)
            password_changed_successfully = False

            current_password = request.POST.get('current_password')
            new_password = request.POST.get('new_password')
            confirm_password = request.POST.get('confirm_password')

            if current_password or new_password or confirm_password:
                if not current_password:
                    # messages.error(request, get_notification('accounts.profile.current_password_required'))
                    return redirect(next_url)
                
                if not user.check_password(current_password):
                    # messages.error(request, get_notification('accounts.profile.current_password_incorrect'))
                    return redirect(next_url)
                
                if new_password != confirm_password:
                    # messages.error(request, get_notification('accounts.profile.new_password_mismatch'))
                    return redirect(next_url)
                
                if len(new_password) < 8:
                    # messages.error(request, get_notification('accounts.profile.new_password_min_length'))
                    return redirect(next_url)

                user.set_password(new_password)
                password_changed_successfully = True

            user.save()

            participate = bool(form.cleaned_data.get("participate_in_auction"))
            if participate and int(getattr(user, "is_verified", 0) or 0) != 1:
                has_pending = VerificationRequest.objects.filter(
                    user=user,
                    status=VerificationRequest.RequestStatus.PENDING,
                ).exists()
                if not has_pending:
                    full_name = (user.full_name or "").strip()
                    phone_val = getattr(user, 'phone_number', getattr(user, 'mobile', ''))
                    VerificationRequest.objects.create(
                        user=user,
                        full_name=full_name,
                        phone_number=phone_val,
                        status=VerificationRequest.RequestStatus.PENDING,
                        is_verified=0,
                    )

            if password_changed_successfully:
                update_session_auth_hash(request, user)
                # messages.success(request, get_notification('accounts.profile.password_changed'))
            else:
                # messages.success(request, get_notification('accounts.profile.updated'))
                pass

            return redirect(next_url)
            
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    # messages.error(request, f"{error}")
                    pass
            return redirect(next_url)


class ProfileView(LoginRequiredMixin, TemplateView):
    template_name = 'registration/profile.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        live_user = CustomUser.objects.get(pk=self.request.user.pk)
        context['user'] = self.request.user
        
        if hasattr(self.request.user, 'liked_products'):
            context['liked_products'] = self.request.user.liked_products.select_related('product').all()
        else:
            context['liked_products'] = []

        context.update(build_profile_live_context(live_user))
        
        return context

    def post(self, request, *args, **kwargs):
        user = request.user
        
        # دریافت تمامی داده‌ها از فرم مودال
        full_name = request.POST.get('full_name')
        email = request.POST.get('email')
        phone_number = request.POST.get('phone_number')
        preferred_methods = request.POST.getlist('preferred_contact_methods')
        telegram_id = request.POST.get('telegram_id')

        # بروزرسانی فیلدها در صورت ارسال مقدار
        if full_name is not None:
            user.full_name = full_name
            
        if email is not None:
            user.email = email
            
        if phone_number is not None:
            user.phone_number = phone_number
            # در صورتی که دیتابیس شما از فیلد mobile هم استفاده می‌کند، آن را نیز مقداردهی می‌کنیم
            if hasattr(user, 'mobile'):
                user.mobile = phone_number
            
        if telegram_id is not None:
            user.telegram_id = telegram_id
            
        user.preferred_contact_methods = preferred_methods

        # ذخیره نهایی کاربر
        user.save()

        # messages.success(request, get_notification('accounts.profile.updated'))
        return redirect('profile')


@login_required
def profile_live_state(request):
    return JsonResponse(
        {
            'success': True,
            **build_profile_live_payload(request.user),
        }
    )


class EditProfileForm(UserChangeForm):
    class Meta:
        model = CustomUser
        fields = ["username", "email", "full_name", "phone_number"]


class SignupView(View):
    def get(self, request):
        form = PublicSignupForm()
        return render(request, 'registration/signup.html', {'form': form})

    def post(self, request):
        form = PublicSignupForm(request.POST)
        if form.is_valid():
            form.save()
            login_url = reverse('login')
            # message_text = get_notification('accounts.signup.success')
            # return redirect(
            #     f'{login_url}?{urlencode({"toast_message": message_text, "toast_type": "success", "toast_position": "bottom-left"})}'
            # )
            return redirect(login_url)

        non_field_errors = form.non_field_errors()
        for error in non_field_errors:
            # messages.error(request, str(error))

            for field_name, errors in form.errors.items():
            if field_name == "__all__":
                continue
            field = form.fields.get(field_name)
            label = str(getattr(field, "label", "") or "").strip() or field_name
            for error in errors:
                # messages.error(request, f"{label}: {error}")

        return render(request, 'registration/signup.html', {'form': form})


@login_required
def request_auction_verification(request):
    next_url = request.POST.get("next") if request.method == "POST" else request.GET.get("next")
    next_url = next_url or request.META.get("HTTP_REFERER") or "/"

    def respond(message, toast_type="info", action_label="", action_href="", request_state="idle"):
        is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
        if is_ajax:
            return JsonResponse(
                {
                    "ok": toast_type != "error",
                    "toast_message": message,
                    "toast_type": toast_type,
                    "toast_action_label": action_label,
                    "toast_action_href": action_href,
                    "request_state": request_state,
                }
            )
        params = {
            "toast_message": message,
            "toast_type": toast_type,
        }
        if action_label:
            params["toast_action_label"] = action_label
        if action_href:
            params["toast_action_href"] = action_href
        joiner = "&" if "?" in next_url else "?"
        return redirect(f"{next_url}{joiner}{urlencode(params)}")

    if request.method not in ("GET", "POST"):
        return respond(get_notification('common.invalid_request'), "error")

    if int(getattr(request.user, "is_verified", 0) or 0) == 1:
        return respond(get_notification('accounts.auction_verification.already_verified'), "success", request_state="verified")

    full_name = (getattr(request.user, "full_name", "") or "").strip()
    if not full_name:
        edit_url = f'{reverse("update_profile")}?{urlencode({"next": next_url})}'
        return respond(
            get_notification('accounts.auction_verification.full_name_required'),
            "warning",
            "ویرایش",
            edit_url,
            "incomplete_profile",
        )

    pending = VerificationRequest.objects.filter(
        user=request.user,
        status=VerificationRequest.RequestStatus.PENDING,
    ).exists()
    if pending:
        return respond(get_notification('accounts.auction_verification.pending_exists'), "warning", request_state="pending")

    phone_val = getattr(request.user, 'phone_number', getattr(request.user, 'mobile', ''))
    VerificationRequest.objects.create(
        user=request.user,
        full_name=full_name,
        phone_number=phone_val,
        status=VerificationRequest.RequestStatus.PENDING,
        is_verified=0,
    )
    
    return respond(
        get_notification('accounts.auction_verification.created'),
        "success",
        request_state="pending",
    )


@login_required
def credit_increase_requests(request):
    """
    ثبت مستقیم درخواست (یا لاگ) افزایش اعتبار در دیتابیس بدون نیاز به فرم
    """
    # دریافت اعتبار فعلی کاربر (در صورت وجود نداشتن، صفر در نظر گرفته می‌شود)
    current_credit = request.user.calculate_current_credit()
    
    pending_request = CreditIncreaseRequest.objects.filter(
        user=request.user,
        status=CreditIncreaseRequest.RequestStatus.PENDING,
    ).exists()
    if pending_request:
        # messages.warning(request, get_notification('accounts.credit_increase.pending_exists'))
        next_url = request.META.get("HTTP_REFERER") or "/"
        return redirect(next_url)

    # ایجاد مستقیم رکورد در دیتابیس
    CreditIncreaseRequest.objects.create(
        user=request.user,
        current_credit=current_credit
    )
    
    # نمایش پیام موفقیت به کاربر
    # messages.success(request, get_notification('accounts.credit_increase.created'))
    
    # بازگرداندن کاربر به همان صفحه‌ای که دکمه را در آن کلیک کرده است
    next_url = request.META.get("HTTP_REFERER") or "/"
    return redirect(next_url)
