from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm, AuthenticationForm, PasswordResetForm
from django.core.exceptions import ValidationError
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from decimal import Decimal, InvalidOperation

from core.emailing import send_plain_email

# ایمپورت CreditIncreaseRequest حذف شد چون دیگر در این فایل استفاده نمی‌شود
from .models import CustomUser, VerificationRequest


PERSIAN_REQUIRED_MESSAGE = "لطفا این فیلد را کامل کنید"
PERSIAN_EMAIL_REQUIRED_MESSAGE = "لطفا آدرس ایمیل را کامل کنید"
PERSIAN_EMAIL_INVALID_MESSAGE = "لطفا یک آدرس ایمیل معتبر وارد کنید"
PERSIAN_FULL_NAME_REQUIRED_MESSAGE = "لطفا نام و نام خانوادگی را کامل کنید"
PERSIAN_PASSWORD_REQUIRED_MESSAGE = "لطفا رمز عبور را کامل کنید"
PERSIAN_PASSWORD_CONFIRM_REQUIRED_MESSAGE = "لطفا تکرار رمز عبور را کامل کنید"
PERSIAN_PASSWORD_MIN_LENGTH_MESSAGE = "رمز عبور باید حداقل ۸ کاراکتر باشد."
PERSIAN_PASSWORD_PATTERN_MESSAGE = (
    "رمز عبور باید حداقل ۸ کاراکتر و شامل حرف بزرگ، حرف کوچک و کاراکتر ویژه باشد."
)


def _escape_js_string(value):
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


def _get_required_browser_message(field):
    label = str(getattr(field, "label", "") or "").strip()
    if "تکرار رمز عبور" in label:
        return PERSIAN_PASSWORD_CONFIRM_REQUIRED_MESSAGE
    if "رمز عبور" in label:
        return PERSIAN_PASSWORD_REQUIRED_MESSAGE
    if "نام و نام خانوادگی" in label:
        return PERSIAN_FULL_NAME_REQUIRED_MESSAGE
    if "ایمیل" in label:
        return PERSIAN_EMAIL_REQUIRED_MESSAGE
    return PERSIAN_REQUIRED_MESSAGE


def _apply_password_browser_validation_attrs(field):
    field.widget.attrs["minlength"] = "8"
    field.widget.attrs["pattern"] = r"(?=.*[A-Z])(?=.*[a-z])(?=.*[^A-Za-z0-9\s]).{8,}"


def _apply_persian_browser_validation(field):
    if isinstance(
        field.widget,
        (forms.CheckboxInput, forms.CheckboxSelectMultiple, forms.RadioSelect, forms.Select, forms.SelectMultiple),
    ):
        return

    required_message = _escape_js_string(_get_required_browser_message(field))
    rules = ["if (this.validity.valueMissing) {" f"this.setCustomValidity('{required_message}');" "}"]

    if isinstance(field, forms.EmailField):
        rules.append(
            f"else if (this.validity.typeMismatch) {{this.setCustomValidity('{_escape_js_string(PERSIAN_EMAIL_INVALID_MESSAGE)}');}}"
        )

    if isinstance(field.widget, forms.PasswordInput):
        rules.append(
            f"else if (this.validity.tooShort) {{this.setCustomValidity('{_escape_js_string(PERSIAN_PASSWORD_MIN_LENGTH_MESSAGE)}');}}"
        )
        rules.append(
            f"else if (this.validity.patternMismatch) {{this.setCustomValidity('{_escape_js_string(PERSIAN_PASSWORD_PATTERN_MESSAGE)}');}}"
        )

    rules.append("else {this.setCustomValidity('');}")
    field.widget.attrs["oninvalid"] = "".join(rules)
    field.widget.attrs["oninput"] = "this.setCustomValidity('')"


def _apply_persian_error_messages(form):
    default_english_messages = {
        "required": "This field is required.",
    }

    for field in form.fields.values():
        if field.error_messages.get("required") in (None, "", default_english_messages["required"]):
            field.error_messages["required"] = "وارد کردن این فیلد الزامی است."
        _apply_persian_browser_validation(field)
        field.error_messages.setdefault("invalid", "مقدار وارد شده معتبر نیست.")
        field.error_messages.setdefault("invalid_choice", "گزینه انتخاب‌شده معتبر نیست.")
        field.error_messages.setdefault("invalid_list", "مقادیر انتخاب‌شده معتبر نیستند.")
        field.error_messages.setdefault(
            "max_length",
            "تعداد کاراکترهای واردشده نباید بیشتر از %(limit_value)s باشد.",
        )
        field.error_messages.setdefault(
            "min_length",
            "تعداد کاراکترهای واردشده باید حداقل %(limit_value)s باشد.",
        )

        if isinstance(field, forms.EmailField):
            field.error_messages["invalid"] = "آدرس ایمیل معتبر نیست."

# ==========================================
# فرم شخصی‌سازی شده برای ورود (تغییر ارور انگلیسی به فارسی)
# ==========================================
class CustomLoginForm(AuthenticationForm):
    
    def get_invalid_login_error(self):
        return ValidationError(
            "شماره موبایل یا رمز عبور اشتباه است. لطفاً دوباره بررسی کنید.",
            code='invalid_login',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_persian_error_messages(self)
        # AuthenticationForm به صورت پیش‌فرض پیام required انگلیسی دارد؛ اینجا قطعی فارسی می‌کنیم.
        self.fields["username"].error_messages["required"] = "وارد کردن این فیلد الزامی است."
        self.fields["password"].error_messages["required"] = "وارد کردن این فیلد الزامی است."

        input_style = (
            'w-full h-12 px-4 rounded-xl border border-gray-300 bg-white/50 text-gray-900 '
            'placeholder-gray-500 focus:bg-white focus:border-primary focus:ring-2 focus:ring-primary/20 '
            'transition-all duration-200 outline-none text-left dir-ltr text-base'
        )

        self.fields['username'].widget.attrs.update({
            'class': input_style,
            'placeholder': 'شماره موبایل...',
            'inputmode': 'numeric'
        })
        self.fields['username'].label = "شماره موبایل"

        self.fields['password'].widget.attrs.update({
            'class': input_style,
            'placeholder': '••••••••'
        })
        self.fields['password'].label = "رمز عبور"


class CustomPasswordResetForm(PasswordResetForm):
    """Password reset form that routes delivery through NotificationService."""

    def send_mail(
        self,
        subject_template_name,
        email_template_name,
        context,
        from_email,
        to_email,
        html_email_template_name=None,
    ):
        subject = render_to_string(subject_template_name, context)
        subject = "".join(subject.splitlines()).strip()
        body = render_to_string(email_template_name, context)
        plain_body = strip_tags(body).strip() or body.strip()
        send_plain_email(
            event='accounts.password.reset_requested',
            subject=subject,
            message=plain_body,
            recipients=[to_email],
            fail_silently=False,
            metadata={
                'user_id': str(getattr(context.get('user'), 'pk', '') or ''),
                'reset_url': context.get('protocol', '') + '://' + context.get('domain', ''),
            },
            context=context,
        )


class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(label="آدرس ایمیل", required=True)
    full_name = forms.CharField(label="نام و نام خانوادگی", max_length=150, required=False)
    phone_number = forms.CharField(label="شماره موبایل", max_length=15, required=True)

    class Meta:
        model = CustomUser
        fields = ("username", "email", "full_name", "phone_number")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_persian_error_messages(self)
        _apply_password_browser_validation_attrs(self.fields["password1"])
        _apply_password_browser_validation_attrs(self.fields["password2"])

        input_style = (
            'w-full h-12 px-4 rounded-xl border border-gray-300 bg-white/50 text-gray-900 '
            'placeholder-gray-500 focus:bg-white focus:border-primary focus:ring-2 focus:ring-primary/20 '
            'transition-all duration-200 outline-none text-right dir-rtl text-base'
        )

        self.fields['username'].label = "نام کاربری"

        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = input_style
            field.widget.attrs['placeholder'] = f"{field.label}..."


class CustomUserChangeForm(UserChangeForm):
    email = forms.EmailField(label="آدرس ایمیل", required=True)
    full_name = forms.CharField(label="نام و نام خانوادگی", max_length=150, required=False)
    phone_number = forms.CharField(label="شماره موبایل", max_length=15, required=True)

    class Meta:
        model = CustomUser
        fields = ("username", "email", "full_name", "phone_number")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_persian_error_messages(self)

        input_style = (
            'w-full h-12 px-4 rounded-xl border border-gray-300 bg-white/50 text-gray-900 '
            'placeholder-gray-500 focus:bg-white focus:border-primary focus:ring-2 focus:ring-primary/20 '
            'transition-all duration-200 outline-none text-right dir-rtl text-base'
        )

        self.fields['username'].label = "نام کاربری"

        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = input_style
            field.widget.attrs['placeholder'] = f"{field.label}..."


class PublicSignupForm(forms.ModelForm):
    CONTACT_METHOD_CHOICES = [
        ("call", "تماس تلفنی"),
        ("sms", "پیامک"),
        ("email", "ایمیل"),
        ("whatsapp", "واتساپ"),
        ("telegram", "تلگرام"),
    ]

    full_name = forms.CharField(label="نام و نام خانوادگی", max_length=150, required=False)
    participate_in_auction = forms.BooleanField(
        label="شرکت در مزایده",
        required=False,
    )
    newsletter_catalog_opt_in = forms.BooleanField(
        label="تمایل به دریافت خبرنامه و کاتالوگ",
        required=False,
    )
    phone_number = forms.CharField(label="شماره موبایل(نام کاربری)", max_length=20, required=True)
    address_street = forms.CharField(label="آدرس", max_length=255, required=False)
    email = forms.EmailField(label="آدرس ایمیل", required=True)
    preferred_contact_methods = forms.MultipleChoiceField(
        label="راه ارتباطی مورد نظر",
        choices=CONTACT_METHOD_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    telegram_id = forms.CharField(label="ایدی تلگرام", max_length=255, required=False)
    password1 = forms.CharField(label="رمز عبور", required=True, widget=forms.PasswordInput)
    password2 = forms.CharField(label="تکرار رمز عبور", required=True, widget=forms.PasswordInput)

    class Meta:
        model = CustomUser
        fields = (
            "full_name",
            "phone_number",
            "address_street",
            "email",
            "preferred_contact_methods",
            "telegram_id",
        )
 
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_persian_error_messages(self)
        _apply_password_browser_validation_attrs(self.fields["password1"])
        _apply_password_browser_validation_attrs(self.fields["password2"])

        input_style = (
            "w-full h-12 px-4 rounded-xl border border-gray-300 bg-white/50 text-gray-900 "
            "placeholder-gray-500 focus:bg-white focus:border-primary focus:ring-2 focus:ring-primary/20 "
            "transition-all duration-200 outline-none text-right dir-rtl text-base"
        )

        password_style = (
            "w-full h-12 px-4 rounded-xl border border-gray-300 bg-white/50 text-gray-900 "
            "placeholder-gray-500 focus:bg-white focus:border-primary focus:ring-2 focus:ring-primary/20 "
            "transition-all duration-200 outline-none text-left dir-ltr text-base"
        )

        for field_name in ("full_name", "address_street"):
            self.fields[field_name].widget.attrs["class"] = input_style
            self.fields[field_name].widget.attrs["placeholder"] = f"{self.fields[field_name].label}..."

        self.fields["phone_number"].widget.attrs["class"] = (
            "w-full h-12 px-4 rounded-xl border border-gray-300 bg-white/50 text-gray-900 "
            "placeholder-gray-500 focus:bg-white focus:border-primary focus:ring-2 focus:ring-primary/20 "
            "transition-all duration-200 outline-none text-left dir-ltr text-base"
        )
        self.fields["phone_number"].widget.attrs["placeholder"] = "شماره موبایل..."
        self.fields["phone_number"].widget.attrs["inputmode"] = "numeric"
        self.fields["phone_number"].widget.attrs["maxlength"] = "11"
        self.fields["phone_number"].widget.attrs["pattern"] = "0[0-9]{10}"

        self.fields["email"].widget.attrs["class"] = (
            "w-full h-12 px-4 rounded-xl border border-gray-300 bg-white/50 text-gray-900 "
            "placeholder-gray-500 focus:bg-white focus:border-primary focus:ring-2 focus:ring-primary/20 "
            "transition-all duration-200 outline-none text-left dir-ltr text-base"
        )
        self.fields["email"].widget.attrs["placeholder"] = "آدرس ایمیل..."
        self.fields["email"].widget.attrs["inputmode"] = "email"

        self.fields["telegram_id"].widget.attrs["class"] = (
            "w-full h-12 px-4 rounded-xl border border-gray-300 bg-white/50 text-gray-900 "
            "placeholder-gray-500 focus:bg-white focus:border-primary focus:ring-2 focus:ring-primary/20 "
            "transition-all duration-200 outline-none text-left dir-ltr text-base"
        )
        self.fields["telegram_id"].widget.attrs["placeholder"] = "در صورت تفاوت با شماره موبایل"

        self.fields["password1"].widget.attrs["class"] = password_style
        self.fields["password1"].widget.attrs["placeholder"] = "••••••••"

        self.fields["password2"].widget.attrs["class"] = password_style
        self.fields["password2"].widget.attrs["placeholder"] = "••••••••"

    def clean_phone_number(self):
        raw = (self.cleaned_data.get("phone_number") or "").strip()
        digit_map = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
        normalized = raw.translate(digit_map).replace(" ", "").replace("-", "")
        normalized = "".join(ch for ch in normalized if ch.isdigit())

        if not normalized.startswith("0"):
            raise ValidationError("شماره موبایل باید با ۰ شروع شود.")
        if len(normalized) != 11:
            raise ValidationError("شماره موبایل باید دقیقاً ۱۱ رقم باشد.")

        # اطمینان از یکتا بودن شماره موبایل در زمان ثبت نام
        if CustomUser.objects.filter(phone_number=normalized).exists():
            raise ValidationError("این شماره موبایل قبلاً در سیستم ثبت شده است.")

        return normalized

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if not email:
            return email
        if CustomUser.objects.filter(email__iexact=email).exists():
            raise ValidationError("این آدرس ایمیل قبلاً در سیستم ثبت شده است.")
        return email

    def clean_telegram_id(self):
        telegram_id = (self.cleaned_data.get("telegram_id") or "").strip()
        return telegram_id or None

    def clean_password1(self):
        password = self.cleaned_data.get("password1") or ""

        errors = []
        if len(password) < 8:
            errors.append("رمز عبور باید حداقل ۸ کاراکتر باشد.")

        has_upper = any("A" <= ch <= "Z" for ch in password)
        has_lower = any("a" <= ch <= "z" for ch in password)
        has_special = any((not ch.isalnum()) and (not ch.isspace()) for ch in password)

        if not has_upper:
            errors.append("حداقل یک حرف بزرگ انگلیسی (A-Z) لازم است.")
        if not has_lower:
            errors.append("حداقل یک حرف کوچک انگلیسی (a-z) لازم است.")
        if not has_special:
            errors.append("حداقل یک کاراکتر ویژه مثل @ یا # لازم است.")

        if errors:
            raise ValidationError(errors)

        return password

    def clean(self):
        cleaned_data = super().clean()
        participate = cleaned_data.get("participate_in_auction") or False
        full_name = (cleaned_data.get("full_name") or "").strip()
        if participate:
            if not full_name:
                self.add_error("full_name", "در صورت شرکت در مزایده، وارد کردن نام و نام خانوادگی الزامی است.")

        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "رمز عبور و تکرار آن یکسان نیستند.")

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)

        user.full_name = (self.cleaned_data.get("full_name") or "").strip()
        user.phone_number = self.cleaned_data["phone_number"]
        # بر اساس منطق CustomUserManager، یوزرنیم همان شماره موبایل است
        user.username = user.phone_number

        address = (self.cleaned_data.get("address_street") or "").strip()
        user.address_street = address or None

        user.email = self.cleaned_data.get("email")
        user.is_email_verified = False
        user.preferred_contact_methods = self.cleaned_data.get("preferred_contact_methods") or []
        user.newsletter_catalog_opt_in = bool(
            self.cleaned_data.get("newsletter_catalog_opt_in")
        )
        user.telegram_id = self.cleaned_data.get("telegram_id")

        # رمزنگاری و ثبت پسورد
        user.set_password(self.cleaned_data["password1"])

        if commit:
            user.save()

            # در صورت انتخاب شرکت در مزایده، درخواست وریفای ثبت می‌شود
            participate = self.cleaned_data.get("participate_in_auction")
            if participate and int(getattr(user, "is_verified", 0) or 0) != 1:
                has_pending = VerificationRequest.objects.filter(
                    user=user,
                    status=VerificationRequest.RequestStatus.PENDING,
                ).exists()
                if not has_pending:
                    VerificationRequest.objects.create(
                        user=user,
                        full_name=user.full_name,
                        phone_number=user.phone_number,
                        status=VerificationRequest.RequestStatus.PENDING,
                        is_verified=0,
                    )

        return user


class SendCustomEmailForm(forms.Form):
    _selected_action = forms.CharField(widget=forms.MultipleHiddenInput)
    subject = forms.CharField(max_length=255, label="موضوع (Subject)")
    message = forms.CharField(widget=forms.Textarea, label="پیام (Message)")


class PublicProfileUpdateForm(forms.ModelForm):
    CONTACT_METHOD_CHOICES = PublicSignupForm.CONTACT_METHOD_CHOICES

    full_name = forms.CharField(label="نام و نام خانوادگی", max_length=150, required=False)
    participate_in_auction = forms.BooleanField(
        label="شرکت در مزایده",
        required=False,
    )
    phone_number = forms.CharField(label="شماره موبایل(نام کاربری)", max_length=20, required=True)
    address_street = forms.CharField(label="آدرس", max_length=255, required=False)
    email = forms.EmailField(label="آدرس ایمیل", required=True)
    preferred_contact_methods = forms.MultipleChoiceField(
        label="راه ارتباطی مورد نظر",
        choices=CONTACT_METHOD_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    telegram_id = forms.CharField(label="ایدی تلگرام", max_length=255, required=False)
    password1 = forms.CharField(label="رمز عبور", required=False, widget=forms.PasswordInput)
    password2 = forms.CharField(label="تکرار رمز عبور", required=False, widget=forms.PasswordInput)

    class Meta:
        model = CustomUser
        fields = (
            "full_name",
            "phone_number",
            "address_street",
            "email",
            "preferred_contact_methods",
            "telegram_id",
        )

    def __init__(self, *args, **kwargs):
        has_auction_opt_in = bool(kwargs.pop("has_auction_opt_in", False))
        super().__init__(*args, **kwargs)
        _apply_persian_error_messages(self)
        _apply_password_browser_validation_attrs(self.fields["password1"])
        _apply_password_browser_validation_attrs(self.fields["password2"])

        input_style = (
            "w-full h-12 px-4 rounded-xl border border-gray-300 bg-white/50 text-gray-900 "
            "placeholder-gray-500 focus:bg-white focus:border-primary focus:ring-2 focus:ring-primary/20 "
            "transition-all duration-200 outline-none text-right dir-rtl text-base"
        )

        password_style = (
            "w-full h-12 px-4 rounded-xl border border-gray-300 bg-white/50 text-gray-900 "
            "placeholder-gray-500 focus:bg-white focus:border-primary focus:ring-2 focus:ring-primary/20 "
            "transition-all duration-200 outline-none text-left dir-ltr text-base"
        )

        for field_name in ("full_name", "address_street"):
            self.fields[field_name].widget.attrs["class"] = input_style
            self.fields[field_name].widget.attrs["placeholder"] = f"{self.fields[field_name].label}..."

        self.fields["phone_number"].widget.attrs["class"] = (
            "w-full h-12 px-4 rounded-xl border border-gray-300 bg-white/50 text-gray-900 "
            "placeholder-gray-500 focus:bg-white focus:border-primary focus:ring-2 focus:ring-primary/20 "
            "transition-all duration-200 outline-none text-left dir-ltr text-base"
        )
        self.fields["phone_number"].widget.attrs["placeholder"] = "شماره موبایل..."
        self.fields["phone_number"].widget.attrs["inputmode"] = "numeric"
        self.fields["phone_number"].widget.attrs["maxlength"] = "11"
        self.fields["phone_number"].widget.attrs["pattern"] = "0[0-9]{10}"

        self.fields["email"].widget.attrs["class"] = (
            "w-full h-12 px-4 rounded-xl border border-gray-300 bg-white/50 text-gray-900 "
            "placeholder-gray-500 focus:bg-white focus:border-primary focus:ring-2 focus:ring-primary/20 "
            "transition-all duration-200 outline-none text-left dir-ltr text-base"
        )
        self.fields["email"].widget.attrs["placeholder"] = "آدرس ایمیل..."
        self.fields["email"].widget.attrs["inputmode"] = "email"

        self.fields["telegram_id"].widget.attrs["class"] = (
            "w-full h-12 px-4 rounded-xl border border-gray-300 bg-white/50 text-gray-900 "
            "placeholder-gray-500 focus:bg-white focus:border-primary focus:ring-2 focus:ring-primary/20 "
            "transition-all duration-200 outline-none text-left dir-ltr text-base"
        )
        self.fields["telegram_id"].widget.attrs["placeholder"] = "در صورت تفاوت با شماره موبایل"

        self.fields["password1"].widget.attrs["class"] = password_style
        self.fields["password1"].widget.attrs["placeholder"] = "••••••••"

        self.fields["password2"].widget.attrs["class"] = password_style
        self.fields["password2"].widget.attrs["placeholder"] = "••••••••"

        if has_auction_opt_in:
            self.fields["participate_in_auction"].initial = True

    def clean_phone_number(self):
        raw = (self.cleaned_data.get("phone_number") or "").strip()
        digit_map = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
        normalized = raw.translate(digit_map).replace(" ", "").replace("-", "")
        normalized = "".join(ch for ch in normalized if ch.isdigit())

        if not normalized.startswith("0"):
            raise ValidationError("شماره موبایل باید با ۰ شروع شود.")
        if len(normalized) != 11:
            raise ValidationError("شماره موبایل باید دقیقاً ۱۱ رقم باشد.")

        qs = CustomUser.objects.filter(phone_number=normalized)
        if self.instance and getattr(self.instance, "pk", None):
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("این شماره موبایل قبلاً ثبت شده است.")

        return normalized

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if not email:
            return email
        qs = CustomUser.objects.filter(email__iexact=email)
        if self.instance and getattr(self.instance, "pk", None):
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("این آدرس ایمیل قبلاً در سیستم ثبت شده است.")
        return email

    def clean_telegram_id(self):
        telegram_id = (self.cleaned_data.get("telegram_id") or "").strip()
        return telegram_id or None

    def clean_password1(self):
        password = self.cleaned_data.get("password1") or ""
        if not password:
            return ""

        errors = []
        if len(password) < 8:
            errors.append("رمز عبور باید حداقل ۸ کاراکتر باشد.")

        has_upper = any("A" <= ch <= "Z" for ch in password)
        has_lower = any("a" <= ch <= "z" for ch in password)
        has_special = any((not ch.isalnum()) and (not ch.isspace()) for ch in password)

        if not has_upper:
            errors.append("حداقل یک حرف بزرگ انگلیسی (A-Z) لازم است.")
        if not has_lower:
            errors.append("حداقل یک حرف کوچک انگلیسی (a-z) لازم است.")
        if not has_special:
            errors.append("حداقل یک کاراکتر ویژه مثل @ یا # لازم است.")

        if errors:
            raise ValidationError(errors)

        return password

    def clean(self):
        cleaned_data = super().clean()
        preferred = cleaned_data.get("preferred_contact_methods") or []
        email = cleaned_data.get("email")

        if "email" in preferred and not email:
            self.add_error("email", "در صورت انتخاب «ایمیل»، وارد کردن آدرس ایمیل الزامی است.")

        participate = cleaned_data.get("participate_in_auction") or False
        full_name = (cleaned_data.get("full_name") or "").strip()
        if participate and not full_name:
            self.add_error("full_name", "در صورت شرکت در مزایده، وارد کردن نام و نام خانوادگی الزامی است.")

        password1 = cleaned_data.get("password1") or ""
        password2 = cleaned_data.get("password2") or ""
        if password1 or password2:
            if not password1:
                self.add_error("password1", "رمز عبور را وارد کنید.")
            if not password2:
                self.add_error("password2", "تکرار رمز عبور را وارد کنید.")
            if password1 and password2 and password1 != password2:
                self.add_error("password2", "رمز عبور و تکرار آن یکسان نیستند.")

        return cleaned_data

    def save(self, commit=True):
        previous_email = ""
        if self.instance and getattr(self.instance, "pk", None):
            previous_email = (
                CustomUser.objects
                .filter(pk=self.instance.pk)
                .values_list("email", flat=True)
                .first()
                or ""
            )

        user = super().save(commit=False)

        user.full_name = (self.cleaned_data.get("full_name") or "").strip()
        user.phone_number = self.cleaned_data["phone_number"]
        user.username = user.phone_number

        address = (self.cleaned_data.get("address_street") or "").strip()
        user.address_street = address or None

        user.email = self.cleaned_data.get("email")
        if (previous_email or "").strip().lower() != (user.email or "").strip().lower():
            user.is_email_verified = False
        user.preferred_contact_methods = self.cleaned_data.get("preferred_contact_methods") or []
        user.telegram_id = self.cleaned_data.get("telegram_id")

        password = self.cleaned_data.get("password1") or ""
        if password:
            user.set_password(password)

        if commit:
            user.save()
            
            participate = self.cleaned_data.get("participate_in_auction")
            if participate and int(getattr(user, "is_verified", 0) or 0) != 1:
                has_pending = VerificationRequest.objects.filter(
                    user=user,
                    status=VerificationRequest.RequestStatus.PENDING,
                ).exists()
                if not has_pending:
                    VerificationRequest.objects.create(
                        user=user,
                        full_name=user.full_name,
                        phone_number=user.phone_number,
                        status=VerificationRequest.RequestStatus.PENDING,
                        is_verified=0,
                    )
                
        return user


def _split_full_name_parts(full_name):
    normalized_name = " ".join((full_name or "").split())
    if not normalized_name:
        return "", ""

    first_part, separator, remaining_parts = normalized_name.partition(" ")
    return first_part, remaining_parts if separator else ""


class AdminUserEditForm(forms.ModelForm):
    CONTACT_METHOD_CHOICES = PublicSignupForm.CONTACT_METHOD_CHOICES
    new_password = forms.CharField(label="رمز عبور جدید", required=False)
    clear_profile_picture = forms.BooleanField(required=False)
    preferred_contact_methods = forms.MultipleChoiceField(
        label="راه‌های ارتباطی ترجیحی",
        choices=CONTACT_METHOD_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = CustomUser
        fields = (
            "username",
            "full_name",
            "phone_number",
            "email",
            "preferred_contact_methods",
            "newsletter_catalog_opt_in",
            "telegram_id",
            "address_country",
            "address_city",
            "address_street",
            "description",
            "profile_picture",
            "is_active",
            "is_staff",
            "is_superuser",
            "is_verified",
            "credit",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_persian_error_messages(self)
        self.fields["username"].required = False
        _apply_password_browser_validation_attrs(self.fields["new_password"])

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        if not username:
            return ""

        qs = CustomUser.objects.filter(username=username)
        if self.instance and getattr(self.instance, "pk", None):
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("این نام کاربری قبلاً ثبت شده است.")

        return username

    def clean_phone_number(self):
        raw = (self.cleaned_data.get("phone_number") or "").strip()
        digit_map = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
        normalized = raw.translate(digit_map).replace(" ", "").replace("-", "")
        normalized = "".join(ch for ch in normalized if ch.isdigit())

        if not normalized.startswith("0"):
            raise ValidationError("شماره موبایل باید با ۰ شروع شود.")
        if len(normalized) != 11:
            raise ValidationError("شماره موبایل باید دقیقاً ۱۱ رقم باشد.")

        qs = CustomUser.objects.filter(phone_number=normalized)
        if self.instance and getattr(self.instance, "pk", None):
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("این شماره موبایل قبلاً ثبت شده است.")

        return normalized

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip()
        if not email:
            return None

        qs = CustomUser.objects.filter(email=email)
        if self.instance and getattr(self.instance, "pk", None):
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("این ایمیل قبلاً ثبت شده است.")

        return email

    def clean_telegram_id(self):
        telegram_id = (self.cleaned_data.get("telegram_id") or "").strip()
        if not telegram_id:
            return None

        qs = CustomUser.objects.filter(telegram_id=telegram_id)
        if self.instance and getattr(self.instance, "pk", None):
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("این شناسه تلگرام قبلاً ثبت شده است.")

        return telegram_id

    def clean_new_password(self):
        password = self.cleaned_data.get("new_password") or ""
        if not password:
            return ""

        errors = []
        if len(password) < 8:
            errors.append("رمز عبور باید حداقل ۸ کاراکتر باشد.")

        has_upper = any("A" <= ch <= "Z" for ch in password)
        has_lower = any("a" <= ch <= "z" for ch in password)
        has_special = any((not ch.isalnum()) and (not ch.isspace()) for ch in password)

        if not has_upper:
            errors.append("حداقل یک حرف بزرگ انگلیسی (A-Z) لازم است.")
        if not has_lower:
            errors.append("حداقل یک حرف کوچک انگلیسی (a-z) لازم است.")
        if not has_special:
            errors.append("حداقل یک کاراکتر ویژه مثل @ یا # لازم است.")

        if errors:
            raise ValidationError(errors)

        return password

    def _get_existing_credit_snapshot(self):
        if not self.instance or not getattr(self.instance, "pk", None):
            return {
                "credit": Decimal("0"),
                "current_credit": Decimal("0"),
                "is_verified": 0,
            }

        snapshot = (
            CustomUser.objects
            .filter(pk=self.instance.pk)
            .values("credit", "current_credit", "is_verified")
            .first()
        ) or {}
        return {
            "credit": Decimal(str(snapshot.get("credit") or 0)),
            "current_credit": Decimal(str(snapshot.get("current_credit") or 0)),
            "is_verified": int(snapshot.get("is_verified") or 0),
        }

    def clean(self):
        cleaned_data = super().clean()
        normalized_phone_number = cleaned_data.get("phone_number") or ""
        if normalized_phone_number:
            cleaned_data["username"] = normalized_phone_number

        requested_is_verified = int(cleaned_data.get("is_verified") or 0)
        requested_credit = Decimal(str(cleaned_data.get("credit") or 0))
        snapshot = self._get_existing_credit_snapshot()
        existing_is_verified = snapshot["is_verified"]
        reserved_auction_credit = (
            self.instance.get_reserved_auction_credit()
            if self.instance and getattr(self.instance, "pk", None)
            else Decimal("0")
        )

        has_reserved_auction_credit = (
            existing_is_verified == 1
            and reserved_auction_credit > Decimal("0")
        )

        if has_reserved_auction_credit and requested_credit < reserved_auction_credit:
            self.add_error(
                "credit",
                "تا وقتی بخشی از اعتبار کاربر در مزایده رزرو شده است، اعتبار کل نمی‌تواند از مبلغ رزروشده کمتر شود.",
            )

        if has_reserved_auction_credit and requested_is_verified == 0:
            self.add_error(
                "is_verified",
                "تا وقتی بخشی از اعتبار کاربر در مزایده رزرو شده است، نمی‌توان دسترسی مزایده را از کاربر گرفت.",
            )

        if requested_is_verified == 0:
            cleaned_data["credit"] = Decimal("0")

        preferred = cleaned_data.get("preferred_contact_methods") or []
        email = cleaned_data.get("email")
        if "email" in preferred and not email:
            self.add_error("email", "در صورت انتخاب «ایمیل»، وارد کردن آدرس ایمیل الزامی است.")

        return cleaned_data

    def _post_clean(self):
        requested_is_verified = int(self.data.get("is_verified") or 0)
        requested_credit = Decimal(str(self.data.get("credit") or 0))
        reserved_auction_credit = (
            self.instance.get_reserved_auction_credit()
            if self.instance and getattr(self.instance, "pk", None)
            else Decimal("0")
        )

        if requested_is_verified == 0:
            self.instance.current_credit = Decimal("0")
        else:
            self.instance.current_credit = max(requested_credit - reserved_auction_credit, Decimal("0"))

        super()._post_clean()

    def _sync_user_verification_request(self, user, previous_is_verified):
        current_is_verified = int(getattr(user, "is_verified", 0) or 0)
        if current_is_verified == previous_is_verified:
            return

        latest_request = (
            VerificationRequest.objects
            .filter(user=user)
            .order_by("-created_at", "-pk")
            .first()
        )

        if current_is_verified == 1:
            target_request = latest_request
            if target_request is None:
                VerificationRequest.objects.create(
                    user=user,
                    full_name=(user.full_name or "").strip(),
                    phone_number=user.phone_number,
                    status=VerificationRequest.RequestStatus.APPROVED,
                    is_verified=1,
                    granted_credit=user.credit or 0,
                )
                return

            target_request.full_name = (user.full_name or "").strip()
            target_request.phone_number = user.phone_number
            target_request.status = VerificationRequest.RequestStatus.APPROVED
            target_request.granted_credit = user.credit or 0
            target_request.save()
            return

        approved_request = (
            VerificationRequest.objects
            .filter(user=user, status=VerificationRequest.RequestStatus.APPROVED)
            .order_by("-updated_at", "-pk")
            .first()
        )
        target_request = approved_request or latest_request
        if target_request is None:
            return

        target_request.full_name = (user.full_name or "").strip()
        target_request.phone_number = user.phone_number
        target_request.status = VerificationRequest.RequestStatus.REJECTED
        target_request.granted_credit = 0
        target_request.save()

    def save(self, commit=True):
        previous_is_verified = 0
        if self.instance and getattr(self.instance, "pk", None):
            previous_is_verified = int(
                CustomUser.objects
                .filter(pk=self.instance.pk)
                .values_list("is_verified", flat=True)
                .first()
                or 0
            )
        previous_email = ""
        if self.instance and getattr(self.instance, "pk", None):
            previous_email = (
                CustomUser.objects
                .filter(pk=self.instance.pk)
                .values_list("email", flat=True)
                .first()
                or ""
            )
        user = super().save(commit=False)
        normalized_full_name = " ".join((self.cleaned_data.get("full_name") or "").split())
        first_name, last_name = _split_full_name_parts(normalized_full_name)

        user.username = self.cleaned_data["phone_number"]
        user.first_name = first_name
        user.last_name = last_name
        user.full_name = normalized_full_name
        user.phone_number = self.cleaned_data["phone_number"]
        user.email = self.cleaned_data.get("email")
        if (previous_email or "").strip().lower() != (user.email or "").strip().lower():
            user.is_email_verified = False
        user.preferred_contact_methods = self.cleaned_data.get("preferred_contact_methods") or []
        user.telegram_id = self.cleaned_data.get("telegram_id")
        user.address_country = (self.cleaned_data.get("address_country") or "").strip() or None
        user.address_city = (self.cleaned_data.get("address_city") or "").strip() or None
        user.address_street = (self.cleaned_data.get("address_street") or "").strip() or None
        user.description = (self.cleaned_data.get("description") or "").strip() or None

        if (
            self.cleaned_data.get("clear_profile_picture")
            and not self.cleaned_data.get("profile_picture")
            and user.profile_picture
        ):
            user.profile_picture.delete(save=False)
            user.profile_picture = None

        password = self.cleaned_data.get("new_password") or ""
        if password:
            user.set_password(password)

        if commit:
            user.save()
            self._sync_user_verification_request(user, previous_is_verified)

        return user
