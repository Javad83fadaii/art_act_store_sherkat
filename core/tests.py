from django.test import TestCase
from django.urls import reverse


class SiteRulesAndSignupTermsTests(TestCase):
    """
    تست‌های جامع بخش قوانین و مقررات:
    ۱. بررسی صفحه اختصاصی قوانین و مقررات (/site_rules/)
    ۲. بررسی نمایش متن کامل قوانین و اجزای تعاملی اسکرول در صفحه ثبت‌نام (/accounts/signup/)
    """

    def test_site_rules_view_status_and_content(self):
        url = reverse('site_rules')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        content = response.content.decode('utf-8')
        # بررسی عنوان و هویت بصری
        self.assertIn("شرایط و قوانین شرکت در حراج آنلاین", content)
        self.assertIn("سند رسمی و چارچوب حقوقی", content)
        self.assertIn("بازگشت به فرم ثبت‌نام", content)

        # بررسی بندهای اصلی قوانین
        expected_clauses = [
            "مقدمه و شروط کلی مشارکت",
            "انتخاب و ارائه آثار هنری در حراج",
            "زمان پایان حراج و قاعده تمدید ۶ ساعته",
            "اسقاط کافه خیارات قانونی",
            "اهلیت متقاضیان و عدم محدودیت خرید",
            "نمایندگی حراج‌گزار و حدود اختیارات",
            "اصالت اثر",
            "پلکان قیمت",
            "نحوه پرداخت و ضمانت اجرای عدم پرداخت",
            "حق‌العمل",
            "محرمانگی",
            "سایر شرایط",
            "حل و فصل اختلافات",
            "قانون حاکم",
            "فورس‌ماژور",
        ]
        for clause in expected_clauses:
            with self.subTest(clause=clause):
                self.assertIn(clause, content)

    def test_signup_page_contains_full_rules_and_scroll_enforcement(self):
        url = reverse('signup')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        content = response.content.decode('utf-8')

        # بررسی المان‌های ساختاری کادر اسکرول و وضعیت
        self.assertIn('id="rules-section-container"', content)
        self.assertIn('id="rules-box-wrapper"', content)
        self.assertIn('id="rules-scroll-box"', content)
        self.assertIn('id="rules-scroll-progress"', content)
        self.assertIn('id="rules-status-bar"', content)
        self.assertIn('id="rules-status-text"', content)
        self.assertIn('id="rules-percent-badge"', content)
        self.assertIn('id="rules-read-badge"', content)
        self.assertIn('id="rules-agreement-wrapper"', content)
        self.assertIn('id="rules-bottom-sentinel"', content)

        # بررسی متن کامل قوانین داخل فرم ثبت‌نام
        self.assertIn("مقدمه و شروط کلی مشارکت", content)
        self.assertIn("زمان پایان حراج و قاعده تمدید ۶ ساعته", content)
        self.assertIn("اسقاط کافه خیارات قانونی", content)
        self.assertIn("پلکان افزایش قیمت", content)
        self.assertIn("نحوه پرداخت و ضمانت اجرای عدم پرداخت", content)
        self.assertIn("حل و فصل اختلافات و داوری", content)
        self.assertIn("پایان سند قوانین و مقررات حراج ماه", content)

        # بررسی منطق اسکریپتی اعتبارسنجی و اسکرول هوشمند
        self.assertIn("isRulesUnlocked", content)
        self.assertIn("unlockRulesAgreement", content)
        self.assertIn("checkRulesScrollState", content)
        self.assertIn("isScrollRequired", content)
        self.assertIn("validateAuctionRulesOnSubmit", content)
        self.assertIn("SCROLL_RULES_FIRST_MESSAGE", content)
        self.assertIn("لطفاً ابتدا متن قوانین را تا انتها اسکرول و مطالعه نمایید.", content)
        self.assertIn("برای ثبت‌نام، پذیرش قوانین و مقررات الزامی است.", content)
