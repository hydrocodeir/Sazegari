from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Any, Iterable
import re
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT, TA_CENTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    NextPageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from pathlib import Path

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
except Exception:  # pragma: no cover
    arabic_reshaper = None
    get_display = None



_ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
_URLISH_RE = re.compile(r"(https?://\S+|/uploads/\S+|[\w.+-]+@[\w-]+\.[\w.-]+)")


def rtl(text: str) -> str:
    """Convert RTL (Persian/Arabic) text to *visual* order for ReportLab.

    ReportLab does not perform Arabic/Persian shaping by itself. We therefore:
    1) reshape (connect) letters, then
    2) apply the bidi algorithm to obtain a visually-correct string.

    For purely LTR strings (IDs, filenames, codes, ...), we keep the text as-is.
    """
    if text is None:
        return ""
    t = str(text)
    if not t:
        return ""

    # Pure LTR strings: keep as-is (prevents reversing filenames/IDs)
    if not _ARABIC_RE.search(t):
        return t

    if not (arabic_reshaper and get_display):
        return t

    # Protect URLs / upload paths / emails so bidi doesn't mangle them
    placeholders: dict[str, str] = {}

    def _protect(m: re.Match[str]) -> str:
        key = f"__URL{len(placeholders)}__"
        placeholders[key] = m.group(0)
        return key

    protected = _URLISH_RE.sub(_protect, t)

    try:
        reshaped = arabic_reshaper.reshape(protected)
        visual = get_display(reshaped)
    except Exception:
        visual = protected

    # Restore protected chunks (wrap with LRM to keep LTR readable inside RTL)
    for key, val in placeholders.items():
        visual = visual.replace(key, f"\u200E{val}\u200E")

    return visual


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


@dataclass
class _HtmlCell:
    para: Paragraph
    colspan: int = 1
    rowspan: int = 1
    is_header: bool = False


class _CKHtmlToFlowables(HTMLParser):
    """HTML -> list of ReportLab Flowables with basic table support (incl. colspan/rowspan).

    Notes:
    - Designed for CKEditor-like HTML (simple tags, no complex CSS).
    - Preserves tables (incl. merged headers) and makes them RTL-friendly.
    """

    def __init__(self, base_style: ParagraphStyle, font_name: str, font_bold: str, max_width_cm: float = 15.0):
        super().__init__(convert_charrefs=True)
        self.base_style = base_style
        self.font_name = font_name
        self.font_bold = font_bold
        self.max_width = max_width_cm * cm

        self.flowables: list[Any] = []

        # paragraph buffer
        self._buf: list[str] = []
        self._stack: list[str] = []
        self._pending_prefix: str = ""

        # table state
        self._in_table = False
        self._in_cell = False
        self._table_rows: list[list[_HtmlCell]] = []
        self._current_row: list[_HtmlCell] | None = None
        self._cell_buf: list[str] = []
        self._cell_stack: list[str] = []
        self._cell_is_header: bool = False
        self._cell_colspan: int = 1
        self._cell_rowspan: int = 1

    def _flush_paragraph(self):
        if not self._buf:
            self._pending_prefix = ""
            return
        content = "".join(self._buf).strip()
        self._buf = []
        # close any dangling tags
        while self._stack:
            content += self._stack.pop()
        if not content:
            self._pending_prefix = ""
            return
        if self._pending_prefix:
            content = xml_escape(rtl(self._pending_prefix)) + content
            self._pending_prefix = ""
        try:
            self.flowables.append(Paragraph(content, self.base_style))
            self.flowables.append(Spacer(1, 4))
        except Exception:
            # as a last resort, strip tags
            plain = re.sub(r"<[^>]+>", "", content)
            self.flowables.append(Paragraph(xml_escape(rtl(plain)), self.base_style))
            self.flowables.append(Spacer(1, 4))

    def _flush_cell(self) -> _HtmlCell:
        content = "".join(self._cell_buf).strip()
        self._cell_buf = []
        while self._cell_stack:
            content += self._cell_stack.pop()
        if not content:
            content = ""
        # ensure base font; <b> will switch to bold via Paragraph's tags
        try:
            para = Paragraph(content, self.base_style)
        except Exception:
            plain = re.sub(r"<[^>]+>", "", content)
            para = Paragraph(xml_escape(rtl(plain)), self.base_style)

        # Header styling hint: force bold font name (helps detect header rows)
        if self._cell_is_header:
            try:
                para.style = ParagraphStyle(name="th", parent=self.base_style)
                para.style.fontName = self.font_bold
            except Exception:
                pass

        cs = max(1, int(self._cell_colspan or 1))
        rs = max(1, int(self._cell_rowspan or 1))
        return _HtmlCell(para=para, colspan=cs, rowspan=rs, is_header=self._cell_is_header)

    def _finalize_table(self):
        rows = self._table_rows or []
        if not rows:
            return

        # Determine column count from colspans
        col_count = 0
        for r in rows:
            col_count = max(col_count, sum(max(1, int(c.colspan or 1)) for c in r))
        if col_count <= 0:
            return

        # Build grid with spans
        # NOTE: We must distinguish between "empty slot" and "span placeholder".
        # Using "" for both breaks rowspan/colspan placement (cells get inserted into
        # spanned areas). We therefore use None for empty slots and a private sentinel
        # object for occupied span placeholders, and convert to "" right before
        # creating the ReportLab Table.
        grid: list[list[Any]] = []
        spans: list[tuple[int, int, int, int]] = []
        _SPAN = object()

        def ensure_row(i: int):
            while len(grid) <= i:
                grid.append([None for _ in range(col_count)])

        for r_idx, r in enumerate(rows):
            ensure_row(r_idx)
            c_idx = 0
            for cell in r:
                # find next free slot (rowspans may occupy cells)
                while c_idx < col_count and grid[r_idx][c_idx] is not None:
                    c_idx += 1
                if c_idx >= col_count:
                    break

                cs = max(1, int(cell.colspan or 1))
                rs = max(1, int(cell.rowspan or 1))

                ensure_row(r_idx + rs - 1)

                # place top-left
                grid[r_idx][c_idx] = cell.para
                # fill the spanned area with empty placeholders
                for rr in range(r_idx, r_idx + rs):
                    ensure_row(rr)
                    for cc in range(c_idx, min(col_count, c_idx + cs)):
                        if rr == r_idx and cc == c_idx:
                            continue
                        grid[rr][cc] = _SPAN

                if cs > 1 or rs > 1:
                    spans.append((c_idx, r_idx, min(col_count - 1, c_idx + cs - 1), r_idx + rs - 1))

                c_idx += cs

        # Convert placeholders to empty strings for ReportLab consumption
        for rr in range(len(grid)):
            for cc in range(col_count):
                if grid[rr][cc] is None or grid[rr][cc] is _SPAN:
                    grid[rr][cc] = ""

        # Detect header rows (leading rows that contain <th>)
        header_rows = 0
        for r in rows:
            if any(c.is_header for c in r):
                header_rows += 1
            else:
                break
        header_rows = min(header_rows, len(grid))

        # RTL-friendly: reverse columns and adjust spans
        grid = [list(reversed(r)) for r in grid]
        adj_spans: list[tuple[int, int, int, int]] = []
        for c1, r1, c2, r2 in spans:
            nc1 = (col_count - 1) - c2
            nc2 = (col_count - 1) - c1
            adj_spans.append((nc1, r1, nc2, r2))

        # Column widths proportional to content length (reasonable min)
        lens = [1] * col_count
        for r in grid:
            for idx, cell in enumerate(r):
                try:
                    txt = cell.getPlainText() if hasattr(cell, "getPlainText") else str(cell)
                except Exception:
                    txt = ""
                txt = (txt or "").strip()
                if txt:
                    lens[idx] = max(lens[idx], len(txt))

        total = sum(lens) or col_count
        min_w = 2.0 * cm
        widths = [max(min_w, self.max_width * (l / total)) for l in lens]
        s = sum(widths)
        if s > 0:
            scale = self.max_width / s
            widths = [w * scale for w in widths]

        tbl = Table(grid, colWidths=widths, hAlign="RIGHT", repeatRows=header_rows)
        tbl.splitByRow = 1

        tstyle: list[tuple] = [
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d0d7de")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]

        # Apply spans
        for c1, r1, c2, r2 in adj_spans:
            tstyle.append(("SPAN", (c1, r1), (c2, r2)))

        if header_rows > 0:
            tstyle.append(("BACKGROUND", (0, 0), (-1, header_rows - 1), colors.HexColor("#f6f8fa")))
            tstyle.append(("TEXTCOLOR", (0, 0), (-1, header_rows - 1), colors.HexColor("#24292f")))

        # Zebra rows after headers
        start_row = header_rows
        tstyle.append(("ROWBACKGROUNDS", (0, start_row), (-1, -1), [colors.white, colors.HexColor("#fbfbfc")]))

        tbl.setStyle(TableStyle(tstyle))
        self.flowables.append(tbl)
        self.flowables.append(Spacer(1, 6))
        self._table_rows = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        tag = (tag or "").lower()
        attr_map = {k.lower(): (v or "") for k, v in attrs}

        # Block boundaries
        if tag in ("p", "div", "h1", "h2", "h3", "figure") and not self._in_table:
            self._flush_paragraph()
            return

        if tag == "br":
            (self._cell_buf if self._in_cell else self._buf).append("<br/>")
            return

        # Table handling
        if tag == "table":
            if not self._in_table:
                self._flush_paragraph()
                self._in_table = True
                self._table_rows = []
            return

        if self._in_table:
            if tag == "tr":
                self._current_row = []
                return

            if tag in ("td", "th"):
                self._in_cell = True
                self._cell_buf = []
                self._cell_stack = []
                self._cell_is_header = (tag == "th")
                # colspan/rowspan
                try:
                    self._cell_colspan = int(attr_map.get("colspan") or 1)
                except Exception:
                    self._cell_colspan = 1
                try:
                    self._cell_rowspan = int(attr_map.get("rowspan") or 1)
                except Exception:
                    self._cell_rowspan = 1
                return

            # Allow basic inline formatting inside cells
            if self._in_cell:
                if tag in ("b", "strong"):
                    self._cell_buf.append("<b>")
                    self._cell_stack.append("</b>")
                    return
                if tag in ("i", "em"):
                    self._cell_buf.append("<i>")
                    self._cell_stack.append("</i>")
                    return
                if tag == "u":
                    self._cell_buf.append("<u>")
                    self._cell_stack.append("</u>")
                    return
                if tag == "a":
                    href = attr_map.get("href", "")
                    self._cell_buf.append(f'<a href="{xml_escape(href)}">')
                    self._cell_stack.append("</a>")
                    return
                if tag in ("p", "div"):
                    self._cell_buf.append("<br/>")
                    return
            return

        # Inline formatting outside table
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
            self._buf.append(f'<a href="{xml_escape(href)}">')
            self._stack.append("</a>")
            return
        if tag == "li":
            self._flush_paragraph()
            self._pending_prefix = "• "
            return
        if tag in ("ul", "ol"):
            self._flush_paragraph()
            return

    def handle_endtag(self, tag: str):
        tag = (tag or "").lower()

        if self._in_table:
            if tag in ("td", "th") and self._in_cell:
                cell = self._flush_cell()
                if self._current_row is not None:
                    self._current_row.append(cell)
                self._in_cell = False
                return

            if tag == "tr":
                if self._current_row is not None:
                    self._table_rows.append(self._current_row)
                self._current_row = None
                return

            if tag == "table":
                self._finalize_table()
                self._in_table = False
                return

            if self._in_cell and tag in ("b", "strong", "i", "em", "u", "a"):
                if self._cell_stack:
                    self._cell_buf.append(self._cell_stack.pop())
                return
            return

        if tag in ("p", "div", "li", "h1", "h2", "h3", "figure"):
            self._flush_paragraph()
            return

        if tag in ("b", "strong", "i", "em", "u", "a"):
            if self._stack:
                self._buf.append(self._stack.pop())
            return

    def handle_data(self, data: str):
        if data is None:
            return
        t = str(data)
        if not t:
            return
        if self._in_cell:
            self._cell_buf.append(xml_escape(rtl(t)))
        else:
            self._buf.append(xml_escape(rtl(t)))

    def close(self):
        super().close()
        if self._in_table:
            self._finalize_table()
            self._in_table = False
        self._flush_paragraph()

def html_to_flowables(
    html: str,
    base_style: ParagraphStyle,
    font_name: str,
    font_bold: str,
    max_width_cm: float = 15.0,
) -> list[Any]:
    """Convert HTML into a list of Flowables.

    Unlike html_to_paragraphs, this also preserves HTML tables.
    """
    if not html:
        return []
    parser = _CKHtmlToFlowables(base_style, font_name, font_bold, max_width_cm=max_width_cm)
    try:
        parser.feed(html)
        parser.close()
        return parser.flowables
    except Exception:
        # Fallback: paragraphs only
        out: list[Any] = []
        for p in html_to_paragraphs(html):
            out.append(Paragraph(p, base_style))
            out.append(Spacer(1, 4))
        return out



def _register_font() -> tuple[str, str]:
    """Register a Persian-capable font and return (regular, bold) font names.

    Preferred: Vazirmatn (embedded in the project).
      - app/static/fonts/Vazirmatn-Regular.ttf
      - app/static/fonts/Vazirmatn-Bold.ttf

    If only the variable font exists (front-end asset):
      - app/static/css/fonts/Vazirmatn[wght].ttf
    we try to instantiate Regular/Bold into a temporary folder.

    Fallback: DejaVu Sans (system) -> Helvetica.
    """

    def _try_register_pair(reg_path: Path, bold_path: Path | None) -> tuple[str, str] | None:
        try:
            pdfmetrics.registerFont(TTFont("Vazirmatn", str(reg_path)))
            bold_name = "Vazirmatn"
            if bold_path and bold_path.exists():
                pdfmetrics.registerFont(TTFont("Vazirmatn-Bold", str(bold_path)))
                bold_name = "Vazirmatn-Bold"
                try:
                    pdfmetrics.registerFontFamily(
                        "Vazirmatn",
                        normal="Vazirmatn",
                        bold="Vazirmatn-Bold",
                        italic="Vazirmatn",
                        boldItalic="Vazirmatn-Bold",
                    )
                except Exception:
                    pass
            return ("Vazirmatn", bold_name)
        except Exception:
            return None

    # 1) Embedded static fonts (best)
    try:
        static_dir = Path(__file__).resolve().parent.parent / "static" / "fonts"
        reg = static_dir / "Vazirmatn-Regular.ttf"
        bold = static_dir / "Vazirmatn-Bold.ttf"
        if reg.exists():
            out = _try_register_pair(reg, bold if bold.exists() else None)
            if out:
                return out
    except Exception:
        pass

    # 2) Variable font from front-end assets -> instantiate on the fly (robust fallback)
    try:
        var_dir = Path(__file__).resolve().parent.parent / "static" / "css" / "fonts"
        var_font = var_dir / "Vazirmatn[wght].ttf"
        if var_font.exists():
            tmp_dir = Path("/tmp/sazegari_fonts")
            tmp_dir.mkdir(parents=True, exist_ok=True)
            reg_out = tmp_dir / "Vazirmatn-Regular.ttf"
            bold_out = tmp_dir / "Vazirmatn-Bold.ttf"

            if not (reg_out.exists() and bold_out.exists()):
                try:
                    from fontTools.ttLib import TTFont as _FTFont
                    from fontTools.varLib.instancer import instantiateVariableFont as _inst

                    f1 = _FTFont(str(var_font))
                    _inst(f1, {"wght": 400}, inplace=False).save(str(reg_out))
                    f2 = _FTFont(str(var_font))
                    _inst(f2, {"wght": 700}, inplace=False).save(str(bold_out))
                except Exception:
                    # If fontTools isn't available in runtime, we'll just try to register variable font.
                    reg_out = var_font
                    bold_out = var_font

            out = _try_register_pair(reg_out, bold_out if bold_out.exists() else None)
            if out:
                return out
    except Exception:
        pass

    # 3) System DejaVu Sans
    candidates = [
        ("DejaVuSans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ("DejaVuSans", "/usr/share/fonts/dejavu/DejaVuSans.ttf"),
    ]
    for name, path in candidates:
        try:
            pdfmetrics.registerFont(TTFont(name, path))
            return (name, name)
        except Exception:
            continue

    return ("Helvetica", "Helvetica")


def _header_footer(canvas, doc, meta: dict[str, str]):
    # Support mixed page orientations (portrait/landscape)
    width, height = getattr(doc, "pagesize", A4)
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
    canvas.setFont(meta.get("font_bold", meta.get("font", "Helvetica")), 12)
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
    font_name, font_bold = _register_font()

    styles = getSampleStyleSheet()
    base = ParagraphStyle(
        name="RTL",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=10,
        leading=15,
        alignment=TA_RIGHT,
        splitLongWords=1,
    )
    h1 = ParagraphStyle(
        name="H1",
        parent=base,
        fontName=font_bold,
        fontSize=14,
        leading=20,
        alignment=TA_CENTER,
        spaceAfter=8,
    )
    h2 = ParagraphStyle(
        name="H2",
        parent=base,
        fontName=font_bold,
        fontSize=12,
        leading=18,
        spaceBefore=10,
        spaceAfter=6,
        keepWithNext=1,
    )
    small = ParagraphStyle(
        name="Small",
        parent=base,
        fontSize=9,
        leading=13,
    )


    tbl_cell = ParagraphStyle(
        name="TblCell",
        parent=small,
        alignment=TA_RIGHT,
    )
    tbl_head = ParagraphStyle(
        name="TblHead",
        parent=small,
        fontName=font_bold,
        alignment=TA_RIGHT,
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
        "font_bold": font_bold,
    }

    portrait_ps = A4
    landscape_ps = landscape(A4)

    # Keep margins consistent across orientations
    left_m = 2 * cm
    right_m = 2 * cm
    top_m = 3 * cm
    bottom_m = 2.2 * cm

    doc_tpl = BaseDocTemplate(
        buff,
        pagesize=portrait_ps,
        rightMargin=right_m,
        leftMargin=left_m,
        topMargin=top_m,
        bottomMargin=bottom_m,
        title=f"report_{getattr(report,'id','')}",
    )

    def _frame_for(ps):
        w, h = ps
        return Frame(left_m, bottom_m, w - left_m - right_m, h - top_m - bottom_m, id="F", showBoundary=0)

    on_page = lambda c, d: _header_footer(c, d, meta)
    doc_tpl.addPageTemplates(
        [
            PageTemplate(id="portrait", frames=[_frame_for(portrait_ps)], onPage=on_page, pagesize=portrait_ps),
            PageTemplate(id="landscape", frames=[_frame_for(landscape_ps)], onPage=on_page, pagesize=landscape_ps),
        ]
    )

    portrait_usable_w = portrait_ps[0] - left_m - right_m
    portrait_usable_w_cm = float(portrait_usable_w / cm)
    landscape_usable_w = landscape_ps[0] - left_m - right_m
    landscape_usable_w_cm = float(landscape_usable_w / cm)

    story: list[Any] = []
    # Cover-ish title block
    story.append(Spacer(1, 6))
    story.append(Paragraph(rtl(meta.get("title") or "گزارش سازگاری با کم‌آبی"), h1))
    if meta.get("subtitle"):
        story.append(Paragraph(rtl(meta.get("subtitle")), ParagraphStyle(name="Sub", parent=base, alignment=TA_CENTER, textColor=colors.HexColor("#57606a"))))
    story.append(Spacer(1, 10))

    # Meta table
    # Meta table (RTL-friendly: value on left, label on right)
    meta_rows: list[list[str]] = []
    meta_rows.append([rtl(str(getattr(report, "id", ""))), rtl("شماره گزارش")])
    meta_rows.append([rtl(getattr(report, "status_label", "") or getattr(getattr(report, "status", None), "value", "")), rtl("وضعیت")])
    if owner_name:
        meta_rows.append([rtl(owner_name), rtl("در صف")])
    meta_rows.append([rtl(org_name) if org_name else rtl(str(getattr(report, "org_id", ""))), rtl("ارگان")])
    meta_rows.append([rtl(county_name) if county_name else rtl(str(getattr(report, "county_id", ""))), rtl("شهرستان")])
    if created_by_name:
        meta_rows.append([rtl(created_by_name), rtl("تهیه‌کننده")])

    t = Table(meta_rows, colWidths=[11*cm, 4*cm])
    t.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#d0d7de")),
        ("BACKGROUND", (1,0), (1,-1), colors.HexColor("#f6f8fa")),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("ALIGN", (0,0), (-1,-1), "RIGHT"),
        ("RIGHTPADDING", (0,0), (-1,-1), 10),
        ("LEFTPADDING", (0,0), (-1,-1), 10),
        ("FONTNAME", (0,0), (0,-1), font_name),
        ("FONTNAME", (1,0), (1,-1), font_bold),
        ("FONTSIZE", (0,0), (-1,-1), 9.5),
        ("TEXTCOLOR", (1,0), (1,-1), colors.HexColor("#24292f")),
        ("TEXTCOLOR", (0,0), (0,-1), colors.HexColor("#0969da")),
    ]))
    story.append(t)
    story.append(Spacer(1, 12))

    # 1) Intro
    story.append(Paragraph(rtl("۱) متن ابتدایی"), h2))
    intro_html = doc.get("intro_html") or ""
    intro_flow = html_to_flowables(intro_html, base, font_name, font_bold, max_width_cm=portrait_usable_w_cm)
    if intro_flow:
        story.extend(intro_flow)
    else:
        story.append(Paragraph(rtl("—"), small))

    # Attachments
    story.append(Spacer(1, 6))
    story.append(Paragraph(rtl("پیوست‌ها"), h2))
    if attachments:
        rows = [[Paragraph(xml_escape(rtl("فایل")), tbl_head), Paragraph(xml_escape(rtl("آپلودکننده")), tbl_head)]]
        for a in attachments:
            up = uploader_map.get(getattr(a, "uploaded_by_id", 0), str(getattr(a, "uploaded_by_id", "")))
            rows.append([
                Paragraph(xml_escape(rtl(getattr(a, 'filename', ''))), tbl_cell),
                Paragraph(xml_escape(rtl(up)), tbl_cell),
            ])
        at = Table(rows, colWidths=[11*cm, 4*cm], repeatRows=1)
        at.setStyle(TableStyle([
            ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#d0d7de")),
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#f6f8fa")),
            ("FONTNAME", (0,0), (-1,0), font_bold),
            ("FONTNAME", (0,1), (-1,-1), font_name),
            ("FONTSIZE", (0,0), (-1,-1), 9),
            ("ALIGN", (0,0), (-1,-1), "RIGHT"),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("RIGHTPADDING", (0,0), (-1,-1), 10),
            ("LEFTPADDING", (0,0), (-1,-1), 10),
        ]))
        story.append(at)
    else:
        story.append(Paragraph(rtl("پیوستی ثبت نشده است."), small))

    # 2) Sections
    # Switch to landscape for the "forms" section (tables need more horizontal space)
    story.append(NextPageTemplate("landscape"))
    story.append(PageBreak())
    story.append(Paragraph(rtl("۲) فرم‌های گزارش"), h2))

    # Smaller font & better wrapping for tables in landscape pages
    land_base = ParagraphStyle(
        name="RTL_Landscape",
        parent=base,
        fontSize=9,
        leading=13,
        wordWrap="CJK",
        splitLongWords=1,
    )
    land_small = ParagraphStyle(name="SmallLand", parent=land_base, fontSize=8, leading=11)
    land_cell = ParagraphStyle(name="CellLand", parent=land_base, fontSize=8.2, leading=11)
    land_cell_bold = ParagraphStyle(name="CellLandBold", parent=land_cell, fontName=font_bold)

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
            desc_flow = html_to_flowables(desc_html or "", land_base, font_name, font_bold, max_width_cm=landscape_usable_w_cm)
            if desc_flow:
                story.extend(desc_flow)

            payload = sub.get("payload") or {}
            labels = fmeta.get("labels") if isinstance(fmeta, dict) else {}
            layout = fmeta.get("layout") if isinstance(fmeta, dict) else None
            fields_map = fmeta.get("fields") if isinstance(fmeta, dict) else None

            # Prefer layout-based rendering (same as فرم‌ساز)
            if isinstance(layout, list) and isinstance(fields_map, dict) and layout:
                total_w = landscape_usable_w
                for r in layout:
                    if not isinstance(r, dict):
                        continue
                    cols = int(r.get("columns") or 2)
                    cols = 1 if cols < 1 else (3 if cols > 3 else cols)
                    names = r.get("fields") or []
                    if not isinstance(names, list):
                        names = []
                    names = (names[:cols] + [""] * cols)[:cols]

                    row_cells = []
                    for fname in names:
                        if fname and fname in fields_map:
                            f = fields_map.get(fname) or {}
                            label = f.get("label") or labels.get(fname, fname)
                            v = payload.get(fname)
                            val = ""
                            if isinstance(v, dict) and v.get("path"):
                                val = f"{v.get('filename','file')} - {v.get('path')}"
                            elif isinstance(v, list):
                                val = ", ".join(map(str, v))
                            elif v is None:
                                val = ""
                            else:
                                val = str(v)

                            safe_val = xml_escape(rtl(str(val))).replace("\n", "<br/>")
                            cell_html = f"<b>{xml_escape(rtl(str(label)))}</b><br/>{safe_val}"
                            row_cells.append(Paragraph(cell_html, land_cell))
                        else:
                            row_cells.append(Paragraph("", land_cell))

                    # RTL: first field should appear on the right
                    if cols > 1:
                        row_cells = list(reversed(row_cells))

                    if cols == 1:
                        widths = [total_w]
                    elif cols == 3:
                        widths = [total_w/3] * 3
                    else:
                        widths = [total_w/2] * 2

                    table = Table([row_cells], colWidths=widths)
                    table.setStyle(TableStyle([
                        ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#d0d7de")),
                        ("BACKGROUND", (0,0), (-1,-1), colors.white),
                        ("FONTNAME", (0,0), (-1,-1), font_name),
                        ("FONTSIZE", (0,0), (-1,-1), 8.2),
                        ("VALIGN", (0,0), (-1,-1), "TOP"),
                        ("ALIGN", (0,0), (-1,-1), "RIGHT"),
                        ("RIGHTPADDING", (0,0), (-1,-1), 10),
                        ("LEFTPADDING", (0,0), (-1,-1), 10),
                        ("TOPPADDING", (0,0), (-1,-1), 8),
                        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
                    ]))
                    story.append(table)
                    story.append(Spacer(1, 6))
            else:
                # Fallback: key/value table
                rows: list[list[Any]] = [[Paragraph(rtl("مقدار"), land_cell_bold), Paragraph(rtl("عنوان"), land_cell_bold)]]
                for k, v in payload.items():
                    label = labels.get(k, k) if isinstance(labels, dict) else k
                    val = ""
                    if isinstance(v, dict) and v.get("path"):
                        val = f"{v.get('filename','file')} - {v.get('path')}"
                    elif isinstance(v, list):
                        val = ", ".join(map(str, v))
                    else:
                        val = str(v)
                    safe_val = xml_escape(rtl(str(val))).replace("\n", "<br/>")
                    rows.append([
                        Paragraph(safe_val, land_cell),
                        Paragraph(xml_escape(rtl(str(label))), land_cell),
                    ])

                table = Table(rows, colWidths=[landscape_usable_w * 0.65, landscape_usable_w * 0.35])
                table.setStyle(TableStyle([
                    ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#d0d7de")),
                    ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#f6f8fa")),
                    ("FONTNAME", (0,0), (-1,0), font_bold),
                    ("FONTNAME", (0,1), (-1,-1), font_name),
                    ("FONTSIZE", (0,0), (-1,-1), 8.2),
                    ("VALIGN", (0,0), (-1,-1), "TOP"),
                    ("ALIGN", (0,0), (-1,-1), "RIGHT"),
                    ("RIGHTPADDING", (0,0), (-1,-1), 10),
                    ("LEFTPADDING", (0,0), (-1,-1), 10),
                ]))
                story.append(table)
                story.append(Spacer(1, 10))
    else:
        story.append(Paragraph(rtl("هیچ فرمی به گزارش اضافه نشده است."), base))

    # Program monitoring comparative sections (snapshot tables)
    psecs = doc.get("program_sections") or []
    if isinstance(psecs, list) and psecs:
        story.append(Spacer(1, 6))
        story.append(Paragraph(rtl("پایش برنامه (گزارش مقایسه‌ای)"), h2))
        for j, ps in enumerate(psecs, start=1):
            if not isinstance(ps, dict):
                continue
            ptitle = ps.get("title") or f"پایش برنامه {j}"
            story.append(Paragraph(rtl(f"{j}. {ptitle}"), ParagraphStyle(name=f"ProgTitle{j}", parent=h2, alignment=TA_RIGHT)))

            pdesc_html = ps.get("description_html") or ""
            pdesc_flow = html_to_flowables(pdesc_html, land_base, font_name, font_bold, max_width_cm=landscape_usable_w_cm)
            if pdesc_flow:
                story.extend(pdesc_flow)

            ptable_html = ps.get("table_html") or ""
            ptable_flow = html_to_flowables(ptable_html, land_base, font_name, font_bold, max_width_cm=landscape_usable_w_cm)
            if ptable_flow:
                story.extend(ptable_flow)
            else:
                story.append(Paragraph(rtl("—"), land_small))
            story.append(Spacer(1, 10))

    # 3) Conclusion
    # Switch back to portrait for text-heavy conclusion/history pages
    story.append(NextPageTemplate("portrait"))
    story.append(PageBreak())
    story.append(Paragraph(rtl("۳) نتیجه‌گیری و نتایج"), h2))
    concl_html = doc.get("conclusion_html") or ""
    concl_flow = html_to_flowables(concl_html, base, font_name, font_bold, max_width_cm=portrait_usable_w_cm)
    if concl_flow:
        story.extend(concl_flow)
    else:
        story.append(Paragraph(rtl("—"), small))

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
        [rtl("تأیید دبیرخانه"), rtl("تأیید مدیر"), rtl("تهیه‌کننده")],
        ["\n\n\n__________________", "\n\n\n__________________", "\n\n\n__________________"],
        [rtl("نام و امضا"), rtl("نام و امضا"), rtl("نام و امضا")],
    ], colWidths=[5.2*cm, 5.2*cm, 5.2*cm])
    sig.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#d0d7de")),
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#f6f8fa")),
        ("FONTNAME", (0,0), (-1,0), font_bold),
        ("FONTNAME", (0,1), (-1,-1), font_name),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
    ]))
    story.append(sig)

    doc_tpl.build(story)

    return buff.getvalue()
