from __future__ import annotations

from pathlib import Path

from app.core.config import settings


DEFAULT_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[1] / "templates" / "reports" / "pdf_template_default.html"
)
CUSTOM_TEMPLATE_PATH = Path(settings.UPLOAD_DIR) / "report_pdf_template.html"


PLACEHOLDERS: tuple[str, ...] = (
    "title",
    "subtitle",
    "report_id",
    "kind_label",
    "status_label",
    "owner_name",
    "generated_at",
    "page_header_html",
    "page_footer_html",
    "page_number",
    "page_count",
    "intro_html",
    "sections_html",
    "sections_index_html",
    "sections_summary_html",
    "sections_tables_html",
    "sections_cards_html",
    "program_sections_html",
    "sections_raw_json",
    "conclusion_html",
    "attachments_html",
)


def get_report_pdf_template_html() -> str:
    if CUSTOM_TEMPLATE_PATH.exists():
        try:
            custom = CUSTOM_TEMPLATE_PATH.read_text(encoding="utf-8").strip()
            if custom:
                return custom
        except Exception:
            pass

    try:
        default_text = DEFAULT_TEMPLATE_PATH.read_text(encoding="utf-8").strip()
        if default_text:
            return default_text
    except Exception:
        pass

    # Hard fallback (should not normally be reached)
    return (
        '<div class="pdf-page">'
        "<h1>{{title}}</h1>"
        "<div>{{subtitle}}</div>"
        "<div>{{intro_html}}</div>"
        "<div>{{sections_html}}</div>"
        "<div>{{conclusion_html}}</div>"
        "<div>{{attachments_html}}</div>"
        "</div>"
    )


def save_report_pdf_template_html(template_html: str) -> None:
    CUSTOM_TEMPLATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CUSTOM_TEMPLATE_PATH.write_text((template_html or "").strip(), encoding="utf-8")


def reset_report_pdf_template_html() -> None:
    try:
        if CUSTOM_TEMPLATE_PATH.exists():
            CUSTOM_TEMPLATE_PATH.unlink()
    except Exception:
        pass
