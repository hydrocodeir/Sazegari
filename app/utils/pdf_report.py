from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Any, Iterable
import re
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT, TA_CENTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
except Exception:  # pragma: no cover
    arabic_reshaper = None
    get_display = None


def rtl(text: str) -> str:
    """Convert RTL (Persian/Arabic) text to visual order for ReportLab.
    Keeps URLs/path-like strings as-is.
    """
    if not text:
        return ""
    t = str(text)
    # Don't reshape URLs / file paths
    if "http://" in t or "https://" in t or "/uploads/" in t:
        return t
    if arabic_reshaper and get_display:
        try:
            reshaped = arabic_reshaper.reshape(t)
            return get_display(reshaped)
        except Exception:
            return t
    return t


class _QuillHTMLToRL(HTMLParser):
    """Very small HTML -> ReportLab paragraph markup converter.
    Supports: p, br, b/strong, i/em, u, a, ul/ol/li.
    """

    def __init__(self):
        super().__init__()
        self.paragraphs: list[str] = []
        self._buf: list[str] = []
        self._stack: list[str] = []

    def _flush(self):
        txt = "".join(self._buf).strip()
        if txt:
            self.paragraphs.append(txt)
        self._buf = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        tag = (tag or "").lower()
        attr_map = {k.lower(): (v or "") for k, v in attrs}

        if tag in ("p", "div", "h1", "h2", "h3"):
            self._flush()
            return

        if tag == "br":
            self._buf.append("<br/>")
            return

        if tag in ("b", "strong"):
            self._buf.append("<b>")
            self._stack.append("</b>")
            return

        if tag in ("i", "em"):
            self._buf.append("<i>")
            self._stack.append("</i>")
            return

        if tag == "u":
            self._buf.append("<u>")
            self._stack.append("</u>")
            return

        if tag == "a":
            href = attr_map.get("href", "")
            # avoid rtl on href
            self._buf.append(f'<a href="{xml_escape(href)}">')
            self._stack.append("</a>")
            return

        if tag == "li":
            self._flush()
            self._buf.append(rtl("• "))
            return

        if tag in ("ul", "ol"):
            self._flush()
            return

    def handle_endtag(self, tag: str):
        tag = (tag or "").lower()
        if tag in ("p", "div", "li", "h1", "h2", "h3"):
            self._flush()
            return

        if tag in ("b", "strong", "i", "em", "u", "a"):
            if self._stack:
                self._buf.append(self._stack.pop())
            return

    def handle_data(self, data: str):
        if data is None:
            return
        t = rtl(data)
        self._buf.append(xml_escape(t))

    def close(self):
        super().close()
        self._flush()


def html_to_paragraphs(html: str) -> list[str]:
    if not html:
        return []
    parser = _QuillHTMLToRL()
    try:
        parser.feed(html)
        parser.close()
        return parser.paragraphs
    except Exception:
        # fallback: strip tags very roughly
        plain = html
        plain = plain.replace("<br>", "\n").replace("<br/>", "\n")
        plain = re.sub(r"<[^>]+>", "", plain)
        lines = [rtl(x.strip()) for x in plain.splitlines() if x.strip()]
        return lines


def _register_font() -> str:
    """Try register a Persian-capable font. Return font name."""
    # DejaVu Sans is common on Debian
    candidates = [
        ("DejaVuSans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ("DejaVuSans", "/usr/share/fonts/dejavu/DejaVuSans.ttf"),
    ]
    for name, path in candidates:
        try:
            pdfmetrics.registerFont(TTFont(name, path))
            return name
        except Exception:
            continue
    return "Helvetica"


def _header_footer(canvas, doc, meta: dict[str, str]):
    width, height = A4
    canvas.saveState()

    # Header background line
    canvas.setStrokeColor(colors.HexColor("#d0d7de"))
    canvas.setLineWidth(1)
    canvas.line(2*cm, height-2.2*cm, width-2*cm, height-2.2*cm)

    # Simple vector "logo" (water drop)
    canvas.setFillColor(colors.HexColor("#0d6efd"))
    x = width - 2.2*cm
    y = height - 1.3*cm
    canvas.circle(x, y, 0.25*cm, stroke=0, fill=1)
    canvas.setFillColor(colors.HexColor("#0b5ed7"))
    canvas.circle(x, y-0.35*cm, 0.18*cm, stroke=0, fill=1)

    canvas.setFillColor(colors.black)
    title = rtl(meta.get("title", "گزارش رسمی سازگاری با کم‌آبی"))
    canvas.setFont(meta.get("font", "Helvetica"), 12)
    canvas.drawRightString(width-2.6*cm, height-1.2*cm, title)

    sub = rtl(meta.get("subtitle", "سامانه جمع‌آوری داده و گزارش‌دهی"))
    canvas.setFont(meta.get("font", "Helvetica"), 9)
    canvas.setFillColor(colors.HexColor("#57606a"))
    canvas.drawRightString(width-2.6*cm, height-1.65*cm, sub)

    # Left meta: date/report id
    canvas.setFillColor(colors.black)
    canvas.setFont(meta.get("font", "Helvetica"), 9)
    left = f"{meta.get('date','')}  |  {meta.get('report_no','')}"
    canvas.drawString(2*cm, height-1.55*cm, left)

    # Footer page number
    canvas.setStrokeColor(colors.HexColor("#d0d7de"))
    canvas.line(2*cm, 1.6*cm, width-2*cm, 1.6*cm)

    canvas.setFillColor(colors.HexColor("#57606a"))
    page_text = rtl(f"صفحه {canvas.getPageNumber()}")
    canvas.setFont(meta.get("font", "Helvetica"), 9)
    canvas.drawRightString(width-2*cm, 1.0*cm, page_text)

    canvas.restoreState()


def build_report_pdf(
    report,
    doc: dict,
    attachments: list,
    uploader_map: dict[int, str],
    logs: list,
    actor_map: dict[int, str],
    owner_name: str | None = None,
    org_name: str | None = None,
    county_name: str | None = None,
    created_by_name: str | None = None,
) -> bytes:
    """Build an official-looking PDF from report doc."""
    font_name = _register_font()

    styles = getSampleStyleSheet()
    base = ParagraphStyle(
        name="RTL",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=10,
        leading=15,
        alignment=TA_RIGHT,
    )
    h1 = ParagraphStyle(
        name="H1",
        parent=base,
        fontSize=14,
        leading=20,
        alignment=TA_CENTER,
        spaceAfter=8,
    )
    h2 = ParagraphStyle(
        name="H2",
        parent=base,
        fontSize=12,
        leading=18,
        spaceBefore=10,
        spaceAfter=6,
    )
    small = ParagraphStyle(
        name="Small",
        parent=base,
        fontSize=9,
        leading=13,
    )

    from io import BytesIO
    buff = BytesIO()

    meta_doc = doc.get("meta") if isinstance(doc, dict) else None
    meta_doc = meta_doc if isinstance(meta_doc, dict) else {}

    default_title = "گزارش رسمی سازگاری با کم‌آبی"
    default_subtitle = ""
    # Subtitle suggestion based on report kind/org/county
    try:
        kind_label = getattr(report, "kind_label", "") or getattr(getattr(report, "kind", None), "value", "")
    except Exception:
        kind_label = ""
    if org_name and county_name:
        default_subtitle = f"{kind_label} | {org_name} - {county_name}"
    elif org_name:
        default_subtitle = f"{kind_label} | {org_name}"
    else:
        default_subtitle = kind_label or ""

    meta = {
        "title": meta_doc.get("title") or default_title,
        "subtitle": meta_doc.get("subtitle") or default_subtitle or "سامانه جمع‌آوری داده و گزارش‌دهی",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "report_no": f"Report #{getattr(report,'id', '')}",
        "font": font_name,
    }

    doc_tpl = SimpleDocTemplate(
        buff,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=3*cm,
        bottomMargin=2.2*cm,
        title=f"report_{getattr(report,'id','')}",
    )

    story: list[Any] = []
    story.append(Paragraph(rtl(meta.get("title") or "گزارش سازگاری با کم‌آبی"), h1))
    story.append(Spacer(1, 6))

    # Meta table
    meta_rows = []
    meta_rows.append([rtl("شماره گزارش"), rtl(str(getattr(report, "id", "")))])
    meta_rows.append([rtl("وضعیت"), rtl(getattr(report, "status_label", "") or getattr(getattr(report, "status", None), "value", ""))])
    if owner_name:
        meta_rows.append([rtl("در صف"), rtl(owner_name)])
    if org_name:
        meta_rows.append([rtl("ارگان"), rtl(org_name)])
    else:
        meta_rows.append([rtl("ارگان"), rtl(str(getattr(report, "org_id", "")))])
    if county_name:
        meta_rows.append([rtl("شهرستان"), rtl(county_name)])
    else:
        meta_rows.append([rtl("شهرستان"), rtl(str(getattr(report, "county_id", "")))])
    if created_by_name:
        meta_rows.append([rtl("تهیه‌کننده"), rtl(created_by_name)])

    t = Table(meta_rows, colWidths=[4*cm, 11*cm])
    t.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#d0d7de")),
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#f6f8fa")),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("FONTNAME", (0,0), (-1,-1), font_name),
        ("FONTSIZE", (0,0), (-1,-1), 9),
    ]))
    story.append(t)
    story.append(Spacer(1, 12))

    # 1) Intro
    story.append(Paragraph(rtl("۱) متن ابتدایی"), h2))
    intro_html = doc.get("intro_html") or ""
    for p in html_to_paragraphs(intro_html):
        story.append(Paragraph(p, base))
        story.append(Spacer(1, 4))

    # Attachments
    story.append(Spacer(1, 6))
    story.append(Paragraph(rtl("پیوست‌ها"), h2))
    if attachments:
        for a in attachments:
            up = uploader_map.get(getattr(a, "uploaded_by_id", 0), str(getattr(a, "uploaded_by_id", "")))
            line = f"- {getattr(a,'filename','')} ({up})"
            story.append(Paragraph(xml_escape(rtl(line)), small))
            url = getattr(a, "url", "")
            if url:
                story.append(Paragraph(xml_escape(url), ParagraphStyle(name="Url", parent=small, alignment=TA_RIGHT)))
            story.append(Spacer(1, 3))
    else:
        story.append(Paragraph(rtl("پیوستی ثبت نشده است."), small))

    # 2) Sections
    story.append(PageBreak())
    story.append(Paragraph(rtl("۲) فرم‌های گزارش"), h2))

    agg = doc.get("aggregation") or {}
    subs = agg.get("submissions") or []
    forms_meta = agg.get("forms") or {}

    # map submission id -> object
    subs_map = {s.get("id"): s for s in subs if isinstance(s, dict)}
    sections = doc.get("sections") or []
    if sections:
        for i, sec in enumerate(sections, start=1):
            sid = sec.get("submission_id") if isinstance(sec, dict) else None
            sub = subs_map.get(sid)
            if not sub:
                continue
            fmeta = forms_meta.get(str(sub.get("form_id")), {}) if isinstance(forms_meta, dict) else {}
            title = fmeta.get("title") or sub.get("form_title") or f"Submission {sid}"
            story.append(Paragraph(rtl(f"{i}. {title} (Submission #{sid})"), ParagraphStyle(name="SecTitle", parent=h2, alignment=TA_RIGHT)))

            desc_html = sec.get("description_html") if isinstance(sec, dict) else ""
            for p in html_to_paragraphs(desc_html or ""):
                story.append(Paragraph(p, base))
                story.append(Spacer(1, 3))

            payload = sub.get("payload") or {}
            labels = fmeta.get("labels") if isinstance(fmeta, dict) else {}
            rows = [[rtl("عنوان"), rtl("مقدار")]]
            for k, v in payload.items():
                label = labels.get(k, k) if isinstance(labels, dict) else k
                val = ""
                if isinstance(v, dict) and v.get("path"):
                    val = f"{v.get('filename','file')} - {v.get('path')}"
                elif isinstance(v, list):
                    val = ", ".join(map(str, v))
                else:
                    val = str(v)
                rows.append([rtl(str(label)), rtl(val)])

            table = Table(rows, colWidths=[6*cm, 9*cm])
            table.setStyle(TableStyle([
                ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#d0d7de")),
                ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#f6f8fa")),
                ("FONTNAME", (0,0), (-1,-1), font_name),
                ("FONTSIZE", (0,0), (-1,-1), 9),
                ("VALIGN", (0,0), (-1,-1), "TOP"),
            ]))
            story.append(table)
            story.append(Spacer(1, 10))
    else:
        story.append(Paragraph(rtl("هیچ فرمی به گزارش اضافه نشده است."), base))

    # 3) Conclusion
    story.append(PageBreak())
    story.append(Paragraph(rtl("۳) نتیجه‌گیری و نتایج"), h2))
    concl_html = doc.get("conclusion_html") or ""
    for p in html_to_paragraphs(concl_html):
        story.append(Paragraph(p, base))
        story.append(Spacer(1, 4))

    # History
    story.append(Spacer(1, 8))
    story.append(Paragraph(rtl("تاریخچه گردش"), h2))
    if logs:
        for l in logs:
            actor = actor_map.get(getattr(l, "actor_id", 0), str(getattr(l, "actor_id", "")))
            line = f"- {getattr(l,'action','')} | {getattr(l,'from_status','')} -> {getattr(l,'to_status','')} | {actor}"
            story.append(Paragraph(xml_escape(rtl(line)), small))
    else:
        story.append(Paragraph(rtl("تاریخچه‌ای ثبت نشده است."), small))

    # Signature / seal
    story.append(Spacer(1, 14))
    story.append(Paragraph(rtl("محل امضا و مهر"), h2))
    sig = Table([
        [rtl("تهیه‌کننده"), rtl("تأیید مدیر"), rtl("تأیید دبیرخانه")],
        ["\n\n\n__________________", "\n\n\n__________________", "\n\n\n__________________"],
        [rtl("نام و امضا"), rtl("نام و امضا"), rtl("نام و امضا")],
    ], colWidths=[5.2*cm, 5.2*cm, 5.2*cm])
    sig.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#d0d7de")),
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#f6f8fa")),
        ("FONTNAME", (0,0), (-1,-1), font_name),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
    ]))
    story.append(sig)

    doc_tpl.build(
        story,
        onFirstPage=lambda c, d: _header_footer(c, d, meta),
        onLaterPages=lambda c, d: _header_footer(c, d, meta),
    )

    return buff.getvalue()
