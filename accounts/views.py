import json
import logging
import smtplib
import socket
from urllib.parse import urlencode
from decimal import Decimal

from django.shortcuts import render, redirect
from django.conf import settings
from django.urls import reverse, reverse_lazy
from django.http import JsonResponse
from django.views.generic import View, TemplateView
from django.contrib.auth import update_session_auth_hash, login as auth_login
from django.contrib.auth.views import LoginView
from django.contrib.auth.views import PasswordChangeView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserChangeForm
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils.http import url_has_allowed_host_and_scheme
from core.notification_messages import get_notification
from store.models import SiteVisitLog
from django.views.decorators.http import require_POST

from auction.models import AuctionCartItem, Bid
from core.emailing import normalize_email_value, send_plain_email
from notifications.enums import NotificationProviderType
from notifications.services import notification_service
from .realtime import build_profile_live_context, build_profile_live_payload
from .emails import send_verification_code_email, send_verification_code_sms, send_welcome_email, send_welcome_sms
from .models import CustomUser, VerificationRequest, CreditIncreaseRequest, EmailVerificationOTP, SMSVerificationOTP
from .forms import (
    CustomUserCreationForm, 
    PublicSignupForm, 
    CustomLoginForm, 
    CustomUserChangeForm, 
    CustomPasswordResetForm,
    PublicProfileUpdateForm,
)

from auction.models import Bid


logger = logging.getLogger(__name__)
EMAIL_VERIFICATION_SENT_TO_SESSION_KEY = "email_verification_code_sent_to"
SMS_VERIFICATION_SENT_TO_SESSION_KEY = "sms_verification_code_sent_to"
SMS_VERIFICATION_ALERT_SESSION_KEY = "sms_verification_alert"


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

        if _user_requires_email_verification(logged_in_user):
            success_url = super().get_success_url()
            verification_url = reverse("email_verification")
            if success_url:
                params = urlencode({"next": success_url})
                return redirect(f"{verification_url}?{params}")
            return redirect(verification_url)

        return response


class CustomPasswordChangeView(LoginRequiredMixin, PasswordChangeView):
    template_name = 'registration/password_change_form.html'
    success_url = reverse_lazy('password_change_done')

    def form_valid(self, form):
        response = super().form_valid(form)
        user = self.request.user
        if getattr(user, 'email', None):
            send_plain_email(
                event='accounts.password.changed',
                subject='رمز عبور شما تغییر کرد',
                message=(
                    "سلام,\n\n"
                    "رمز عبور حساب کاربری شما با موفقیت تغییر کرد.\n"
                    "اگر این تغییر توسط شما انجام نشده است، لطفاً سریع‌تر رمز عبور خود را بازیابی کنید."
                ),
                recipients=[user.email],
                fail_silently=True,
                metadata={'user_id': str(user.pk)},
            )
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
                if getattr(user, 'email', None):
                    send_plain_email(
                        event='accounts.password.changed',
                        subject='رمز عبور شما تغییر کرد',
                        message=(
                            "سلام,\n\n"
                            "رمز عبور حساب کاربری شما با موفقیت تغییر کرد.\n"
                            "اگر این تغییر توسط شما انجام نشده است، لطفاً سریع‌تر رمز عبور خود را بازیابی کنید."
                        ),
                        recipients=[user.email],
                        fail_silently=True,
                        metadata={'user_id': str(user.pk)},
                    )
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
            user = form.save()
            if _user_has_sms_contact_method(user) and user.is_active:
                user.is_active = False
                user.is_sms_verified = False
                user.save(update_fields=["is_active", "is_sms_verified"])
            auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")

            sms_verification_error = None
            welcome_email_error = None
            if _user_has_sms_contact_method(user):
                try:
                    send_welcome_sms(user=user)
                except Exception:
                    logger.exception("Signup welcome sms exception for user %s", user.pk)
            if _user_requires_email_verification(user):
                try:
                    send_welcome_email(user=user)
                except Exception as exc:
                    logger.exception("Signup welcome email exception for user %s", user.pk)
                    welcome_email_error = _email_error_response(exc)

                ok, error_message = _send_email_verification_code_for_user(user=user, email=user.email)
                if ok:
                    _remember_sent_verification_code(request, user.email)
                    alert_type = "success"
                    alert_message = "کد تایید ۶ رقمی به ایمیل شما ارسال شد."
                    if welcome_email_error:
                        alert_type = "error"
                        alert_message = (
                            "کد تایید برای شما ارسال شد، اما ایمیل خوش‌آمدگویی ارسال نشد. "
                            f"{welcome_email_error}"
                        )
                    request.session["email_verification_alert"] = {
                        "type": alert_type,
                        "message": alert_message,
                    }
                else:
                    alert_message = error_message or "ارسال کد تایید با خطا مواجه شد."
                    if welcome_email_error:
                        alert_message = (
                            "ارسال ایمیل خوش‌آمدگویی با خطا مواجه شد. "
                            f"{welcome_email_error} "
                            f"ارسال کد تایید نیز با خطا مواجه شد: {alert_message}"
                        )
                    request.session["email_verification_alert"] = {
                        "type": "error",
                        "message": alert_message,
                    }

                return redirect(reverse("email_verification"))

            if _user_requires_sms_verification(user):
                ok, error_message = _send_sms_verification_code_for_user(user=user, phone_number=user.phone_number)
                if ok:
                    _remember_sent_sms_verification_code(request, user.phone_number)
                    request.session[SMS_VERIFICATION_ALERT_SESSION_KEY] = {
                        "type": "success",
                        "message": "کد تایید پیامکی برای شما ارسال شد.",
                    }
                else:
                    sms_verification_error = error_message or "ارسال کد تایید پیامکی با خطا مواجه شد."
                    request.session[SMS_VERIFICATION_ALERT_SESSION_KEY] = {
                        "type": "error",
                        "message": sms_verification_error,
                    }
                return redirect(reverse("sms_verification"))

            return redirect(reverse("home"))

        non_field_errors = form.non_field_errors()
        for error in non_field_errors:
            pass
            # messages.error(request, str(error))

        for field_name, errors in form.errors.items():
            if field_name == "all":
                continue

            field = form.fields.get(field_name)
            label = str(getattr(field, "label", "") or "").strip() or field_name

            for error in errors:
                pass
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

def _json_body(request):
    try:
        return json.loads((request.body or b"{}").decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _email_error_response(exc):
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "احراز هویت SMTP ناموفق بود. نام کاربری یا رمز عبور ایمیل را بررسی کنید."
    if isinstance(exc, smtplib.SMTPConnectError):
        return "اتصال به سرور SMTP برقرار نشد. هاست، پورت و دسترسی شبکه را بررسی کنید."
    if isinstance(exc, smtplib.SMTPServerDisconnected):
        detail = str(exc).lower()
        if "timed out" in detail:
            return "اتصال به سرور SMTP تایم‌اوت شد. دسترسی شبکه یا پورت خروجی سرور را بررسی کنید."
        return "اتصال سرور SMTP ناگهانی قطع شد. احتمالاً پورت یا TLS/SSL نادرست است."
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "زمان انتظار برای اتصال یا ارسال ایمیل تمام شد. دسترسی شبکه سرور به SMTP را بررسی کنید."
    return str(exc)

def _safe_next_url(request, next_url):
    candidate = str(next_url or "").strip()
    if not candidate:
        return None
    if not url_has_allowed_host_and_scheme(
        url=candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return None
    return candidate


def _user_requires_email_verification(user):
    email_value = normalize_email_value(getattr(user, "email", "") or "")
    if not email_value or getattr(user, "has_verified_email", False):
        return False

    enabled_channels = {
        str(method).strip().lower()
        for method in (getattr(user, "get_enabled_notification_channels", lambda: [])() or [])
        if str(method).strip()
    }
    if not enabled_channels:
        return True
    return "email" in enabled_channels


def _normalize_verification_code(code):
    digit_map = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    return str(code or "").strip().translate(digit_map).replace(" ", "")


def _normalize_phone_number(phone_number):
    digit_map = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    normalized = str(phone_number or "").strip().translate(digit_map)
    normalized = normalized.replace(" ", "").replace("-", "")
    return "".join(ch for ch in normalized if ch.isdigit())


def _user_has_sms_contact_method(user):
    return "sms" in {method.lower() for method in user.get_enabled_notification_channels()}


def _user_requires_sms_verification(user):
    return _user_has_sms_contact_method(user) and not bool(getattr(user, "is_active", False))


def _remember_sent_verification_code(request, email):
    email_value = normalize_email_value(email)
    if email_value:
        request.session[EMAIL_VERIFICATION_SENT_TO_SESSION_KEY] = email_value.casefold()


def _has_sent_verification_code(request, email):
    email_value = normalize_email_value(email)
    if not email_value:
        return False
    return request.session.get(EMAIL_VERIFICATION_SENT_TO_SESSION_KEY) == email_value.casefold()


def _clear_sent_verification_code(request):
    request.session.pop(EMAIL_VERIFICATION_SENT_TO_SESSION_KEY, None)


def _remember_sent_sms_verification_code(request, phone_number):
    phone_value = _normalize_phone_number(phone_number)
    if phone_value:
        request.session[SMS_VERIFICATION_SENT_TO_SESSION_KEY] = phone_value


def _has_sent_sms_verification_code(request, phone_number):
    phone_value = _normalize_phone_number(phone_number)
    if not phone_value:
        return False
    return request.session.get(SMS_VERIFICATION_SENT_TO_SESSION_KEY) == phone_value


def _clear_sent_sms_verification_code(request):
    request.session.pop(SMS_VERIFICATION_SENT_TO_SESSION_KEY, None)


def _send_sms_verification_code_for_user(*, user, phone_number=None):
    phone_value = _normalize_phone_number(phone_number or getattr(user, "phone_number", ""))
    user_phone_number = _normalize_phone_number(getattr(user, "phone_number", ""))

    if not phone_value:
        return False, "وارد کردن شماره موبایل الزامی است."
    if phone_value != user_phone_number:
        return False, "شماره موبایل واردشده با حساب کاربری مطابقت ندارد."

    SMSVerificationOTP.objects.filter(
        user=user,
        phone_number=phone_value,
        is_used=False,
    ).update(is_used=True)

    otp = SMSVerificationOTP.generate_otp(user=user, phone_number=phone_value)

    try:
        send_verification_code_sms(user=user, code=otp.code)
    except Exception as exc:
        otp.is_used = True
        otp.save(update_fields=["is_used"])
        return False, str(exc)

    return True, None


def _send_email_verification_code_for_user(*, user, email):
    email_value = normalize_email_value(email)
    if not email_value:
        return False, "وارد کردن آدرس ایمیل الزامی است."

    try:
        validate_email(email_value)
    except ValidationError:
        return False, "لطفا یک آدرس ایمیل معتبر وارد کنید."

    if (
        CustomUser.objects.exclude(pk=user.pk)
        .filter(email__iexact=email_value)
        .exists()
    ):
        return False, "این آدرس ایمیل قبلاً در سیستم ثبت شده است."

    EmailVerificationOTP.objects.filter(
        user=user,
        email__iexact=email_value,
        is_used=False,
    ).update(is_used=True)

    otp = EmailVerificationOTP.generate_otp(user=user, email=email_value)

    try:
        send_verification_code_email(email=email_value, code=otp.code, user=user)
    except Exception as exc:
        otp.is_used = True
        otp.save(update_fields=["is_used"])
        return False, _email_error_response(exc)

    return True, None


def _verify_email_code_for_user(*, user, email, code):
    email_value = normalize_email_value(email)
    code_value = _normalize_verification_code(code)
    if not email_value or not code_value:
        return False, "وارد کردن ایمیل و کد الزامی است."

    try:
        validate_email(email_value)
    except ValidationError:
        return False, "لطفا یک آدرس ایمیل معتبر وارد کنید."

    if len(code_value) != 6 or not code_value.isdigit():
        return False, "کد تایید باید ۶ رقم باشد."

    otp = (
        EmailVerificationOTP.objects
        .filter(user=user, email__iexact=email_value, code=code_value)
        .order_by("-created_at")
        .first()
    )

    if not otp:
        return False, "کد تایید نامعتبر است."

    if not otp.is_valid():
        return False, "کد تایید منقضی شده یا قبلاً استفاده شده است."

    otp.is_used = True
    otp.save(update_fields=["is_used"])

    user.email = email_value
    user.is_email_verified = True
    user.save(update_fields=["email", "is_email_verified"])

    notification_service.send(
        event='accounts.signup.verified',
        subject='ایمیل شما با موفقیت تایید شد',
        body=(
            "سلام,\n\n"
            "ایمیل حساب کاربری شما با موفقیت تایید شد.\n"
            "اکنون می‌توانید از امکانات کامل حساب خود استفاده کنید."
        ),
        recipients=[email_value],
        providers=[NotificationProviderType.EMAIL],
        context={'user': user},
        metadata={'user_id': str(user.pk)},
    )

    return True, None


def _verify_sms_code_for_user(*, user, phone_number, code):
    phone_value = _normalize_phone_number(phone_number)
    code_value = _normalize_verification_code(code)
    user_phone_number = _normalize_phone_number(getattr(user, "phone_number", ""))

    if not phone_value or not code_value:
        return False, "وارد کردن شماره موبایل و کد الزامی است."
    if phone_value != user_phone_number:
        return False, "شماره موبایل واردشده با حساب کاربری مطابقت ندارد."
    if len(code_value) != 6 or not code_value.isdigit():
        return False, "کد تایید باید ۶ رقم باشد."

    otp = (
        SMSVerificationOTP.objects
        .filter(user=user, phone_number=phone_value, code=code_value)
        .order_by("-created_at")
        .first()
    )

    if not otp:
        return False, "کد تایید نامعتبر است."

    if not otp.is_valid():
        return False, "کد تایید منقضی شده یا قبلاً استفاده شده است."

    otp.is_used = True
    otp.save(update_fields=["is_used"])

    update_fields = []
    if not getattr(user, "is_sms_verified", False):
        user.is_sms_verified = True
        update_fields.append("is_sms_verified")

    if not user.is_active:
        user.is_active = True
        update_fields.append("is_active")

    if update_fields:
        user.save(update_fields=update_fields)

    return True, None


class EmailVerificationView(LoginRequiredMixin, View):
    template_name = "registration/email_verification.html"

    def get(self, request):
        if not _user_requires_email_verification(request.user):
            next_url = _safe_next_url(request, request.GET.get("next"))
            if _user_requires_sms_verification(request.user):
                sms_verification_url = reverse("sms_verification")
                next_raw = request.GET.get("next") or ""
                if next_raw:
                    return redirect(f"{sms_verification_url}?{urlencode({'next': next_raw})}")
                return redirect(sms_verification_url)
            return redirect(next_url or reverse("home"))

        alert = request.session.pop("email_verification_alert", None) or {}
        email = normalize_email_value(getattr(request.user, "email", "") or "")
        alert_type = alert.get("type") or ""
        alert_message = alert.get("message") or ""

        if email and not _has_sent_verification_code(request, email):
            ok, error_message = _send_email_verification_code_for_user(user=request.user, email=email)
            if ok:
                _remember_sent_verification_code(request, email)
                if not alert_message:
                    alert_type = "success"
                    alert_message = "کد تایید ۶ رقمی به ایمیل شما ارسال شد."
            else:
                alert_type = "error"
                alert_message = error_message or "ارسال کد تایید با خطا مواجه شد."

        return render(
            request,
            self.template_name,
            {
                "email": email,
                "has_email": bool(email),
                "next": request.GET.get("next") or "",
                "alert_type": alert_type,
                "alert_message": alert_message,
            },
        )

    def post(self, request):
        action = str(request.POST.get("action") or "").strip()
        email = normalize_email_value(request.POST.get("email")) or normalize_email_value(getattr(request.user, "email", "") or "")
        code = _normalize_verification_code(request.POST.get("code"))
        next_raw = request.POST.get("next") or request.GET.get("next") or ""
        next_url = _safe_next_url(request, next_raw)

        if action == "send_code":
            ok, error_message = _send_email_verification_code_for_user(user=request.user, email=email)
            if ok:
                _remember_sent_verification_code(request, email)
            return render(
                request,
                self.template_name,
                {
                    "email": email,
                    "has_email": bool(email),
                    "next": next_raw,
                    "alert_type": "success" if ok else "error",
                    "alert_message": "کد تایید ارسال شد." if ok else (error_message or "ارسال کد تایید با خطا مواجه شد."),
                },
            )

        if action == "verify_code":
            ok, error_message = _verify_email_code_for_user(user=request.user, email=email, code=code)
            if ok:
                _clear_sent_verification_code(request)
                if _user_requires_sms_verification(request.user):
                    request.session[SMS_VERIFICATION_ALERT_SESSION_KEY] = {
                        "type": "success",
                        "message": "ایمیل با موفقیت تایید شد. حالا کد تایید پیامکی را وارد کنید.",
                    }
                    sms_verification_url = reverse("sms_verification")
                    if next_raw:
                        return redirect(f"{sms_verification_url}?{urlencode({'next': next_raw})}")
                    return redirect(sms_verification_url)
                return redirect(next_url or reverse("home"))
            return render(
                request,
                self.template_name,
                {
                    "email": email,
                    "has_email": bool(email),
                    "next": next_raw,
                    "alert_type": "error",
                    "alert_message": error_message or "تایید ایمیل با خطا مواجه شد.",
                },
            )

        return render(
            request,
            self.template_name,
            {
                "email": email or (getattr(request.user, "email", "") or ""),
                "has_email": bool(email or getattr(request.user, "email", "")),
                "next": next_raw,
                "alert_type": "error",
                "alert_message": "درخواست نامعتبر است.",
            },
        )


class SMSVerificationView(LoginRequiredMixin, View):
    template_name = "registration/sms_verification.html"

    def get(self, request):
        if _user_requires_email_verification(request.user):
            email_verification_url = reverse("email_verification")
            next_raw = request.GET.get("next") or ""
            if next_raw:
                return redirect(f"{email_verification_url}?{urlencode({'next': next_raw})}")
            return redirect(email_verification_url)

        if not _user_requires_sms_verification(request.user):
            next_url = _safe_next_url(request, request.GET.get("next"))
            return redirect(next_url or reverse("home"))

        alert = request.session.pop(SMS_VERIFICATION_ALERT_SESSION_KEY, None) or {}
        phone_number = _normalize_phone_number(getattr(request.user, "phone_number", "") or "")
        alert_type = alert.get("type") or ""
        alert_message = alert.get("message") or ""

        if phone_number and not _has_sent_sms_verification_code(request, phone_number):
            ok, error_message = _send_sms_verification_code_for_user(user=request.user, phone_number=phone_number)
            if ok:
                _remember_sent_sms_verification_code(request, phone_number)
                if not alert_message:
                    alert_type = "success"
                    alert_message = "کد تایید پیامکی برای شما ارسال شد."
            else:
                alert_type = "error"
                alert_message = error_message or "ارسال کد تایید پیامکی با خطا مواجه شد."

        return render(
            request,
            self.template_name,
            {
                "phone_number": phone_number,
                "has_phone_number": bool(phone_number),
                "next": request.GET.get("next") or "",
                "alert_type": alert_type,
                "alert_message": alert_message,
            },
        )

    def post(self, request):
        action = str(request.POST.get("action") or "").strip()
        phone_number = _normalize_phone_number(
            request.POST.get("phone_number") or getattr(request.user, "phone_number", "") or ""
        )
        code = _normalize_verification_code(request.POST.get("code"))
        next_raw = request.POST.get("next") or request.GET.get("next") or ""
        next_url = _safe_next_url(request, next_raw)

        if action == "send_code":
            ok, error_message = _send_sms_verification_code_for_user(user=request.user, phone_number=phone_number)
            if ok:
                _remember_sent_sms_verification_code(request, phone_number)
            return render(
                request,
                self.template_name,
                {
                    "phone_number": phone_number,
                    "has_phone_number": bool(phone_number),
                    "next": next_raw,
                    "alert_type": "success" if ok else "error",
                    "alert_message": "کد تایید پیامکی ارسال شد." if ok else (
                        error_message or "ارسال کد تایید پیامکی با خطا مواجه شد."
                    ),
                },
            )

        if action == "verify_code":
            ok, error_message = _verify_sms_code_for_user(
                user=request.user,
                phone_number=phone_number,
                code=code,
            )
            if ok:
                _clear_sent_sms_verification_code(request)
                return redirect(next_url or reverse("home"))
            return render(
                request,
                self.template_name,
                {
                    "phone_number": phone_number,
                    "has_phone_number": bool(phone_number),
                    "next": next_raw,
                    "alert_type": "error",
                    "alert_message": error_message or "تایید پیامک با خطا مواجه شد.",
                },
            )

        return render(
            request,
            self.template_name,
            {
                "phone_number": phone_number,
                "has_phone_number": bool(phone_number),
                "next": next_raw,
                "alert_type": "error",
                "alert_message": "درخواست نامعتبر است.",
            },
        )


@login_required
@require_POST
def send_email_verification(request):
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"error": "Invalid JSON payload."}, status=400)

    email = normalize_email_value(payload.get("email"))
    requested_user_id = str(payload.get("user_id") or "").strip()
    if not email:
        return JsonResponse({"error": "Email is required."}, status=400)

    try:
        validate_email(email)
    except ValidationError:
        return JsonResponse({"error": "A valid email address is required."}, status=400)

    if requested_user_id and requested_user_id != str(request.user.pk):
        return JsonResponse({"error": "You can only request email verification for your own account."}, status=403)

    if (
        CustomUser.objects.exclude(pk=request.user.pk)
        .filter(email__iexact=email)
        .exists()
    ):
        return JsonResponse({"error": "This email address is already in use."}, status=400)

    ok, error_message = _send_email_verification_code_for_user(user=request.user, email=email)
    if not ok:
        return JsonResponse({"error": error_message or "Failed to send verification code."}, status=500)

    _remember_sent_verification_code(request, email)
    return JsonResponse({"message": "Verification code sent successfully."})


@login_required
@require_POST
def verify_email_code(request):
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"error": "Invalid JSON payload."}, status=400)

    email = normalize_email_value(payload.get("email"))
    code = _normalize_verification_code(payload.get("code"))
    if not email or not code:
        return JsonResponse({"error": "Email and code are required."}, status=400)

    try:
        validate_email(email)
    except ValidationError:
        return JsonResponse({"error": "A valid email address is required."}, status=400)

    ok, error_message = _verify_email_code_for_user(user=request.user, email=email, code=code)
    if not ok:
        return JsonResponse({"error": error_message or "Email verification failed."}, status=400)

    _clear_sent_verification_code(request)
    return JsonResponse({"message": "Email verified successfully."})
