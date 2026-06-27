from django.db import models
from django.conf import settings
from pathlib import Path
import uuid
import os
from django.utils import timezone  

class Artist(models.Model):
    id = models.IntegerField(primary_key=True)
    name = models.CharField(max_length=45, verbose_name='نام هنرمند')
    bio = models.TextField(blank=True, verbose_name='بیوگرافی', default="")

    class Meta:
        verbose_name = 'هنرمند'
        verbose_name_plural = 'هنرمندان'

    def __str__(self):
        return self.name

class ArtworkType(models.Model):
    name = models.CharField(max_length=100, verbose_name='نام نوع اثر هنری')
    description = models.TextField(blank=True, verbose_name='توضیحات', default="", null=True)

    class Meta:
        verbose_name = 'نوع اثر هنری'
        verbose_name_plural = 'انواع اثر هنری'

    def __str__(self):
        return self.name


class Subject(models.Model):
    name = models.CharField(max_length=100, verbose_name='نام موضوع')
    description = models.TextField(blank=True, verbose_name='توضیحات', default="", null=True)

    class Meta:
        db_table = 'store_subject'
        verbose_name = 'موضوع'
        verbose_name_plural = 'موضوعات'

    def __str__(self):
        return self.name


class Usage(models.Model):
    name = models.CharField(max_length=100, verbose_name='نام کاربرد')
    description = models.TextField(blank=True, verbose_name='توضیحات', default="", null=True)

    class Meta:
        db_table = 'store_usage'
        verbose_name = 'کاربرد'
        verbose_name_plural = 'کاربردها'

    def __str__(self):
        return self.name


class Material(models.Model):
    name = models.CharField(max_length=100, verbose_name='نام متریال')
    description = models.TextField(blank=True, verbose_name='توضیحات', default="", null=True)

    class Meta:
        db_table = 'store_material'
        verbose_name = 'متریال'
        verbose_name_plural = 'متریال‌ها'

    def __str__(self):
        return self.name

class Artwork(models.Model):
    class AuthenticityStatus(models.IntegerChoices):
        CONFIRMED = 0, 'اصالت تایید شده'
        NOT_CONFIRMED = 1, 'اصالت تایید نشده'

    product_id = models.CharField(max_length=5, unique=True, blank=True, editable=False)
    title = models.CharField(max_length=30, verbose_name='عنوان اثر')
    artist = models.ForeignKey(Artist, on_delete=models.CASCADE, related_name='artworks', verbose_name='هنرمند')
    authenticity_status = models.IntegerField(
        choices=AuthenticityStatus.choices,
        default=AuthenticityStatus.CONFIRMED,
        verbose_name='وضعیت اصالت'
    )
    artwork_type = models.ForeignKey(
        ArtworkType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='artworks',
        verbose_name='نوع اثر هنری'
    )
    subject = models.ForeignKey(
        Subject,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='artworks',
        verbose_name='موضوع'
    )
    usage = models.ForeignKey(
        Usage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='artworks',
        verbose_name='کاربرد'
    )
    material = models.ForeignKey(
        Material,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='artworks',
        verbose_name='متریال'
    )

    description = models.TextField(verbose_name='توضیحات')
    price = models.DecimalField(max_digits=12, decimal_places=0, verbose_name='قیمت')
    price_description = models.CharField(max_length=255, blank=True, null=True, verbose_name='توضیحات قیمت')
    
    class IsSoldStatus(models.IntegerChoices):
        AVAILABLE = 0, 'موجود'
        SOLD = 1, 'فروخته شده'
        RESERVED = 2, 'رزرو شده'

    is_sold = models.IntegerField(
        choices=IsSoldStatus.choices,
        default=IsSoldStatus.AVAILABLE,
        verbose_name='وضعیت فروش'
    )
    dimensions = models.CharField(max_length=255, null=True, blank=True, verbose_name='ابعاد')
    creation_year = models.IntegerField(null=True, blank=True, verbose_name='سال خلق')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاریخ ایجاد')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='تاریخ بروزرسانی')
    provenance = models.TextField(verbose_name='پیشینه', blank=True)

    class Meta:
        verbose_name = 'اثر هنری'
        verbose_name_plural = 'آثار هنری'

    def save(self, *args, **kwargs):
        if not self.product_id:
            last = Artwork.objects.exclude(product_id='').order_by('-product_id').values_list('product_id', flat=True).first()
            next_num = (int(last) + 1) if (last and str(last).isdigit()) else 1
            self.product_id = f'{next_num:05d}'
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.title

    @property
    def main_image_url(self):
        if not self.product_id:
            return f'{settings.STATIC_URL}images/no-image.jpg'

        try:
            if settings.STATICFILES_DIRS:
                static_root = Path(settings.STATICFILES_DIRS[0])
            else:
                static_root = Path(settings.BASE_DIR) / 'static'
        except AttributeError:
            static_root = Path(settings.BASE_DIR) / 'static'

        exts = ('.webp', '.png', '.jpg', '.jpeg')

        root_dir = static_root / 'images' / 'artwork'
        for ext in exts:
            candidate = root_dir / f'{self.product_id}{ext}'
            if candidate.exists() and candidate.is_file():
                return f'{settings.STATIC_URL}images/artwork/{self.product_id}{ext}'

        folder_dir = root_dir / self.product_id
        if folder_dir.exists() and folder_dir.is_dir():
            for ext in exts:
                candidate = folder_dir / f'{self.product_id}{ext}'
                if candidate.exists() and candidate.is_file():
                    return f'{settings.STATIC_URL}images/artwork/{self.product_id}/{candidate.name}'

            image_files = [
                file_path
                for file_path in folder_dir.iterdir()
                if file_path.is_file() and file_path.suffix.lower() in exts
            ]
            image_files.sort(key=lambda p: p.name.lower())
            if image_files:
                selected = image_files[0]
                return f'{settings.STATIC_URL}images/artwork/{self.product_id}/{selected.name}'

        return f'{settings.STATIC_URL}images/no-image.jpg'

    @property
    def gallery_images(self):
        if not self.product_id:
            return []
        try:
            if settings.STATICFILES_DIRS:
                static_root = Path(settings.STATICFILES_DIRS[0])
            else:
                static_root = Path(settings.BASE_DIR) / 'static'
        except AttributeError:
            return []
        relative_path = Path('images') / 'artwork' / self.product_id
        full_dir_path = static_root / relative_path
        images_urls = []
        if full_dir_path.exists() and full_dir_path.is_dir():
            for file_path in full_dir_path.iterdir():
                if file_path.is_file() and file_path.suffix.lower() in ['.jpg', '.jpeg', '.png', '.webp']:
                    url = f"{settings.STATIC_URL}images/artwork/{self.product_id}/{file_path.name}"
                    images_urls.append(url)
        images_urls.sort()
        return images_urls

    @property
    def video_url(self):
        if not self.product_id:
            return None
        try:
            if settings.STATICFILES_DIRS:
                static_root = Path(settings.STATICFILES_DIRS[0])
            else:
                static_root = Path(settings.BASE_DIR) / 'static'
        except AttributeError:
            return None
        relative_path = Path('images') / 'artwork' / self.product_id
        full_dir_path = static_root / relative_path
        if not (full_dir_path.exists() and full_dir_path.is_dir()):
            return None
        video_files = [
            file_path
            for file_path in full_dir_path.iterdir()
            if file_path.is_file() and file_path.suffix.lower() == '.mp4'
        ]
        if not video_files:
            return None
        video_files.sort(key=lambda p: p.name.lower())
        selected = video_files[0]
        return f"{settings.STATIC_URL}images/artwork/{self.product_id}/{selected.name}"

    @property
    def model_360_url(self):
        if not self.product_id:
            return None
        try:
            if settings.STATICFILES_DIRS:
                static_root = Path(settings.STATICFILES_DIRS[0])
            else:
                static_root = Path(settings.BASE_DIR) / 'static'
        except AttributeError:
            return None
        folder_relative_path = Path('images') / 'artwork' / self.product_id
        folder_full_path = static_root / folder_relative_path
        if folder_full_path.exists() and folder_full_path.is_dir():
            glb_files = [
                file_path
                for file_path in folder_full_path.iterdir()
                if file_path.is_file() and file_path.suffix.lower() == '.glb'
            ]
            if glb_files:
                glb_files.sort(key=lambda p: p.name.lower())
                selected = glb_files[0]
                return f"{settings.STATIC_URL}images/artwork/{self.product_id}/{selected.name}"
        root_glb = static_root / 'images' / 'artwork' / f'{self.product_id}.glb'
        if root_glb.exists() and root_glb.is_file():
            return f"{settings.STATIC_URL}images/artwork/{root_glb.name}"
        return None

class ProductLike(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='liked_products', verbose_name='کاربر')
    product = models.ForeignKey(Artwork, on_delete=models.CASCADE, related_name='likes', verbose_name='اثر هنری')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاریخ پسندیدن')

    class Meta:
        verbose_name = 'پسند'
        verbose_name_plural = 'پسندها'
        unique_together = ('user', 'product')

class VisitHistory(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='visit_history', verbose_name='کاربر')
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name='آدرس IP')
    product = models.ForeignKey(Artwork, on_delete=models.CASCADE, verbose_name='اثر هنری')
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name='زمان بازدید')

    class Meta:
        verbose_name = 'تاریخچه بازدید'
        verbose_name_plural = 'تاریخچه‌های بازدید'
        ordering = ['-timestamp']

    def __str__(self):
        if self.user:
            return f"{self.user} - {self.product.title}"
        return f"{self.ip_address} (مهمان) - {self.product.title}"

class TelegramPurchaseRequest(models.Model):
    STATUS_CHOICES = (
        ('pending', 'در انتظار تایید کاربر'),
        ('confirmed', 'تایید شده (نیاز به تماس)'),
        ('rejected', 'لغو شده توسط کاربر'),
        ('contacted', 'تماس گرفته شد'),
    )
    token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='telegram_requests', verbose_name='کاربر')
    artwork = models.ForeignKey(Artwork, on_delete=models.CASCADE, related_name='telegram_requests', verbose_name='اثر هنری')
    telegram_chat_id = models.CharField(max_length=50, blank=True, null=True, verbose_name='آیدی چت تلگرام')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name='وضعیت')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاریخ درخواست')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='زمان بروزرسانی')

    class Meta:
        verbose_name = 'درخواست خرید تلگرامی'
        verbose_name_plural = 'درخواست‌های خرید تلگرامی'

    def __str__(self):
        return f"{self.user} - {self.artwork.title}"

class PurchaseHistory(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='purchases', verbose_name='کاربر')
    artwork = models.ForeignKey(Artwork, on_delete=models.CASCADE, related_name='purchase_histories', verbose_name='اثر هنری')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='زمان خرید')
    
    class Meta:
        verbose_name = 'تاریخچه خرید'
        verbose_name_plural = 'تاریخچه خریدها'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user} "

class SiteVisitLog(models.Model):
    session_key = models.CharField(max_length=40, verbose_name="شناسه نشست (Session)")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="کاربر (در صورت لاگین)")
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="آدرس IP")
    
    start_time = models.DateTimeField(default=timezone.now, verbose_name="زمان ورود")
    last_activity = models.DateTimeField(default=timezone.now, verbose_name="آخرین فعالیت")
    is_closed = models.BooleanField(default=False, verbose_name="پایان یافته")
    
    @property
    def duration_in_minutes(self):
        delta = self.last_activity - self.start_time
        return int(delta.total_seconds() / 60)

    class Meta:
        verbose_name = "لاگ حضور در سایت"
        verbose_name_plural = "لاگ‌های حضور در سایت"
        ordering = ['-last_activity']

    def __str__(self):
        user_display = self.user.username if self.user else "کاربر ناشناس"
        return f"{user_display} ({self.ip_address}) - {self.duration_in_minutes} دقیقه"
