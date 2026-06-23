from __future__ import annotations

from copy import deepcopy


NOTIFICATION_MESSAGES = {
    "common": {
        "invalid_request": "درخواست نامعتبر است.",
        "request_submit_error": "خطا در ثبت درخواست",
        "server_communication_error": "خطا در ارتباط با سرور.",
        "server_retry_error": "خطا در ارتباط با سرور. لطفاً مجدداً تلاش کنید.",
    },
    "accounts": {
        "profile": {
            "current_password_required": "برای تغییر رمز عبور، وارد کردن رمز عبور فعلی الزامی است.",
            "current_password_incorrect": "رمز عبور فعلی اشتباه است.",
            "new_password_mismatch": "رمز عبور جدید و تکرار آن با هم مطابقت ندارند.",
            "new_password_min_length": "رمز عبور جدید باید حداقل ۸ کاراکتر باشد.",
            "password_changed": "رمز عبور شما با موفقیت تغییر یافت.",
            "updated": "اطلاعات پروفایل با موفقیت بروزرسانی شد.",
        },
        "signup": {
            "success": "خوش آمدید! ثبت‌نام شما با موفقیت انجام شد.",
            "required_email": "لطفا آدرس ایمیل را کامل کنید",
            "invalid_email": "لطفا یک آدرس ایمیل معتبر وارد کنید",
            "required_full_name": "وارد کردن نام و نام خانوادگی الزامی است.",
            "required_auction_rules": "برای ثبت‌نام، پذیرش قوانین و مقررات الزامی است.",
            "password_min_length": "رمز عبور باید حداقل ۸ کاراکتر باشد.",
            "password_pattern": "رمز عبور باید حداقل ۸ کاراکتر و شامل حرف بزرگ، حرف کوچک و کاراکتر ویژه باشد.",
            "password_mismatch": "رمز عبور و تکرار آن یکسان نیستند.",
        },
        "credit_increase": {
            "pending_exists": "درخواست اعتبار شما قبلاً ثبت شده و در انتظار بررسی است.",
            "created": "درخواست بررسی اعتبار شما با موفقیت ثبت شد.",
        },
        "auction_verification": {
            "already_verified": "حساب کاربری شما قبلاً تایید شده است.",
            "full_name_required": "برای ثبت درخواست مزایده، ابتدا نام و نام خانوادگی را تکمیل کنید.",
            "pending_exists": "درخواست شما قبلاً ثبت شده و در انتظار تایید مدیران است.",
            "created": "درخواست شما برای شرکت در مزایده ثبت شد. پس از تایید مدیران می‌توانید در مزایده شرکت کنید.",
        },
    },
    "admin": {
        "settings": {
            "notifications_load_error": "دریافت تنظیمات اعلان‌ها با خطا مواجه شد",
            "notifications_saved": "تنظیمات اعلان‌ها با موفقیت ذخیره شد",
            "notifications_save_error": "ذخیره اعلان‌ها انجام نشد",
            "filter_name_required": "نام فیلتر را وارد کنید",
            "filter_invalid_json": "فرمت JSON معتبر نیست",
            "filter_saved": "فیلتر با موفقیت ذخیره شد",
            "filter_save_error": "ذخیره فیلتر انجام نشد. نام فیلتر را یکتا انتخاب کنید",
            "filter_default_saved": "فیلتر پیش‌فرض تنظیم شد",
            "filter_default_save_error": "تعیین فیلتر پیش‌فرض انجام نشد",
            "filter_deleted": "فیلتر با موفقیت حذف شد",
            "filter_delete_error": "حذف فیلتر انجام نشد",
        },
        "saved_filters": {
            "name_page_required": "نام و صفحه الزامی است",
            "at_least_one_filter": "حداقل یک فیلتر باید انتخاب شود",
            "created": "فیلتر \"{name}\" با موفقیت ذخیره شد",
            "deleted": "فیلتر \"{name}\" حذف شد",
            "set_default": "فیلتر \"{name}\" به عنوان پیش‌فرض تنظیم شد",
            "invalid_page": "صفحه نامعتبر",
        },
        "product_create": {
            "title_required": "لطفا حداقل عنوان محصول را وارد کنید.",
            "store_create_error": "خطا در ایجاد محصول.",
            "store_created": "محصول با موفقیت ساخته شد. برای ویرایش وارد شوید: {url}",
            "auction_create_error": "خطا در ایجاد مزایده.",
            "auction_created_partial": "مزایده ساخته شد (شناسه: {auction_id}). اما برخی محصولات خطا داشتند: {errors}. لینک ویرایش مزایده: {url}",
            "auction_created": "مزایده و محصولات با موفقیت ساخته شد. لینک ویرایش مزایده: {url}",
            "auction_product_build_error": "خطا در ساخت محصول: {title}",
            "auction_product_create_error": "خطا در ایجاد محصول مزایده.",
            "auction_product_created": "محصول مزایده با موفقیت ساخته شد. شناسه: {id}",
        },
        "requests": {
            "invalid_positive_amount": "لطفاً یک مبلغ صحیح و بیشتر از صفر وارد کنید.",
            "error_prefix": "خطا: {error}",
            "operation_error": "خطا در عملیات: {error}",
            "unknown_reason": "دلیل نامشخص",
            "load_error": "خطا در ارتباط با سرور.",
        },
        "reports": {
            "resolve_error": "رفع خطا با مشکل مواجه شد.",
            "load_error": "دریافت اطلاعات این بخش با خطا مواجه شد.",
        },
    },
    "auction": {
        "inactive": "مزایده فعال نیست.",
        "detail_login_required": "برای مشاهده جزئیات مزایده لطفاً وارد شوید.",
        "list_detail_login_required": "برای مشاهده جزئیات محصول مزایده، لطفاً ابتدا وارد حساب کاربری خود شوید.",
        "list_bid_login_required": "برای ثبت پیشنهاد در مزایده، لطفاً ابتدا وارد حساب کاربری خود شوید.",
        "enable_participation": "برای شرکت در مزایده، گزینه «شرکت در مزایده» را فعال کنید.",
        "pending_approval": "درخواست شما ثبت شده و در انتظار تایید مدیران است.",
        "bid_success_ajax": "پیشنهاد شما با موفقیت ثبت شد.",
        "bid_success_redirect": "بید شما با موفقیت ثبت شد.",
        "generic_error": "خطایی رخ داده است.",
        "credit_request_pending": "درخواست افزایش اعتبار شما در انتظار تایید است.",
        "credit_request_needed": "اعتبار شما کافی نیست. برای افزایش سقف پیشنهادات باید درخواست افزایش اعتبار ثبت کنید.",
        "credit_request_pending_exists": "درخواست افزایش اعتبار شما قبلاً ثبت شده و در انتظار بررسی است.",
        "credit_request_created": "درخواست شما ثبت شده پس از تایید مدیران اعتبارتان زیاد می‌شود.",
    },
    "store": {
        "reserve": {
            "login_required": "ابتدا وارد حساب کاربری خود شوید",
            "already_reserved_or_sold": "این اثر قبلاً رزرو یا فروخته شده است.",
            "not_found": "اثر مورد نظر یافت نشد.",
            "success": "درخواست شما با موفقیت ثبت شد. همکاران ما به زودی با شما تماس خواهند گرفت.",
        },
        "like": {
            "login_required": "برای افزودن اثر به علاقه مندی ها، لطفاً ابتدا وارد حساب کاربری خود شوید.",
        },
    },
}


def get_notification(key: str, **params) -> str:
    current = NOTIFICATION_MESSAGES
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(f"Unknown notification key: {key}")
        current = current[part]

    if not isinstance(current, str):
        raise KeyError(f"Notification key does not resolve to text: {key}")

    return current.format(**params) if params else current


def get_notification_catalog() -> dict:
    return deepcopy(NOTIFICATION_MESSAGES)
