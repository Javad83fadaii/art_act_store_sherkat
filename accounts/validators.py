import re
from django.core.exceptions import ValidationError

INVALID_TEST_NAME_MESSAGE = (
    "نام وارد شده نامعتبر است. لطفاً از وارد کردن نام‌های تستی خودداری کرده و نام واقعی خود را وارد کنید."
)

_CHAR_MAP = str.maketrans({
    'ي': 'ی',
    'ك': 'ک',
    'ة': 'ه',
    'ئ': 'ی',
    'ؤ': 'و',
    'آ': 'ا',
    'أ': 'ا',
    'إ': 'ا',
    'ٱ': 'ا',
})

_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

# حذف اعراب و حرکات عربی و فارسی
_DIACRITICS_RE = re.compile(r'[\u064B-\u065F\u0670]')

# نویسه‌های نامرئی (نیم‌فاصله و ...)
_INVISIBLE_RE = re.compile(r'[\u200c\u200b\ufeff]')

# الگوهای رجکس برای تشخیص ریشه‌های تستی همراه با دور زدن کاراکتری:
# ۱. انگلیسی: test و مشتقات (testing, tester, teeeest, t-e-s-t, user_test, test1234 و ...)
_ENGLISH_TEST_RE = re.compile(r't+[\W_\d]*e+[\W_\d]*s+[\W_\d]*t+', re.IGNORECASE)

# ۲. فارسی: تست و مشتقات (تـــست، ت-س-ت، تتتتست، تست ۱، کاربر_تست، تستینگ، تستر و ...)
_PERSIAN_TEST_RE = re.compile(r'ت+[\W_\d\u0640]*س+[\W_\d\u0640]*ت+')

# ۳. فارسی: آزمایش و آزمایشی (آزمایشی، آزمایش، آزماااایشی، آ-ز-م-ا-ی-ش، کاربر آزمایشی و ...)
_PERSIAN_AZMAYESH_RE = re.compile(r'ا+[\W_\d]*ز+[\W_\d]*م+[\W_\d]*ا+[\W_\d]*ی+[\W_\d]*ش+')


def normalize_test_name(text: str) -> str:
    """
    نرمال‌سازی رشته برای مقایسه دقیق:
    - حذف فاصله‌های اضافه
    - کوچک‌سازی حروف انگلیسی
    - تبدیل ارقام فارسی و عربی به انگلیسی
    - حذف اعراب و حرکات (فتحه، ضمه، کسره، تنوین، تشدید)
    - یکسان‌سازی حروف مشابه عربی/فارسی (ی، ک، انواع الف)
    - حذف نویسه‌های نامرئی و نیم‌فاصله‌ها
    """
    if not text:
        return ""
    text = str(text).strip().lower()
    text = text.translate(_DIGIT_MAP)
    text = _DIACRITICS_RE.sub('', text)
    text = text.translate(_CHAR_MAP)
    text = _INVISIBLE_RE.sub('', text)
    return text


def is_test_name(name: str) -> bool:
    """
    بررسی اینکه آیا نام داده‌شده شامل عبارات یا الگوهای آزمایشی است یا خیر.
    این تابع الگوهای فارسی و انگلیسی، تکرار کاراکتر، تطویل (کشیدگی حروف)،
    علائم نگارشی و ترکیبات مشتق را پوشش می‌دهد.
    """
    if not name:
        return False

    normalized = normalize_test_name(name)
    if not normalized:
        return False

    # ۱. بررسی با الگوهای انعطاف‌پذیر رجکس
    if _ENGLISH_TEST_RE.search(normalized):
        return True

    if _PERSIAN_TEST_RE.search(normalized):
        return True

    if _PERSIAN_AZMAYESH_RE.search(normalized):
        return True

    # ۲. بررسی بدون کاراکترهای جداکننده (مانند t.e.s.t یا ت.س.ت)
    clean_chars = re.sub(r'[\W_\d\u0640]+', '', normalized)
    if clean_chars:
        # فشرده‌سازی کاراکترهای متوالی تکراری (مانند teeeest -> test یا تتتتسسستتت -> تست)
        compressed = re.sub(r'(.)\1+', r'\1', clean_chars)
        if 'test' in clean_chars or 'test' in compressed:
            return True
        if 'تست' in clean_chars or 'تست' in compressed:
            return True
        if 'ازمایش' in clean_chars or 'ازمایش' in compressed:
            return True

    return False


def validate_not_test_name(value: str) -> None:
    """
    اعتبارسنج جنگو برای جلوگیری از وارد کردن نام‌های آزمایشی.
    در صورت عدم اعتبار، خطای ValidationError با پیام استاندارد پرتاب می‌شود.
    """
    if is_test_name(value):
        raise ValidationError(INVALID_TEST_NAME_MESSAGE)
