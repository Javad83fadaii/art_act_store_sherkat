from __future__ import annotations

import io
import os
from decimal import Decimal
from pathlib import Path

from django.conf import settings

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import arabic_reshaper
from bidi.algorithm import get_display


_FONTS_REGISTERED = False


def _register_fonts():
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return

    base_dir = Path(settings.BASE_DIR)
    static_font_dir = base_dir / 'static' / 'fonts'
    reg_font_path = static_font_dir / 'Tahoma-Regular.ttf'
    bold_font_path = static_font_dir / 'Tahoma-Bold.ttf'

    # Fallback to Windows fonts if not found
    if not reg_font_path.exists():
        win_reg = Path('C:/Windows/Fonts/tahoma.ttf')
        if win_reg.exists():
            reg_font_path = win_reg
    if not bold_font_path.exists():
        win_bold = Path('C:/Windows/Fonts/tahomabd.ttf')
        if win_bold.exists():
            bold_font_path = win_bold

    if reg_font_path.exists():
        pdfmetrics.registerFont(TTFont('Tahoma', str(reg_font_path)))
        pdfmetrics.registerFont(TTFont('Morabba', str(reg_font_path)))
    if bold_font_path.exists():
        pdfmetrics.registerFont(TTFont('Tahoma-Bold', str(bold_font_path)))
        pdfmetrics.registerFont(TTFont('Morabba-Bold', str(bold_font_path)))

    _FONTS_REGISTERED = True


def fa_text(val) -> str:
    if val is None or val == '':
        return ''
    text = str(val).strip()
    try:
        configuration = {
            'delete_harakat': False,
            'support_ligatures': True,
        }
        reshaper = arabic_reshaper.ArabicReshaper(configuration=configuration)
        reshaped = reshaper.reshape(text)
        return get_display(reshaped)
    except Exception:
        return text


def format_amount(value) -> str:
    try:
        amount = int(Decimal(str(value or 0)))
        return f"{amount:,}"
    except Exception:
        return str(value or 0)


def generate_invoice_pdf_buffer(invoice) -> io.BytesIO:
    _register_fonts()
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    elements = []

    # Title & Main Info
    buyer_name = (
        getattr(invoice.user, 'get_full_name', lambda: '')()
        or getattr(invoice.user, 'full_name', '')
        or 'کاربر گرامی'
    )
    buyer_phone = getattr(invoice.user, 'phone_number', '') or '-'
    auction_name = invoice.auction.name or f"مزایده شماره {invoice.auction_id}"
    issued_date = invoice.jalali_issued_at

    # Header Table: Col 0 is LEFT, Col 1 is RIGHT
    header_data = [
        [fa_text('صورتحساب رسمی فروش مزایده'), ''],
        [fa_text(f'شماره فاکتور: {invoice.invoice_number}'), fa_text(f'نام خریدار: {buyer_name}')],
        [fa_text(f'تاریخ صدور: {issued_date}'), fa_text(f'رویداد مزایده: {auction_name}')],
        [fa_text(f'شماره تماس: {buyer_phone}'), ''],
    ]

    header_table = Table(header_data, colWidths=[260, 260])
    header_table.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, -1), 'Tahoma'),
        ('FONT', (0, 0), (0, 0), 'Tahoma-Bold'),
        ('FONTSIZE', (0, 0), (0, 0), 12),
        ('FONTSIZE', (0, 1), (-1, -1), 8.5),
        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('SPAN', (0, 0), (1, 0)),
        ('ALIGN', (0, 0), (0, 0), 'CENTER'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BACKGROUND', (0, 0), (1, 0), colors.HexColor('#F1F5F9')),
        ('LINEBELOW', (0, 0), (1, 0), 1.5, colors.HexColor('#CBD5E1')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 14))

    # Items Table (RTL Column Order):
    # Col 0 (LEFT): قیمت خالص (تومان) [140]
    # Col 1: عنوان اثر [270]
    # Col 2: کد / لات [70]
    # Col 3 (RIGHT): ردیف [40]
    # Total width = 520
    items_data = [
        [
            fa_text('قیمت خالص (تومان)'),
            fa_text('عنوان اثر'),
            fa_text('کد / لات'),
            fa_text('ردیف'),
        ]
    ]

    items = list(invoice.items.all().order_by('lot', 'id'))
    for index, item in enumerate(items, start=1):
        lot_label = f"لات {item.lot}" if item.lot else (item.product_code or '-')
        items_data.append([
            fa_text(format_amount(item.hammer_price)),
            fa_text(item.title or '-'),
            fa_text(lot_label),
            fa_text(str(index)),
        ])

    # Totals rows: labels on the RIGHT (Cols 1 to 3 spanned), amounts on the LEFT (Col 0)
    total_hammer = format_amount(invoice.total_hammer_price) + ' تومان'
    premium = format_amount(invoice.buyers_premium) + ' تومان'
    grand_total = format_amount(invoice.total_amount) + ' تومان'

    items_data.append([
        fa_text(total_hammer),
        fa_text('جمع مبالغ چکش‌خورده خالص:'), '', '',
    ])
    items_data.append([
        fa_text(premium),
        fa_text('۱۰٪ حق‌العمل حراج‌گزار (کارمزد و خدمات قانونی):'), '', '',
    ])
    items_data.append([
        fa_text(grand_total),
        fa_text('مبلغ کل قابل پرداخت (مجموع خالص + ۱۰٪):'), '', '',
    ])

    num_rows = len(items_data)
    items_table = Table(items_data, colWidths=[140, 270, 70, 40], repeatRows=1)
    items_table.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, -1), 'Tahoma'),
        ('FONT', (0, 0), (-1, 0), 'Tahoma-Bold'),
        ('FONT', (0, num_rows - 3), (-1, num_rows - 1), 'Tahoma-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8.5),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (1, 1), (1, num_rows - 4), 'RIGHT'),
        ('ALIGN', (1, num_rows - 3), (1, num_rows - 1), 'RIGHT'),
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F1F5F9')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('SPAN', (1, num_rows - 3), (3, num_rows - 3)),
        ('SPAN', (1, num_rows - 2), (3, num_rows - 2)),
        ('SPAN', (1, num_rows - 1), (3, num_rows - 1)),
        ('BACKGROUND', (0, num_rows - 3), (-1, num_rows - 3), colors.HexColor('#F8FAFC')),
        ('BACKGROUND', (0, num_rows - 2), (-1, num_rows - 2), colors.HexColor('#F8FAFC')),
        ('BACKGROUND', (0, num_rows - 1), (-1, num_rows - 1), colors.HexColor('#E2E8F0')),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 14))

    # Notes Table
    notes_data = [
        [fa_text('توضیحات و شرایط قانونی:')],
        [fa_text('۱. این صورتحساب رسمی پس از اتمام قطعی مزایده به صورت سیستمی صادر گردیده و مدارک و اقلام فوق متعلق به برنده قطعی می‌باشد.')],
        [fa_text('۲. کارمزد و خدمات قانونی حراج‌گزار ۱۰٪ محاسبه شده و به مبلغ خالص چکش‌خورده اضافه گردیده است.')],
        [fa_text('۳. کلیه مبالغ مندرج در این فاکتور به تومان می‌باشد.')],
    ]
    notes_table = Table(notes_data, colWidths=[520])
    notes_table.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, -1), 'Tahoma'),
        ('FONT', (0, 0), (0, 0), 'Tahoma-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 7.5),
        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#FAFAFA')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(notes_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer

