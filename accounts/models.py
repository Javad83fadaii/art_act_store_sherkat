from decimal import Decimal

from django.apps import apps
from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.conf import settings
from django.utils import timezone
import uuid
import re

class CustomUserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, phone_number, password, **extra_fields):
        if not phone_number:
            raise ValueError("phone_number must be set")
            
        # بررسی و اجباری بودن نام و نام خانوادگی (full_name)
        full_name = extra_fields.get("full_name")
        if not full_name or not str(full_name).strip():
            raise ValueError("full_name must be set")

        phone_number = str(phone_number).strip()

        # رفع مشکل ایمیل خالی در زمان ساخت یوزر
        email = extra_fields.get("email")
        if email:
            extra_fields["email"] = self.normalize_email(email)
        else:
            extra_fields["email"] = None

        username = extra_fields.get("username")
        if not username:
            username = re.sub(r"[^0-9A-Za-z@.+-_]", "", phone_number)
            extra_fields["username"] = username or uuid.uuid4().hex

        extra_fields.setdefault("phone_number", phone_number)

        user = self.model(**extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, phone_number, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(phone_number, password, **extra_fields)

    def create_superuser(self, phone_number, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(phone_number, password, **extra_fields)


class CustomUser(AbstractUser):
    # حذف کامل فیلدهای پیش‌فرض نام و نام خانوادگی از AbstractUser
    first_name = None
    last_name = None

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone_number = models.CharField(max_length=20, unique=True)
    
    # فیلد نام کامل (اجباری)
    full_name = models.CharField(max_length=150)
    
    preferred_contact_methods = models.JSONField(default=list, blank=True)
    telegram_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    email = models.EmailField(unique=True, null=True, blank=True)
    address_country = models.CharField(max_length=255, blank=True, null=True)
    address_city = models.CharField(max_length=255, blank=True, null=True)
    address_street = models.CharField(max_length=255, blank=True, null=True)
    profile_picture = models.ImageField(upload_to='profile_pictures/', null=True, blank=True)
    description = models.TextField(blank=True, null=True)
    is_verified = models.IntegerField(default=0)
    
    # اعتبار کل تخصیص‌یافته به کاربر
    credit = models.DecimalField(max_digits=15, decimal_places=0, default=0)
    # اعتبار قابل استفاده فعلی برای ثبت بید
    current_credit = models.DecimalField(max_digits=15, decimal_places=0, default=0)
    newsletter_catalog_opt_in = models.BooleanField(
        default=False,
        verbose_name="تمایل به دریافت خبرنامه و کاتالوگ",
    )

    objects = CustomUserManager()

    USERNAME_FIELD = 'phone_number'
    # اضافه شدن full_name به فیلدهای الزامی برای دستور createsuperuser
    REQUIRED_FIELDS = ['full_name']

    def __str__(self):
        name = str(self.full_name).strip() if self.full_name else ""
        return name or self.phone_number

    def get_full_name(self):
        return str(self.full_name).strip() if self.full_name else ""

    def get_short_name(self):
        return str(self.full_name).strip() if self.full_name else self.phone_number

    @property
    def has_pending_auction_request(self):
        return self.verification_requests.filter(
            status=VerificationRequest.RequestStatus.PENDING
        ).exists()

    def get_reserved_auction_credit(self):
        if not self.pk or int(self.is_verified or 0) != 1:
            return Decimal("0")

        AuctionCartItem = apps.get_model('auction', 'AuctionCartItem')
        now = timezone.now()
        reserved_total = (
            AuctionCartItem.objects
            .filter(
                user_id=self.pk,
                is_active=True,
                auction__start_date__lte=now,
                auction__end_date__gte=now,
            )
            .aggregate(total=models.Sum('reserved_amount'))
            .get('total')
        )
        return Decimal(str(reserved_total or 0))

    def calculate_current_credit(self):
        if int(self.is_verified or 0) != 1:
            return Decimal("0")

        total_credit = Decimal(str(self.credit or 0))
        reserved_credit = self.get_reserved_auction_credit()
        return max(total_credit - reserved_credit, Decimal("0"))

    def refresh_current_credit(self, persist=True):
        new_current_credit = self.calculate_current_credit()
        self.current_credit = new_current_credit

        if persist and self.pk:
            type(self).objects.filter(pk=self.pk).update(current_credit=new_current_credit)

        return new_current_credit

    def clean(self):
        super().clean()
        
        # تبدیل رشته خالی به None برای جلوگیری از خطای Unique Constraint
        if not self.email:
            self.email = None
        if not self.telegram_id:
            self.telegram_id = None

        # تبدیل مقادیر به int برای جلوگیری از باگ‌های String vs Integer
        current_is_verified = int(self.is_verified or 0)
        total_credit = int(self.credit or 0)
        available_credit = int(self.current_credit or 0)
        
        if current_is_verified == 0 and (total_credit > 0 or available_credit > 0):
            raise ValidationError({
                'credit': 'کاربری که وضعیت وریفای آن 0 است، نمی‌تواند اعتباری داشته باشد.',
                'current_credit': 'کاربری که وضعیت وریفای آن 0 است، نمی‌تواند اعتبار فعلی داشته باشد.',
            })
        if available_credit > total_credit:
            raise ValidationError({
                'current_credit': 'اعتبار فعلی نمی‌تواند از اعتبار کل بیشتر باشد.'
            })

    def save(self, *args, **kwargs):
        refresh_current_credit = kwargs.pop('refresh_current_credit', True)
        # اطمینان از تبدیل رشته خالی به None در زمان ذخیره‌سازی
        if not self.email:
            self.email = None
        if not self.telegram_id:
            self.telegram_id = None

        if int(self.is_verified or 0) == 0:
            self.credit = 0
            self.current_credit = 0
            
        super().save(*args, **kwargs)

        if refresh_current_credit and self.pk:
            self.refresh_current_credit(persist=True)


class VerificationRequest(models.Model):
    class RequestStatus(models.IntegerChoices):
        PENDING = 0, 'در انتظار بررسی'
        APPROVED = 1, 'تایید شده'
        REJECTED = 2, 'رد شده'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="verification_requests",
    )
    full_name = models.CharField(max_length=150)
    phone_number = models.CharField(max_length=20)
    status = models.IntegerField(
        choices=RequestStatus.choices,
        default=RequestStatus.PENDING,
        verbose_name="وضعیت درخواست",
    )
    is_verified = models.IntegerField(default=0)
    
    # فیلد جدید برای تنظیم اعتبار
    granted_credit = models.DecimalField(max_digits=15, decimal_places=0, default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        status_label = dict(self.RequestStatus.choices).get(self.status, "نامشخص")
        return f"{self.full_name} - {self.phone_number} - {status_label}"

    def clean(self):
        super().clean()
        current_status = int(self.status or self.RequestStatus.PENDING)
        current_is_verified = 1 if current_status == self.RequestStatus.APPROVED else 0
        current_granted_credit = int(self.granted_credit or 0)
        
        if current_is_verified == 0 and current_granted_credit > 0:
            raise ValidationError({
                'granted_credit': 'تا زمانی که وضعیت وریفای 1 نباشد، نمی‌توانید اعتباری تخصیص دهید.'
            })

    def save(self, *args, **kwargs):
        previous_status = None
        if self.pk:
            previous_status = (
                VerificationRequest.objects
                .filter(pk=self.pk)
                .values_list('status', flat=True)
                .first()
            )
        current_status = int(self.status or self.RequestStatus.PENDING)
        current_is_verified = 1 if current_status == self.RequestStatus.APPROVED else 0
        self.is_verified = current_is_verified
        
        # اطمینان از صفر بودن اعتبار در صورت عدم تایید
        if current_is_verified == 0:
            self.granted_credit = 0
            
        super().save(*args, **kwargs)
        
        # گرفتن آبجکت یوزر به صورت مستقیم از دیتابیس برای جلوگیری از خطای Caching 
        user_obj = CustomUser.objects.get(id=self.user_id)
        user_updated = False
        
        # بررسی تغییر در وضعیت وریفای کاربر
        if int(user_obj.is_verified or 0) != current_is_verified:
            user_obj.is_verified = current_is_verified
            user_updated = True
            
        # فقط در اولین تایید، اعتبار اولیه را روی کاربر ست می‌کنیم تا
        # ذخیره‌های بعدی درخواست، اعتبار فعلی مصرف‌شده کاربر را بازنویسی نکند.
        if current_is_verified == 1 and previous_status != self.RequestStatus.APPROVED:
            user_obj.credit = self.granted_credit
            user_updated = True
            
        # در صورت نیاز به آپدیت، یوزر را ذخیره می‌کنیم
        if user_updated:
            user_obj.save()


class CreditIncreaseRequest(models.Model):
    class RequestStatus(models.IntegerChoices):
        PENDING = 0, 'در انتظار بررسی'
        APPROVED = 1, 'تایید شده'
        REJECTED = 2, 'رد شده'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name="credit_updates"
    )
    current_credit = models.DecimalField(
        max_digits=15, 
        decimal_places=0, 
        verbose_name="اعتبار درخواستی/تخصیص یافته"
    )
    
    # فیلد جدید وضعیت درخواست
    status = models.IntegerField(
        choices=RequestStatus.choices,
        default=RequestStatus.PENDING,
        verbose_name="وضعیت درخواست"
    )

    previous_current_credit = models.DecimalField(
        max_digits=15,
        decimal_places=0,
        default=0,
        editable=False,
    )
    previous_total_credit = models.DecimalField(
        max_digits=15,
        decimal_places=0,
        default=0,
        editable=False,
    )
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ایجاد")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاریخ آخرین بروزرسانی")

    class Meta:
        verbose_name = "Credit Update Log"
        verbose_name_plural = "Credit Update Logs"
        ordering = ["-created_at"]

    def __str__(self):
        status_label = dict(self.RequestStatus.choices).get(self.status, "نامشخص")
        return f"Credit Request #{self.pk} - User: {self.user.id} - Credit: {self.current_credit} - Status: {status_label}"

    def clean(self):
        super().clean()
        
        # ۱. بررسی تغییرات اعتبار پس از تایید یا رد
        if self.pk is not None:
            old_instance = CreditIncreaseRequest.objects.get(pk=self.pk)
            if old_instance.status in [self.RequestStatus.APPROVED, self.RequestStatus.REJECTED]:
                if old_instance.current_credit != self.current_credit:
                    raise ValidationError({
                        'current_credit': 'این درخواست قبلاً تایید یا رد شده است. تغییر مبلغ تنها در وضعیت "در انتظار بررسی" امکان‌پذیر است.'
                    })

        # ۲. اگر وضعیت درخواست 1 (تایید شده) باشد، باید چک کنیم که کاربر وریفای شده است یا خیر
        if self.status == self.RequestStatus.APPROVED:
            if int(self.user.is_verified or 0) == 0:
                raise ValidationError({
                    'status': 'نمی‌توانید درخواست افزایش اعتبار را برای کاربری که وریفای نشده (وضعیت 0) تایید کنید.'
                })

    def save(self, *args, **kwargs):
        previous_status = None
        is_create = self.pk is None
        if self.pk:
            previous_status = (
                CreditIncreaseRequest.objects
                .filter(pk=self.pk)
                .values_list('status', flat=True)
                .first()
            )

        if is_create and self.user_id:
            snapshot = (
                CustomUser.objects
                .filter(id=self.user_id)
                .values('credit', 'current_credit')
                .first()
            ) or {}
            self.previous_total_credit = Decimal(str(snapshot.get('credit') or 0))
            self.previous_current_credit = Decimal(str(snapshot.get('current_credit') or 0))

        # فراخوانی متد clean برای اطمینان از اجرای اعتبارسنجی‌ها هنگام ذخیره از طریق کد
        self.clean()
        
        super().save(*args, **kwargs)
        
        # فقط هنگام تغییر وضعیت به تایید، مبلغ تاییدشده را به اعتبار کل کاربر اضافه می‌کنیم
        # و سپس اعتبار فعلی را بر اساس مبالغ رزرو شده در سبد مزایده محاسبه می‌کنیم.
        if self.status == self.RequestStatus.APPROVED and previous_status != self.RequestStatus.APPROVED:
            from django.db import transaction

            with transaction.atomic():
                user_obj = CustomUser.objects.select_for_update().get(id=self.user_id)
                amount = Decimal(str(self.current_credit or 0))
                user_obj.credit = Decimal(str(user_obj.credit or 0)) + amount
                user_obj.save(refresh_current_credit=True)
