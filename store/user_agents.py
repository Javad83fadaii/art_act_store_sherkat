import re


WINDOWS_VERSION_MAP = {
    "10.0": "10/11",
    "6.3": "8.1",
    "6.2": "8",
    "6.1": "7",
    "6.0": "Vista",
    "5.2": "XP x64",
    "5.1": "XP",
    "5.0": "2000",
}

# هدری که به مرورگر می‌گوید نسخه دقیق سیستم‌عامل را بفرستد.
# بدون این هدر، کروم نسخه را فریز می‌کند:
#   اندروید همیشه «Android 10; K» و ویندوز همیشه «NT 10.0» گزارش می‌شود.
ACCEPT_CH_HEADER = (
    "Sec-CH-UA, Sec-CH-UA-Mobile, Sec-CH-UA-Platform, "
    "Sec-CH-UA-Platform-Version, Sec-CH-UA-Arch, Sec-CH-UA-Bitness, "
    "Sec-CH-UA-Model, Sec-CH-UA-Full-Version"
)


def _normalize_version(value: str) -> str:
    return str(value or "").strip().replace("_", ".")


def _clean_hint_value(value) -> str:
    """مقادیر Client Hints معمولاً داخل کوتیشن هستند: '"Windows"' یا '"13.0.0"'."""
    text = str(value or "").strip()
    if not text:
        return ""
    # بعضی مرورگرها چند مقدار می‌فرستند؛ فقط توکن معنادار را نگه می‌داریم
    if text.startswith("?"):
        return ""
    # حذف کوتیشن‌های دور مقدار
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1].strip()
    # حذف کوتیشن‌های تکی احتمالی
    text = text.strip().strip('"').strip("'").strip()
    # مقادیر خالی Chromium مثل "?0" یا "Unknown"
    if text in ("?0", "?1", "Unknown", "unknown"):
        return ""
    return text


def _shorten_version(version: str) -> str:
    """'13.0.0' -> '13' ، '13.1.0' -> '13.1' تا نمایش تمیز و دقیق باشد."""
    text = _normalize_version(version).strip(" .")
    if not text:
        return ""
    parts = [p for p in re.split(r"[.\-]", text) if p != ""]
    if not parts:
        return ""
    # حذف صفرهای انتهایی (13.0.0 -> 13)
    while len(parts) > 1 and parts[-1] == "0":
        parts.pop()
    return ".".join(parts)


def _major_version(version: str) -> int:
    text = _shorten_version(version)
    if not text:
        return 0
    try:
        return int(str(text).split(".")[0])
    except (ValueError, IndexError):
        return 0


def _normalize_hint_platform(platform: str) -> str:
    text = _clean_hint_value(platform).lower()
    # یکدست‌سازی نام‌ها
    aliases = {
        "macos": "macos",
        "mac os": "macos",
        "macintosh": "macos",
        "chromeos": "chromeos",
        "chrome os": "chromeos",
        "cros": "chromeos",
    }
    return aliases.get(text, text)


def is_ambiguous_operating_system(value: str) -> bool:
    """آیا این مقدار فریز/مبهم است و نباید جایگزین مقدار دقیق شود؟

    - «Android 10»: کروم جدید نسخه اندروید را همیشه 10 گزارش می‌کند،
      پس این مقدار ممکن است فریز شده باشد (اندروید 11/12/13/14 واقعی).
    - «Windows 10/11 (NT 10.0)»: هم برای ویندوز ۱۰ هم ۱۱ همین گزارش می‌آید.
    """
    text = str(value or "").strip()
    if not text:
        return True
    if text == "Android 10":
        return True
    if text.startswith("Windows 10/11"):
        return True
    return False


def should_replace_operating_system(old: str, new: str) -> bool:
    """تصمیم می‌گیرد مقدار ذخیره‌شده با مقدار تازه‌تشخیص جایگزین شود یا نه.

    قانون اصلی: هرگز یک مقدار دقیق (مثل «Android 13» یا «Windows 11»)
    را با یک مقدار فریز/مبهم (مثل «Android 10» یا «Windows 10/11»)
    برنگردان. این اتفاق وقتی می‌افتد که یک درخواست بدون Client Hints
    بعد از درخواستی که نسخه دقیق را آورده برسد.
    """
    new_clean = str(new or "").strip()
    if not new_clean:
        return False
    old_clean = str(old or "").strip()
    if not old_clean:
        return True
    if old_clean == new_clean:
        return False
    if is_ambiguous_operating_system(new_clean) and not is_ambiguous_operating_system(old_clean):
        return False
    return True


def _extract_hints(client_hints=None, platform=None, platform_version=None, model=None) -> dict:
    """پشتیبانی از چند شکل ورودی تا استفاده در middleware/view/تست ساده باشد."""
    hints = {}
    if isinstance(client_hints, dict):
        # کلیدها ممکن است به شکل‌های مختلف باشند (META، هدر، کوکی، JS)
        for key, value in client_hints.items():
            hints[str(key).lower()] = value

    def _pick(*names):
        for name in names:
            nl = name.lower()
            if nl in hints and hints[nl] not in (None, ""):
                cleaned = _clean_hint_value(hints[nl])
                if cleaned:
                    return cleaned
        return ""

    if platform is None:
        platform = _pick(
            "platform",
            "sec-ch-ua-platform",
            "http_sec_ch_ua_platform",
            "ch_platform",
            "x-client-platform",
            "http_x_client_platform",
        )
    if platform_version is None:
        platform_version = _pick(
            "platformversion",
            "platform_version",
            "sec-ch-ua-platform-version",
            "http_sec_ch_ua_platform_version",
            "ch_platform_version",
            "x-client-platform-version",
            "http_x_client_platform_version",
            "x-platform-version",
        )
    if model is None:
        model = _pick(
            "model",
            "sec-ch-ua-model",
            "http_sec_ch_ua_model",
            "ch_model",
        )

    return {
        "platform": _clean_hint_value(platform),
        "platform_version": _clean_hint_value(platform_version),
        "model": _clean_hint_value(model),
    }


def extract_client_hints_from_meta(meta: dict) -> dict:
    """خواندن Client Hints از request.META (هدرها + کوکی‌های JS)."""
    meta = meta or {}
    cookies = {}

    def _parse_cookies(raw: str):
        result = {}
        for chunk in str(raw or "").split(";"):
            if "=" not in chunk:
                continue
            k, v = chunk.split("=", 1)
            result[k.strip()] = v.strip().strip('"')
        return result

    raw_cookie = meta.get("HTTP_COOKIE", "") or meta.get("COOKIES", "")
    if isinstance(raw_cookie, dict):
        cookies = {str(k).strip(): str(v).strip() for k, v in raw_cookie.items()}
    elif raw_cookie:
        cookies = _parse_cookies(raw_cookie)

    def _get(*names):
        for name in names:
            if name in meta and meta[name] not in (None, ""):
                cleaned = _clean_hint_value(meta[name])
                if cleaned:
                    return cleaned
        return ""

    platform = _get(
        "HTTP_SEC_CH_UA_PLATFORM",
        "HTTP_X_CLIENT_PLATFORM",
        "HTTP_X_PLATFORM",
    ) or _clean_hint_value(cookies.get("ch_platform", ""))

    platform_version = _get(
        "HTTP_SEC_CH_UA_PLATFORM_VERSION",
        "HTTP_X_CLIENT_PLATFORM_VERSION",
        "HTTP_X_PLATFORM_VERSION",
    ) or _clean_hint_value(cookies.get("ch_platform_version", ""))

    model = _get("HTTP_SEC_CH_UA_MODEL") or _clean_hint_value(cookies.get("ch_model", ""))

    return {
        "platform": platform,
        "platform_version": platform_version,
        "model": model,
    }


def detect_operating_system_from_request(request) -> str:
    """تشخیص دقیق با ترکیب User-Agent و Client Hints."""
    meta = getattr(request, "META", {}) or {}
    user_agent = meta.get("HTTP_USER_AGENT", "")
    hints = extract_client_hints_from_meta(meta)
    return detect_operating_system(user_agent, hints)


def _windows_from_hints(platform_version: str) -> str:
    """تفکیک ویندوز ۱۰ و ۱۱ با Sec-CH-UA-Platform-Version.

    طبق مستندات Chromium:
        platformVersion با major >= 13 یعنی ویندوز ۱۱
        (13=21H2، 14=22H2، 15=23H2 به بعد)
    """
    short = _shorten_version(platform_version)
    major = _major_version(short)
    if major >= 13:
        return "Windows 11"
    if major > 0:
        return "Windows 10"
    return ""


def _android_from_hints(platform_version: str, fallback_version: str = "") -> str:
    short = _shorten_version(platform_version) or _shorten_version(fallback_version)
    return f"Android {short}".strip() if short else "Android"


def detect_operating_system(user_agent: str, client_hints=None, platform=None, platform_version=None, model=None) -> str:
    ua = str(user_agent or "").strip()
    hints = _extract_hints(client_hints, platform=platform, platform_version=platform_version, model=model)
    hint_platform_raw = hints.get("platform", "")
    hint_platform = _normalize_hint_platform(hint_platform_raw)
    hint_version_raw = hints.get("platform_version", "")
    hint_version = _normalize_version(_clean_hint_value(hint_version_raw))

    lower_ua = ua.lower()

    # ————— ۱. اگر Client Hint معتبر داریم، اول به آن اعتماد می‌کنیم —————
    if hint_platform == "windows":
        refined = _windows_from_hints(hint_version) if hint_version else ""
        if refined:
            return refined
        # platform ویندوز است ولی نسخه نفرستاده؛ ادامه با UA
    elif hint_platform == "android":
        ua_match = re.search(r"Android[ /]([0-9][0-9._]*)", ua, re.IGNORECASE)
        ua_version = _normalize_version(ua_match.group(1)) if ua_match else ""
        # نسخه hint دقیق است (مشکل Android 10 فریز شده را حل می‌کند)
        if hint_version:
            return _android_from_hints(hint_version)
        if ua_version:
            return f"Android {_shorten_version(ua_version)}".strip()
        return "Android"
    elif hint_platform in ("macos",):
        if hint_version:
            return f"macOS {_shorten_version(hint_version)}".strip()
    elif hint_platform in ("ios",):
        if hint_version:
            return f"iOS {_shorten_version(hint_version)}".strip()
    elif hint_platform in ("chromeos",):
        if hint_version:
            return f"ChromeOS {_shorten_version(hint_version)}".strip()
        return "ChromeOS"
    elif hint_platform in ("linux", "ubuntu", "fedora", "debian"):
        if hint_platform == "linux":
            if hint_version:
                return f"Linux {_shorten_version(hint_version)}".strip()
        else:
            label = hint_platform_raw.strip().strip('"')
            if hint_version:
                return f"{label} {_shorten_version(hint_version)}".strip()
            return label

    if not ua:
        # بدون UA فقط hint را برگردان
        if hint_platform_raw and hint_version:
            return f"{hint_platform_raw} {_shorten_version(hint_version)}".strip()
        return hint_platform_raw or ""

    if "windows phone" in lower_ua:
        match = re.search(r"Windows Phone(?: OS)? ([0-9._]+)", ua, re.IGNORECASE)
        version = _normalize_version(match.group(1)) if match else ""
        # ویندوزفون قدیمی است و Client Hint ندارد؛ همان UA کافی است
        return f"Windows Phone {_shorten_version(version)}".strip() if version else "Windows Phone"

    if "cros" in lower_ua:
        match = re.search(r"CrOS [^ ]+ ([0-9.]+)", ua, re.IGNORECASE)
        version = _normalize_version(match.group(1)) if match else ""
        if hint_platform == "chromeos" and hint_version:
            return f"ChromeOS {_shorten_version(hint_version)}".strip()
        return f"ChromeOS {_shorten_version(version)}".strip() if version else "ChromeOS"

    if "iphone" in lower_ua or "ipod" in lower_ua:
        match = re.search(r"OS ([0-9_]+) like Mac OS X", ua, re.IGNORECASE)
        version = _normalize_version(match.group(1)) if match else ""
        return f"iOS {_shorten_version(version)}".strip() if version else "iOS"

    if "ipad" in lower_ua:
        match = re.search(r"OS ([0-9_]+) like Mac OS X", ua, re.IGNORECASE)
        version = _normalize_version(match.group(1)) if match else ""
        return f"iPadOS {_shorten_version(version)}".strip() if version else "iPadOS"

    if "android" in lower_ua:
        harmony_match = re.search(r"(?:HarmonyOS|OpenHarmony)[ /]([0-9._]+)", ua, re.IGNORECASE)
        if harmony_match:
            version = _normalize_version(harmony_match.group(1))
            return f"HarmonyOS {_shorten_version(version)}".strip()

        match = re.search(r"Android[ /]([0-9][0-9._]*)", ua, re.IGNORECASE)
        ua_version = _normalize_version(match.group(1)) if match else ""
        # مهم‌ترین اصلاح: کروم جدید همیشه «Android 10» می‌فرستد؛
        # اگر hint نسخه واقعی (مثل 13/14) را داده، از آن استفاده کن.
        if hint_version and (not hint_platform or hint_platform == "android"):
            # اگر UA فریز شده (10) و hint متفاوت است، حتماً hint درست است
            if _shorten_version(ua_version) != _shorten_version(hint_version):
                return _android_from_hints(hint_version)
            return _android_from_hints(hint_version, ua_version)
        short = _shorten_version(ua_version)
        return f"Android {short}".strip() if short else "Android"

    if "macintosh" in lower_ua and "mobile/" in lower_ua:
        match = re.search(r"Version/([0-9._]+)", ua, re.IGNORECASE)
        version = _normalize_version(match.group(1)) if match else ""
        return f"iPadOS {_shorten_version(version)}".strip() if version else "iPadOS"

    if "mac os x" in lower_ua or "macintosh" in lower_ua:
        match = re.search(r"Mac OS X ([0-9_]+)", ua, re.IGNORECASE)
        version = _normalize_version(match.group(1)) if match else ""
        if hint_platform == "macos" and hint_version:
            return f"macOS {_shorten_version(hint_version)}".strip()
        return f"macOS {_shorten_version(version)}".strip() if version else "macOS"

    if "windows nt" in lower_ua:
        match = re.search(r"Windows NT ([0-9.]+)", ua, re.IGNORECASE)
        if not match:
            if hint_platform == "windows" and hint_version:
                return _windows_from_hints(hint_version) or "Windows"
            return "Windows"
        nt_version = _normalize_version(match.group(1))
        # اصلاح اصلی ویندوز: NT 10.0 هم برای ۱۰ است هم ۱۱؛ فقط hint جدا می‌کند
        if nt_version == "10.0":
            if hint_version and (not hint_platform or hint_platform == "windows"):
                refined = _windows_from_hints(hint_version)
                if refined:
                    return refined
            friendly_version = WINDOWS_VERSION_MAP.get(nt_version)
            if friendly_version:
                return f"Windows {friendly_version} (NT {nt_version})"
            return f"Windows NT {nt_version}"
        friendly_version = WINDOWS_VERSION_MAP.get(nt_version)
        if friendly_version:
            return f"Windows {friendly_version} (NT {nt_version})"
        return f"Windows NT {nt_version}"

    distro_patterns = [
        ("Ubuntu", r"Ubuntu(?:/| )([0-9.]+)"),
        ("Fedora", r"Fedora(?:/| )([0-9.]+)"),
        ("Debian", r"Debian(?:/| )([0-9.]+)"),
        ("openSUSE", r"openSUSE(?:/| )([0-9.]+)"),
        ("Red Hat", r"Red Hat(?: Enterprise Linux)?(?:/| )([0-9.]+)"),
        ("CentOS", r"CentOS(?:/| )([0-9.]+)"),
        ("Kali", r"Kali(?:/| )([0-9.]+)"),
        ("KaiOS", r"KaiOS/([0-9.]+)"),
    ]
    for label, pattern in distro_patterns:
        match = re.search(pattern, ua, re.IGNORECASE)
        if match:
            version = _normalize_version(match.group(1))
            return f"{label} {_shorten_version(version)}".strip()
        if label.lower() in lower_ua:
            return label

    if "linux" in lower_ua or "x11" in lower_ua:
        return "Linux"

    return ""
