import json
import os
import uuid
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, Response, JSONResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.config import settings
from app.auth.deps import get_current_user
from app.core.rbac import require, can_view_report, can_create_report, is_secretariat
from app.core.workflow import (
    allowed_actions,
    allowed_actions_for_status,
    can_edit as wf_can_edit,
    can_delete as wf_can_delete,
    get_recipients,
    get_transition,
)
from app.db.models.report import Report, ReportStatus
from app.db.models.workflow_log import WorkflowLog
from app.db.models.report_submission import ReportSubmission
from app.db.models.report_attachment import ReportAttachment
from app.db.models.notification import Notification
from app.db.models.submission import Submission
from app.db.models.form_template import FormTemplate
from app.db.models.org_county import OrgCountyUnit
from app.db.models.program_form_type import ProgramFormType
from app.db.models.program_baseline import ProgramBaseline
from app.db.models.user import User, Role
from app.db.models.report_audit_log import ReportAuditLog
from app.db.models.report import ReportKind
from app.utils.badges import get_badge_count, invalidate_badge
from app.utils.report_agg import aggregate_content
from app.utils.report_doc import load_doc, dump_doc
from app.utils.program_report import build_program_report, resolve_latest_period
from app.utils.notify import notify

router = APIRouter(prefix="/reports", tags=["reports"])

UPLOAD_DIR = settings.UPLOAD_DIR

def _linked_submission_ids(db: Session, report_id: int) -> list[int]:
    links = db.query(ReportSubmission).filter(ReportSubmission.report_id == report_id).all()
    return [l.submission_id for l in links]

def _sync_sections(doc: dict, linked_ids: list[int]) -> dict:
    """Ensure doc['sections'] exists and only references attached submissions.
    If sections is empty but there are linked submissions, create sections in linked order.
    """
    linked_set = set(linked_ids)
    sections = doc.get("sections") if isinstance(doc, dict) else None
    if not isinstance(sections, list):
        sections = []
    # drop sections that are no longer attached
    sections = [s for s in sections if isinstance(s, dict) and s.get("submission_id") in linked_set]
    if not sections and linked_ids:
        sections = [{"submission_id": sid, "description_html": ""} for sid in linked_ids]
    doc["sections"] = sections
    return doc


def _audit(
    db: Session,
    report_id: int,
    actor_id: int,
    action: str,
    field: str = "",
    before: dict | list | str | None = None,
    after: dict | list | str | None = None,
    comment: str = "",
) -> None:
    """ثبت لاگ تغییرات گزارش (ایجاد/ویرایش/حذف و ...)."""

    def _dump(v):
        if v is None:
            return ""
        if isinstance(v, str):
            return v
        try:
            return json.dumps(v, ensure_ascii=False)
        except Exception:
            return str(v)

    db.add(
        ReportAuditLog(
            report_id=report_id,
            actor_id=actor_id,
            action=action,
            field=field or "",
            before_json=_dump(before),
            after_json=_dump(after),
            comment=comment or "",
        )
    )




def _last_sender_user(db: Session, report: Report) -> User | None:
    """آخرین ارسال‌کننده‌ی «رو به بالا» به وضعیت فعلی گزارش.

    این تابع برای action = request_revision استفاده می‌شود: وقتی یک مرحله نیاز به اصلاح دارد
    باید به مرحله‌ی قبلی (فرد/سمتی که گزارش را از او دریافت کرده‌ایم در مسیر *ارسال رو به بالا*)
    برگردانده شود.

    نکته: ورود به یک وضعیت می‌تواند هم با «ارسال/تأیید رو به بالا» اتفاق بیفتد و هم با
    «برگشت برای اصلاح». برای پیدا کردن ارسال‌کننده‌ی صحیح، لاگ‌هایی که action = request_revision
    هستند را نادیده می‌گیریم.

    در صورت نبود لاگ مناسب، به created_by_id برمی‌گردیم.
    """
    # NOTE: WorkflowLog در این پروژه timestamp ندارد؛ پس id (auto-increment) معیار ترتیب است.
    log = (
        db.query(WorkflowLog)
        .filter(
            WorkflowLog.report_id == report.id,
            WorkflowLog.to_status == report.status,
            WorkflowLog.action != "request_revision",
        )
        .order_by(WorkflowLog.id.desc())
        .first()
    )

    sender_id = (log.actor_id if log and getattr(log, "actor_id", None) else None) or report.created_by_id
    if not sender_id:
        return None
    return db.get(User, int(sender_id))

def _eligible_recipients(db: Session, report: Report, action: str) -> list[User]:
    """گیرنده‌های مجاز برای هر اقدام (State Machine Driven)."""
    try:
        recipients = get_recipients(db, report, action)
    except KeyError:
        recipients = []

    # Fix: For provincial reports, when the provincial manager requests revision,
    # the report must return ONLY to the provincial expert who last sent it up.
    # (Never show county experts in the dropdown.)
    if (
        action == "request_revision"
        and report.kind == ReportKind.PROVINCIAL
        and report.status == ReportStatus.PROV_MANAGER_REVIEW
    ):
        sender = _last_sender_user(db, report)
        if sender and sender.role == Role.ORG_PROV_EXPERT and sender.org_id == report.org_id:
            return [sender]

    # Fallback: for request_revision, if config yields none, send back to last sender.
    if action == "request_revision" and not recipients:
        sender = _last_sender_user(db, report)
        return [sender] if sender else []

    return recipients

def _can_act(user: User, report: Report, action: str) -> bool:
    # allowed_actions() already checks: final + current owner + role/state
    return action in allowed_actions(user, report)


def _can_edit(user: User, report: Report) -> bool:
    return wf_can_edit(user, report)


def _action_label(action: str) -> str:
    return {
        "submit_for_review": "ارسال برای بررسی",
        "approve": "تأیید",
        "request_revision": "نیاز به اصلاح",
        "final_approve": "تأیید نهایی",
    }.get(action, action)


def _role_fa(role: Role) -> str:
    return {
        Role.ORG_COUNTY_EXPERT: "کارشناس شهرستان",
        Role.ORG_COUNTY_MANAGER: "مدیر شهرستان",
        Role.ORG_PROV_EXPERT: "کارشناس استان",
        Role.ORG_PROV_MANAGER: "مدیر استان",
        Role.SECRETARIAT_USER: "کارشناس دبیرخانه",
        Role.SECRETARIAT_ADMIN: "مدیر دبیرخانه",
    }.get(role, role.value)

@router.get("", response_class=HTMLResponse)
def page(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = db.query(Report).order_by(Report.id.desc())
    if user.role.value.startswith("secretariat"):
        reports = q.limit(200).all()
    elif user.role.value.startswith("org_prov"):
        reports_q = q.filter(Report.org_id == user.org_id)
        if user.role == Role.ORG_PROV_EXPERT:
            reports_q = reports_q.filter(Report.current_owner_id == user.id)
        reports = reports_q.limit(200).all()
    else:
        # شهرستان: گزارش‌های شهرستان خودش + هر گزارش استانی که در صف او قرار گرفته است
        reports_q = q.filter(
            Report.org_id == user.org_id,
            ((Report.county_id == user.county_id) | ((Report.county_id.is_(None)) & (Report.current_owner_id == user.id))),
        )
        if user.role == Role.ORG_COUNTY_EXPERT:
            reports_q = reports_q.filter((Report.created_by_id == user.id) | (Report.current_owner_id == user.id))
        reports = reports_q.limit(200).all()

    subs = []
    if user.role in (Role.ORG_COUNTY_EXPERT, Role.ORG_COUNTY_MANAGER) and user.org_id and user.county_id:
        subs = (
            db.query(Submission)
            .filter(Submission.org_id == user.org_id, Submission.county_id == user.county_id)
            .order_by(Submission.id.desc())
            .limit(200)
            .all()
        )

    forms_map_subs = {}
    if subs:
        fids = list({s.form_id for s in subs})
        forms_map_subs = {f.id: f.title for f in db.query(FormTemplate).filter(FormTemplate.id.in_(fids)).all()} if fids else {}


    # Map owner user_id -> display name for list view
    owner_names = {}
    owner_ids = list({r.current_owner_id for r in reports if getattr(r, 'current_owner_id', None)})
    if owner_ids:
        owner_names = {
            u.id: (u.full_name or u.username or str(u.id))
            for u in db.query(User).filter(User.id.in_(owner_ids)).all()
        }

    return request.app.state.templates.TemplateResponse(
        "reports/index.html",
        {"request": request, "reports": reports, "subs": subs, "forms_map_subs": forms_map_subs, "owner_names": owner_names, "user": user, "badge_count": get_badge_count(db, user)},
    )

@router.post("")
def create(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    kind: str = Query(""),
):
    require(can_create_report(user))
    require(user.org_id is not None, "کاربر باید org_id داشته باشد.", 400)

    # نوع گزارش
    kind_enum = ReportKind.PROVINCIAL if (kind or "").lower() in ("provincial", "province", "ostan") else ReportKind.COUNTY
    # محدودیت نوع گزارش بر اساس نقش
    if kind_enum == ReportKind.PROVINCIAL:
        require(user.role == Role.ORG_PROV_EXPERT, "فقط کارشناس استان می‌تواند گزارش استانی ایجاد کند.", 403)
    else:
        require(user.role == Role.ORG_COUNTY_EXPERT, "فقط کارشناس شهرستان می‌تواند گزارش شهرستان ایجاد کند.", 403)
        require(user.county_id is not None, "کاربر شهرستان باید county_id داشته باشد.", 400)

    # گزارش به صورت Draft ساخته می‌شود و کاربر در صفحه‌ی ویرایش (builder) متن اولیه، بخش‌های فرم و نتیجه‌گیری را اضافه می‌کند.
    r = Report(
        org_id=user.org_id,
        county_id=user.county_id if kind_enum == ReportKind.COUNTY else None,
        created_by_id=user.id,
        current_owner_id=user.id,
        status=ReportStatus.DRAFT,
        kind=kind_enum,
        content_json=dump_doc({"intro_html": "", "conclusion_html": "", "meta": {"title": "", "subtitle": ""}, "sections": [], "program_sections": [], "aggregation": {}}),
        note="",
    )
    db.add(r)
    db.commit()
    db.refresh(r)

    _audit(db, r.id, user.id, action="create", field="report", before=None, after={"kind": r.kind.value})
    db.commit()

    return RedirectResponse(f"/reports/{r.id}", status_code=303)


@router.post("/{report_id}/delete")
def delete_report(
    report_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    r = db.get(Report, report_id)
    require(r is not None, "گزارش یافت نشد", 404)
    require(can_view_report(user, r.org_id, r.county_id, r.current_owner_id))
    require(wf_can_delete(user, r), "شما اجازه حذف این گزارش را ندارید.", 403)

    # ثبت لاگ قبل از حذف
    _audit(db, r.id, user.id, action="delete", field="report", before={"kind": r.kind.value, "status": r.status.value, "content": load_doc(r.content_json)}, after=None)
    db.commit()

    # حذف وابستگی‌ها
    db.query(WorkflowLog).filter(WorkflowLog.report_id == r.id).delete(synchronize_session=False)
    db.query(ReportSubmission).filter(ReportSubmission.report_id == r.id).delete(synchronize_session=False)
    # حذف فایل‌های پیوست و رکوردها
    atts = db.query(ReportAttachment).filter(ReportAttachment.report_id == r.id).all()
    for a in atts:
        try:
            if a.path and os.path.exists(a.path):
                os.remove(a.path)
        except Exception:
            pass
    db.query(ReportAttachment).filter(ReportAttachment.report_id == r.id).delete(synchronize_session=False)
    db.query(ReportAuditLog).filter(ReportAuditLog.report_id == r.id).delete(synchronize_session=False)

    db.delete(r)
    db.commit()

    return RedirectResponse("/reports", status_code=303)


@router.get("/{report_id}", response_class=HTMLResponse)
def view(request: Request, report_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    r = db.get(Report, report_id)
    require(r is not None, "گزارش یافت نشد", 404)
    require(can_view_report(user, r.org_id, r.county_id, r.current_owner_id))

    # Auto-mark notifications as read when user opens the related report.
    # This keeps notifications personal and removes the need for manual "mark read".
    updated = (
        db.query(Notification)
        .filter(
            Notification.user_id == user.id,
            Notification.report_id == r.id,
            Notification.is_read == False,
        )
        .update({"is_read": True}, synchronize_session=False)
    )
    if updated:
        db.commit()
        invalidate_badge(user.id)

    logs = db.query(WorkflowLog).filter(WorkflowLog.report_id == r.id).order_by(WorkflowLog.id.desc()).all()

    audit_logs = (
        db.query(ReportAuditLog)
        .filter(ReportAuditLog.report_id == r.id)
        .order_by(ReportAuditLog.id.desc())
        .limit(500)
        .all()
    )

    actor_ids = list({l.actor_id for l in logs} | {a.actor_id for a in audit_logs})
    users_map = {u.id: u for u in db.query(User).filter(User.id.in_(actor_ids)).all()} if actor_ids else {}
    actor_map = {uid: (users_map[uid].full_name or users_map[uid].username) for uid in users_map}

    actions = allowed_actions(user, r)

    action_recipients = {a: _eligible_recipients(db, r, a) for a in actions}

    attachments = db.query(ReportAttachment).filter(ReportAttachment.report_id == r.id).order_by(ReportAttachment.id.desc()).all()

    owner_name = None
    if r.current_owner_id:
        ou = db.get(User, r.current_owner_id)
        owner_name = (ou.full_name or ou.username) if ou else str(r.current_owner_id)

    uploader_ids = list({a.uploaded_by_id for a in attachments})
    uploader_users = {u.id: u for u in db.query(User).filter(User.id.in_(uploader_ids)).all()} if uploader_ids else {}
    uploader_map = {uid: (uploader_users[uid].full_name or uploader_users[uid].username) for uid in uploader_users}

    links = db.query(ReportSubmission).filter(ReportSubmission.report_id == r.id).all()
    sub_ids = [l.submission_id for l in links]
    attached_subs = db.query(Submission).filter(Submission.id.in_(sub_ids)).all() if sub_ids else []

    fids = list({s.form_id for s in attached_subs})
    forms_map_attached = {f.id: f.title for f in db.query(FormTemplate).filter(FormTemplate.id.in_(fids)).all()} if fids else {}

    available_subs = []
    if _can_edit(user, r):
        # County report: show submissions for the same org/county
        if r.kind == ReportKind.COUNTY and r.org_id and r.county_id:
            available_subs = (
                db.query(Submission)
                .filter(Submission.org_id == r.org_id, Submission.county_id == r.county_id)
                .order_by(Submission.id.desc())
                .limit(200)
                .all()
            )
        # Provincial report: only province-scope submissions (county_id = NULL)
        elif r.kind == ReportKind.PROVINCIAL and r.org_id:
            available_subs = (
                db.query(Submission)
                .join(FormTemplate, Submission.form_id == FormTemplate.id)
                .filter(
                    Submission.org_id == r.org_id,
                    Submission.county_id.is_(None),
                    FormTemplate.scope == "province",
                )
                .order_by(Submission.id.desc())
                .limit(200)
                .all()
            )

    available_forms = []

    forms_map_available = {}
    if available_subs:
        fids2 = list({s.form_id for s in available_subs})
        forms_map_available = {f.id: f.title for f in db.query(FormTemplate).filter(FormTemplate.id.in_(fids2)).all()} if fids2 else {}
        available_forms = db.query(FormTemplate).filter(FormTemplate.id.in_(fids2)).order_by(FormTemplate.title).all() if fids2 else []

    # Program monitoring types (created by secretariat admin) usable in reports.
    program_types = []
    if _can_edit(user, r) and r.org_id:
        all_types = (
            db.query(ProgramFormType)
            .filter(ProgramFormType.org_id == int(r.org_id))
            .order_by(ProgramFormType.title.asc(), ProgramFormType.id.asc())
            .all()
        )
        if all_types:
            baselines = (
                db.query(ProgramBaseline)
                .filter(ProgramBaseline.org_id == int(r.org_id), ProgramBaseline.form_type_id.in_([t.id for t in all_types]))
                .all()
            )
            has_baseline = {int(b.form_type_id) for b in baselines}
            program_types = [t for t in all_types if int(t.id) in has_baseline]



    return request.app.state.templates.TemplateResponse(
        "reports/view.html",
        {
            "request": request,
            "report": r,
            "doc": load_doc(r.content_json),
            "logs": logs,
            "audit_logs": audit_logs,
            "actions": actions,
            "action_recipients": action_recipients,
            "attached_subs": attached_subs,
            "forms_map_attached": forms_map_attached,
            "attachments": attachments,
            "owner_name": owner_name,
            "uploader_map": uploader_map,
            "available_subs": available_subs,
            "forms_map_available": forms_map_available,
            "available_forms": available_forms,
            "program_types": program_types,
            "user": user,
            "badge_count": get_badge_count(db, user),
            "actor_map": actor_map,
            "can_edit": _can_edit(user, r),
        },
    )


@router.get("/{report_id}/permissions")
def permissions(report_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """JSON permissions endpoint for SPA/React.

    Returns exactly what the client needs to render buttons and recipient dropdowns.
    """
    r = db.get(Report, report_id)
    require(r is not None, "گزارش یافت نشد", 404)
    require(can_view_report(user, r.org_id, r.county_id, r.current_owner_id))

    # What actions exist for this state, and which of them are allowed for this user
    state_actions = list(allowed_actions_for_status(r.kind, r.status))
    user_allowed = set(allowed_actions(user, r))

    actions_payload = []
    for action in state_actions:
        is_allowed = action in user_allowed
        recipients = _eligible_recipients(db, r, action) if is_allowed else []
        try:
            t = get_transition(r.kind, r.status, action)
            to_status = t.to_status.value if hasattr(t.to_status, "value") else str(t.to_status)
            recipient_roles = [role.value for role in (t.recipient_roles or ())]
        except Exception:
            to_status = ""
            recipient_roles = []

        actions_payload.append(
            {
                "action": action,
                "label": _action_label(action),
                "allowed": is_allowed,
                "to_status": to_status,
                "recipient_roles": recipient_roles,
                "recipients": [
                    {
                        "id": u.id,
                        "name": (u.full_name or u.username or str(u.id)),
                        "role": u.role.value,
                        "role_fa": _role_fa(u.role),
                        "org_id": u.org_id,
                        "county_id": u.county_id,
                    }
                    for u in recipients
                ],
            }
        )

    owner_name = None
    if r.current_owner_id:
        ou = db.get(User, r.current_owner_id)
        owner_name = (ou.full_name or ou.username) if ou else str(r.current_owner_id)

    payload = {
        "report": {
            "id": r.id,
            "kind": r.kind.value,
            "status": r.status.value,
            "org_id": r.org_id,
            "county_id": r.county_id,
            "created_by_id": r.created_by_id,
            "current_owner_id": r.current_owner_id,
            "current_owner_name": owner_name,
        },
        "user": {
            "id": user.id,
            "role": user.role.value,
            "role_fa": _role_fa(user.role),
            "org_id": user.org_id,
            "county_id": user.county_id,
        },
        "permissions": {
            "is_current_owner": r.current_owner_id == user.id,
            "can_edit": wf_can_edit(user, r),
            "can_delete": wf_can_delete(user, r),
            "allowed_actions": sorted(list(user_allowed)),
        },
        "actions": actions_payload,
    }

    return JSONResponse(payload)


@router.get("/{report_id}/sections/submission-options", response_class=HTMLResponse)
def submission_options(
    report_id: int,
    request: Request,
    form_id: int = Query(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    report = db.get(Report, report_id)
    require(report is not None, "گزارش یافت نشد", 404)
    require(can_view_report(user, report.org_id, report.county_id, report.current_owner_id))

    # When editing, allow options for:
    # - County report: same org/county (except secretariat view-only won't show this anyway)
    # - Provincial report: same org (or secretariat), province-scope submissions only
    if report.kind == ReportKind.COUNTY:
        require(report.county_id is not None, "گزارش شهرستان نامعتبر است", 400)
        if not is_secretariat(user):
            require(user.org_id == report.org_id and user.county_id == report.county_id, "دسترسی ندارید", 403)

        subs = (
            db.query(Submission)
            .filter(
                Submission.org_id == report.org_id,
                Submission.county_id == report.county_id,
                Submission.form_id == form_id,
            )
            .order_by(Submission.id.desc())
            .limit(200)
            .all()
        )

    else:  # PROVINCIAL
        if not is_secretariat(user):
            require(user.org_id == report.org_id, "دسترسی ندارید", 403)

        subs = (
            db.query(Submission)
            .join(FormTemplate, Submission.form_id == FormTemplate.id)
            .filter(
                Submission.org_id == report.org_id,
                Submission.county_id.is_(None),
                Submission.form_id == form_id,
                FormTemplate.scope == "province",
            )
            .order_by(Submission.id.desc())
            .limit(200)
            .all()
        )

    forms_map_available = {f.id: f.title for f in db.query(FormTemplate).filter(FormTemplate.id == form_id).all()}

    return request.app.state.templates.TemplateResponse(
        "reports/_submission_options.html",
        {"request": request, "subs": subs, "forms_map_available": forms_map_available},
    )


@router.get("/{report_id}/pdf")
def download_pdf(report_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    r = db.get(Report, report_id)
    require(r is not None, "گزارش یافت نشد", 404)
    require(can_view_report(user, r.org_id, r.county_id, r.current_owner_id))

    from app.utils.pdf_report import build_report_pdf
    from app.db.models.org import Org
    from app.db.models.county import County

    def _name(u: User | None) -> str | None:
        return (u.full_name or u.username) if u else None

    def _names_map(ids: list[int]) -> dict[int, str]:
        if not ids:
            return {}
        users = db.query(User).filter(User.id.in_(ids)).all()
        return {u.id: (u.full_name or u.username) for u in users}

    # compute fresh aggregation without mutating DB
    doc = load_doc(r.content_json)
    # Safety: if there are linked submissions but doc['sections'] is stale/empty,
    # synthesize sections for PDF output (do not write back to DB here).
    try:
        doc = _sync_sections(doc, _linked_submission_ids(db, r.id))
    except Exception:
        pass
    doc["aggregation"] = aggregate_content(db, r.id)

    attachments = (
        db.query(ReportAttachment)
        .filter(ReportAttachment.report_id == r.id)
        .order_by(ReportAttachment.id.desc())
        .all()
    )
    uploader_map = _names_map(list({a.uploaded_by_id for a in attachments}))

    logs = db.query(WorkflowLog).filter(WorkflowLog.report_id == r.id).order_by(WorkflowLog.id.asc()).all()
    actor_map = _names_map(list({l.actor_id for l in logs}))

    owner_name = _name(db.get(User, r.current_owner_id)) if r.current_owner_id else None
    created_by_name = _name(db.get(User, r.created_by_id)) if r.created_by_id else None

    org = db.get(Org, r.org_id) if getattr(r, "org_id", None) else None
    county = db.get(County, r.county_id) if getattr(r, "county_id", None) else None
    org_name = org.name if org else None
    county_name = county.name if county else None

    pdf_bytes = build_report_pdf(
        report=r,
        doc=doc,
        attachments=attachments,
        uploader_map=uploader_map,
        logs=logs,
        actor_map=actor_map,
        owner_name=owner_name,
        org_name=org_name,
        county_name=county_name,
        created_by_name=created_by_name,
    )

    filename = f"report_{r.id}.pdf"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)

@router.post("/{report_id}/attach", response_class=HTMLResponse)
def attach(
    request: Request,
    report_id: int,
    submission_id: int = Form(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    r = db.get(Report, report_id)
    require(r is not None, "گزارش یافت نشد", 404)
    require(can_view_report(user, r.org_id, r.county_id, r.current_owner_id))
    require(_can_edit(user, r), "در این وضعیت امکان اتصال وجود ندارد.")

    db.add(ReportSubmission(report_id=r.id, submission_id=submission_id))
    try:
        db.commit()
    except Exception:
        db.rollback()

    doc = load_doc(r.content_json)
    doc["aggregation"] = aggregate_content(db, r.id)
    doc = _sync_sections(doc, _linked_submission_ids(db, r.id))
    r.content_json = dump_doc(doc)
    db.commit()
    _audit(db, r.id, user.id, action="attach_submission", field="submission_id", before=None, after={"submission_id": submission_id})
    db.commit()

    attachments = db.query(ReportAttachment).filter(ReportAttachment.report_id == r.id).order_by(ReportAttachment.id.desc()).all()

    owner_name = None
    if r.current_owner_id:
        ou = db.get(User, r.current_owner_id)
        owner_name = (ou.full_name or ou.username) if ou else str(r.current_owner_id)

    uploader_ids = list({a.uploaded_by_id for a in attachments})
    uploader_users = {u.id: u for u in db.query(User).filter(User.id.in_(uploader_ids)).all()} if uploader_ids else {}
    uploader_map = {uid: (uploader_users[uid].full_name or uploader_users[uid].username) for uid in uploader_users}

    links = db.query(ReportSubmission).filter(ReportSubmission.report_id == r.id).all()
    sub_ids = [l.submission_id for l in links]
    attached_subs = db.query(Submission).filter(Submission.id.in_(sub_ids)).all() if sub_ids else []

    fids = list({s.form_id for s in attached_subs})
    forms_map_attached = {f.id: f.title for f in db.query(FormTemplate).filter(FormTemplate.id.in_(fids)).all()} if fids else {}


    return request.app.state.templates.TemplateResponse("reports/_attachments.html", {"request": request, "report": r,
            "doc": load_doc(r.content_json), "attached_subs": attached_subs,
            "forms_map_attached": forms_map_attached,
            "attachments": attachments,
            "owner_name": owner_name,
            "uploader_map": uploader_map, "user": user})

@router.post("/{report_id}/detach", response_class=HTMLResponse)
def detach(
    request: Request,
    report_id: int,
    submission_id: int = Form(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    r = db.get(Report, report_id)
    require(r is not None, "گزارش یافت نشد", 404)
    require(can_view_report(user, r.org_id, r.county_id, r.current_owner_id))
    require(_can_edit(user, r), "در این وضعیت امکان حذف اتصال وجود ندارد.")

    link = db.query(ReportSubmission).filter(ReportSubmission.report_id==r.id, ReportSubmission.submission_id==submission_id).first()
    if link:
        db.delete(link)
        db.commit()
        _audit(db, r.id, user.id, action="detach_submission", field="submission_id", before={"submission_id": submission_id}, after=None)
        db.commit()

    doc = load_doc(r.content_json)
    # remove from sections if exists
    if isinstance(doc.get("sections"), list):
        doc["sections"] = [s for s in doc["sections"] if s.get("submission_id") != submission_id]

    doc["aggregation"] = aggregate_content(db, r.id)
    doc = _sync_sections(doc, _linked_submission_ids(db, r.id))
    r.content_json = dump_doc(doc)
    db.commit()
    _audit(db, r.id, user.id, action="detach_submission", field="submission_id", before=None, after={"submission_id": submission_id})
    db.commit()

    attachments = db.query(ReportAttachment).filter(ReportAttachment.report_id == r.id).order_by(ReportAttachment.id.desc()).all()

    owner_name = None
    if r.current_owner_id:
        ou = db.get(User, r.current_owner_id)
        owner_name = (ou.full_name or ou.username) if ou else str(r.current_owner_id)

    uploader_ids = list({a.uploaded_by_id for a in attachments})
    uploader_users = {u.id: u for u in db.query(User).filter(User.id.in_(uploader_ids)).all()} if uploader_ids else {}
    uploader_map = {uid: (uploader_users[uid].full_name or uploader_users[uid].username) for uid in uploader_users}

    links = db.query(ReportSubmission).filter(ReportSubmission.report_id == r.id).all()
    sub_ids = [l.submission_id for l in links]
    attached_subs = db.query(Submission).filter(Submission.id.in_(sub_ids)).all() if sub_ids else []

    fids = list({s.form_id for s in attached_subs})
    forms_map_attached = {f.id: f.title for f in db.query(FormTemplate).filter(FormTemplate.id.in_(fids)).all()} if fids else {}


    return request.app.state.templates.TemplateResponse("reports/_attachments.html", {"request": request, "report": r,
            "doc": load_doc(r.content_json), "attached_subs": attached_subs,
            "forms_map_attached": forms_map_attached,
            "attachments": attachments,
            "owner_name": owner_name,
            "uploader_map": uploader_map, "user": user})




@router.get("/{report_id}/attachments/partial", response_class=HTMLResponse)
def attachments_partial(
    request: Request,
    report_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    r = db.get(Report, report_id)
    require(r is not None, "گزارش یافت نشد", 404)
    require(can_view_report(user, r.org_id, r.county_id, r.current_owner_id))

    attachments = (
        db.query(ReportAttachment)
        .filter(ReportAttachment.report_id == r.id)
        .order_by(ReportAttachment.id.desc())
        .all()
    )

    owner_name = None
    if r.current_owner_id:
        ou = db.get(User, r.current_owner_id)
        owner_name = (ou.full_name or ou.username) if ou else str(r.current_owner_id)

    uploader_ids = list({a.uploaded_by_id for a in attachments})
    uploader_users = (
        {u.id: u for u in db.query(User).filter(User.id.in_(uploader_ids)).all()} if uploader_ids else {}
    )
    uploader_map = {uid: (uploader_users[uid].full_name or uploader_users[uid].username) for uid in uploader_users}



    return request.app.state.templates.TemplateResponse(
        "reports/_attachments_files.html",
        {
            "request": request,
            "report": r,
            "doc": load_doc(r.content_json),
            "attachments": attachments,
            "owner_name": owner_name,
            "uploader_map": uploader_map,
            "user": user,
        },
    )

@router.post("/{report_id}/attachments/delete", response_class=HTMLResponse)
def delete_attachment(
    request: Request,
    report_id: int,
    attachment_id: int = Form(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    r = db.get(Report, report_id)
    require(r is not None, "گزارش یافت نشد", 404)
    require(can_view_report(user, r.org_id, r.county_id, r.current_owner_id))
    require(_can_edit(user, r), "در این وضعیت امکان حذف پیوست وجود ندارد.")
    att = db.get(ReportAttachment, attachment_id)
    if att and att.report_id == r.id:
        _audit(db, r.id, user.id, action="delete_attachment", field="attachment", before={"id": att.id, "filename": att.filename, "url": att.url}, after=None)
        # حذف فایل فیزیکی (best-effort)
        try:
            # در این پروژه مسیر در DB ذخیره نشده؛ از url فایل را حدس می‌زنیم.
            u = (att.url or "").strip()
            if u.startswith("/uploads/"):
                fname = u.split("/uploads/", 1)[1]
                fpath = os.path.join(UPLOAD_DIR, fname)
                if os.path.exists(fpath):
                    os.remove(fpath)
        except Exception:
            pass
        db.delete(att)
        db.commit()
        db.commit()
    attachments = db.query(ReportAttachment).filter(ReportAttachment.report_id == r.id).order_by(ReportAttachment.id.desc()).all()

    owner_name = None
    if r.current_owner_id:
        ou = db.get(User, r.current_owner_id)
        owner_name = (ou.full_name or ou.username) if ou else str(r.current_owner_id)

    uploader_ids = list({a.uploaded_by_id for a in attachments})
    uploader_users = {u.id: u for u in db.query(User).filter(User.id.in_(uploader_ids)).all()} if uploader_ids else {}
    uploader_map = {uid: (uploader_users[uid].full_name or uploader_users[uid].username) for uid in uploader_users}


    return request.app.state.templates.TemplateResponse(
        "reports/_attachments_files.html",
        {
            "request": request,
            "report": r,
            "doc": load_doc(r.content_json),
            "attachments": attachments,
            "owner_name": owner_name,
            "uploader_map": uploader_map,
            "user": user,
        },
    )
@router.post("/{report_id}/update_note")
def update_note(
    request: Request,
    report_id: int,
    # Front-end sends note_html (legacy name). Some clients may send intro_html.
    note_html: str = Form(""),
    intro_html: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    r = db.get(Report, report_id)
    require(r is not None, "گزارش یافت نشد", 404)
    require(can_view_report(user, r.org_id, r.county_id, r.current_owner_id))
    require(_can_edit(user, r), "در این وضعیت امکان ویرایش متن وجود ندارد.")
    before = load_doc(r.content_json)
    # store HTML in intro field
    doc = load_doc(r.content_json)
    payload = (note_html or "").strip() or (intro_html or "").strip()
    doc["intro_html"] = payload
    r.content_json = dump_doc(doc)
    _audit(db, r.id, user.id, action="update", field="intro_html", before=before.get("intro_html"), after=doc.get("intro_html"))
    db.commit()
    return {"ok": True}

@router.post("/{report_id}/update_conclusion")
def update_conclusion(
    request: Request,
    report_id: int,
    # Front-end usually sends conclusion_html, but accept a few aliases for robustness.
    conclusion_html: str = Form(""),
    note_html: str = Form(""),
    result_html: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    r = db.get(Report, report_id)
    require(r is not None, "گزارش یافت نشد", 404)
    require(can_view_report(user, r.org_id, r.county_id, r.current_owner_id))
    require(_can_edit(user, r), "در این وضعیت امکان ویرایش نتیجه‌گیری وجود ندارد.")
    before = load_doc(r.content_json)
    doc = load_doc(r.content_json)
    payload = (conclusion_html or "").strip() or (note_html or "").strip() or (result_html or "").strip()
    doc["conclusion_html"] = payload
    r.content_json = dump_doc(doc)
    _audit(db, r.id, user.id, action="update", field="conclusion_html", before=before.get("conclusion_html"), after=doc.get("conclusion_html"))
    db.commit()
    return {"ok": True}



@router.post("/{report_id}/update_meta")
def update_meta(
    request: Request,
    report_id: int,
    title: str = Form(""),
    subtitle: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    r = db.get(Report, report_id)
    require(r is not None, "گزارش یافت نشد", 404)
    require(can_view_report(user, r.org_id, r.county_id, r.current_owner_id))
    require(_can_edit(user, r), "در این وضعیت امکان ویرایش گزارش وجود ندارد.")

    before = load_doc(r.content_json)
    doc = load_doc(r.content_json)
    meta = doc.get("meta") if isinstance(doc, dict) else None
    if not isinstance(meta, dict):
        meta = {"title": "", "subtitle": ""}
    meta["title"] = (title or "").strip()
    meta["subtitle"] = (subtitle or "").strip()
    doc["meta"] = meta

    r.content_json = dump_doc(doc)
    _audit(db, r.id, user.id, action="update", field="meta", before=before.get("meta"), after=doc.get("meta"))
    db.commit()
    return {"ok": True}

@router.post("/{report_id}/sections/add", response_class=HTMLResponse)
def add_section(
    request: Request,
    report_id: int,
    submission_id: int = Form(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    r = db.get(Report, report_id)
    require(r is not None, "گزارش یافت نشد", 404)
    require(can_view_report(user, r.org_id, r.county_id, r.current_owner_id))
    require(_can_edit(user, r), "در این وضعیت امکان افزودن بخش وجود ندارد.")
    # Validate submission eligibility for this report
    sub = db.get(Submission, submission_id)
    require(sub is not None, "ثبت مورد نظر یافت نشد", 404)
    sub_form = db.get(FormTemplate, sub.form_id) if sub else None

    if r.kind == ReportKind.COUNTY:
        require(
            sub.org_id == r.org_id and sub.county_id == r.county_id,
            "این ثبت متعلق به این گزارش شهرستان نیست.",
            400,
        )
        if sub_form is not None:
            require(sub_form.scope != "province", "فرم‌های استانی فقط در گزارش استانی قابل استفاده هستند.", 400)
    else:  # PROVINCIAL
        require(
            sub.org_id == r.org_id and sub.county_id is None,
            "این ثبت متعلق به این گزارش استانی نیست.",
            400,
        )
        require(sub_form is not None and sub_form.scope == "province", "فقط ثبت‌های فرم استانی در گزارش استانی قابل استفاده هستند.", 400)

    # ensure attached
    db.add(ReportSubmission(report_id=r.id, submission_id=submission_id))
    try:
        db.commit()
    except Exception:
        db.rollback()
    before_doc = load_doc(r.content_json)
    doc = load_doc(r.content_json)
    # add section if not exists
    if not any(s.get("submission_id")==submission_id for s in doc.get("sections", [])):
        doc["sections"].append({"submission_id": submission_id, "description_html": ""})
    doc["aggregation"] = aggregate_content(db, r.id)
    r.content_json = dump_doc(doc)
    db.commit()
    _audit(db, r.id, user.id, action="add_section", field="sections", before=before_doc.get("sections"), after=doc.get("sections"), comment=f"submission_id={submission_id}")
    db.commit()
    # rebuild context for partial
    doc = load_doc(r.content_json)


    return request.app.state.templates.TemplateResponse("reports/_sections.html", {"request": request, "report": r, "doc": doc, "user": user, "can_edit": _can_edit(user, r)})

@router.post("/{report_id}/sections/update", response_class=HTMLResponse)
def update_section_desc(
    request: Request,
    report_id: int,
    submission_id: int = Form(...),
    description_html: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    r = db.get(Report, report_id)
    require(r is not None, "گزارش یافت نشد", 404)
    require(can_view_report(user, r.org_id, r.county_id, r.current_owner_id))
    require(_can_edit(user, r), "در این وضعیت امکان ویرایش توضیحات وجود ندارد.")
    before_doc = load_doc(r.content_json)
    doc = load_doc(r.content_json)
    for s in doc.get("sections", []):
        if s.get("submission_id")==submission_id:
            s["description_html"] = description_html or ""
            break
    r.content_json = dump_doc(doc)
    _audit(db, r.id, user.id, action="update_section", field="sections", before=before_doc.get("sections"), after=doc.get("sections"), comment=f"submission_id={submission_id}")
    db.commit()
    doc = load_doc(r.content_json)


    return request.app.state.templates.TemplateResponse("reports/_sections.html", {"request": request, "report": r, "doc": doc, "user": user, "can_edit": _can_edit(user, r)})


@router.post("/{report_id}/sections/remove", response_class=HTMLResponse)
def remove_section(
    request: Request,
    report_id: int,
    submission_id: int = Form(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    r = db.get(Report, report_id)
    require(r is not None, "گزارش یافت نشد", 404)
    require(can_view_report(user, r.org_id, r.county_id, r.current_owner_id))
    require(_can_edit(user, r), "در این وضعیت امکان حذف بخش وجود ندارد.")

    # delete link (detach)
    link = db.query(ReportSubmission).filter(ReportSubmission.report_id==r.id, ReportSubmission.submission_id==submission_id).first()
    if link:
        db.delete(link)
        db.commit()

    before_doc = load_doc(r.content_json)
    doc = load_doc(r.content_json)
    if isinstance(doc.get("sections"), list):
        doc["sections"] = [s for s in doc["sections"] if s.get("submission_id") != submission_id]
    doc["aggregation"] = aggregate_content(db, r.id)
    doc = _sync_sections(doc, _linked_submission_ids(db, r.id))
    r.content_json = dump_doc(doc)
    _audit(db, r.id, user.id, action="update", field="section_description", before=before_doc.get("sections"), after=doc.get("sections"), comment=f"submission_id={submission_id}")
    db.commit()
    _audit(db, r.id, user.id, action="remove_section", field="sections", before=before_doc.get("sections"), after=doc.get("sections"), comment=f"submission_id={submission_id}")
    db.commit()

    doc = load_doc(r.content_json)


    return request.app.state.templates.TemplateResponse("reports/_sections.html", {"request": request, "report": r, "doc": doc, "user": user, "can_edit": _can_edit(user, r)})

@router.post("/{report_id}/sections/reorder", response_class=HTMLResponse)
def reorder_sections(
    request: Request,
    report_id: int,
    order: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    r = db.get(Report, report_id)
    require(r is not None, "گزارش یافت نشد", 404)
    require(can_view_report(user, r.org_id, r.county_id, r.current_owner_id))
    require(_can_edit(user, r), "در این وضعیت امکان تغییر ترتیب وجود ندارد.")

    ids = []
    for part in (order or "").split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    ids = list(dict.fromkeys(ids))

    before_doc = load_doc(r.content_json)
    before_doc = load_doc(r.content_json)
    doc = load_doc(r.content_json)
    sections = doc.get("sections") if isinstance(doc.get("sections"), list) else []
    sec_map = {s.get("submission_id"): s for s in sections if isinstance(s, dict) and s.get("submission_id") is not None}

    new_sections = []
    for sid in ids:
        if sid in sec_map:
            new_sections.append(sec_map[sid])
    # append any remaining (keeps data)
    for s in sections:
        sid = s.get("submission_id") if isinstance(s, dict) else None
        if sid and sid not in ids:
            new_sections.append(s)

    doc["sections"] = new_sections
    r.content_json = dump_doc(doc)
    _audit(db, r.id, user.id, action="reorder_sections", field="sections", before=before_doc.get("sections"), after=doc.get("sections"), comment=f"order={order}")
    db.commit()

    doc = load_doc(r.content_json)


    return request.app.state.templates.TemplateResponse("reports/_sections.html", {"request": request, "report": r, "doc": doc, "user": user, "can_edit": _can_edit(user, r)})


# ---------------------------------------------------------------------
# Program monitoring sections (comparative program report)
# ---------------------------------------------------------------------

@router.post("/{report_id}/program_sections/add", response_class=HTMLResponse)
def add_program_section(
    request: Request,
    report_id: int,
    form_type_id: int = Form(...),
    mode: str = Form("province"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    r = db.get(Report, report_id)
    require(r is not None, "گزارش یافت نشد", 404)
    require(can_view_report(user, r.org_id, r.county_id, r.current_owner_id))
    require(_can_edit(user, r), "در این وضعیت امکان افزودن خروجی پایش برنامه وجود ندارد.")

    # County report => always county scope based on report county
    county_id = 0
    effective_mode = (mode or "").strip().lower() or "province"
    if r.kind == ReportKind.COUNTY:
        effective_mode = "county"
        county_id = int(r.county_id)
    else:
        # Provincial report: allow province OR aggregated counties
        require(effective_mode in ("province", "county_agg"), "حالت خروجی پایش برنامه معتبر نیست.", 400)

    # Auto-pick the latest available period for the selected scope.
    sel = resolve_latest_period(
        db=db,
        org_id=int(r.org_id),
        form_type_id=int(form_type_id),
        mode=effective_mode,
        county_id=int(county_id),
    )

    data = build_program_report(
        db=db,
        org_id=int(r.org_id),
        form_type_id=int(form_type_id),
        year=int(sel["year"]),
        period_type=str(sel["period_type"]),
        period_no=int(sel["period_no"]),
        mode=effective_mode,
        county_id=int(county_id),
    )

    # Render a snapshot HTML table and store it in report JSON.
    table_html = request.app.state.templates.get_template("reports/_program_table.html").render({"data": data})
    scope_label = data.get("scope_label") or ""
    title = f"{data.get('form_type', {}).get('title', 'پایش برنامه')} — {scope_label} — {data.get('current_label', '')}".strip(" —")

    before_doc = load_doc(r.content_json)
    doc = load_doc(r.content_json)
    sec_id = uuid.uuid4().hex
    doc.setdefault("program_sections", [])
    doc["program_sections"].append(
        {
            "id": sec_id,
            "title": title,
            "description_html": "",
            "table_html": table_html,
            "params": {
                "form_type_id": int(form_type_id),
                "mode": effective_mode,
                "county_id": int(county_id),
                "auto": True,
                "year": int(sel["year"]),
                "period_type": str(sel["period_type"]),
                "period_no": int(sel["period_no"]),
            },
        }
    )
    r.content_json = dump_doc(doc)
    _audit(db, r.id, user.id, action="add_program_section", field="program_sections", before=before_doc.get("program_sections"), after=doc.get("program_sections"), comment=title)
    db.commit()

    doc = load_doc(r.content_json)
    return request.app.state.templates.TemplateResponse("reports/_sections.html", {"request": request, "report": r, "doc": doc, "user": user, "can_edit": _can_edit(user, r)})


@router.post("/{report_id}/program_sections/update", response_class=HTMLResponse)
def update_program_section_desc(
    request: Request,
    report_id: int,
    section_id: str = Form(...),
    description_html: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    r = db.get(Report, report_id)
    require(r is not None, "گزارش یافت نشد", 404)
    require(can_view_report(user, r.org_id, r.county_id, r.current_owner_id))
    require(_can_edit(user, r), "در این وضعیت امکان ویرایش توضیحات وجود ندارد.")

    before_doc = load_doc(r.content_json)
    doc = load_doc(r.content_json)
    changed = False
    for s in doc.get("program_sections", []) or []:
        if isinstance(s, dict) and str(s.get("id")) == str(section_id):
            s["description_html"] = description_html or ""
            changed = True
            break
    require(changed, "بخش پایش برنامه یافت نشد.", 404)

    r.content_json = dump_doc(doc)
    _audit(db, r.id, user.id, action="update_program_section", field="program_sections", before=before_doc.get("program_sections"), after=doc.get("program_sections"), comment=f"id={section_id}")
    db.commit()
    doc = load_doc(r.content_json)
    return request.app.state.templates.TemplateResponse("reports/_sections.html", {"request": request, "report": r, "doc": doc, "user": user, "can_edit": _can_edit(user, r)})


@router.post("/{report_id}/program_sections/remove", response_class=HTMLResponse)
def remove_program_section(
    request: Request,
    report_id: int,
    section_id: str = Form(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    r = db.get(Report, report_id)
    require(r is not None, "گزارش یافت نشد", 404)
    require(can_view_report(user, r.org_id, r.county_id, r.current_owner_id))
    require(_can_edit(user, r), "در این وضعیت امکان حذف بخش وجود ندارد.")

    before_doc = load_doc(r.content_json)
    doc = load_doc(r.content_json)
    secs = doc.get("program_sections") if isinstance(doc.get("program_sections"), list) else []
    new_secs = [s for s in secs if not (isinstance(s, dict) and str(s.get("id")) == str(section_id))]
    require(len(new_secs) != len(secs), "بخش پایش برنامه یافت نشد.", 404)
    doc["program_sections"] = new_secs

    r.content_json = dump_doc(doc)
    _audit(db, r.id, user.id, action="remove_program_section", field="program_sections", before=before_doc.get("program_sections"), after=doc.get("program_sections"), comment=f"id={section_id}")
    db.commit()
    doc = load_doc(r.content_json)
    return request.app.state.templates.TemplateResponse("reports/_sections.html", {"request": request, "report": r, "doc": doc, "user": user, "can_edit": _can_edit(user, r)})


@router.post("/{report_id}/program_sections/regenerate", response_class=HTMLResponse)
def regenerate_program_section(
    request: Request,
    report_id: int,
    section_id: str = Form(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Rebuild table_html snapshot from current DB state (useful if submissions changed)."""
    r = db.get(Report, report_id)
    require(r is not None, "گزارش یافت نشد", 404)
    require(can_view_report(user, r.org_id, r.county_id, r.current_owner_id))
    require(_can_edit(user, r), "در این وضعیت امکان بازتولید وجود ندارد.")

    before_doc = load_doc(r.content_json)
    doc = load_doc(r.content_json)
    found = None
    for s in doc.get("program_sections", []) or []:
        if isinstance(s, dict) and str(s.get("id")) == str(section_id):
            found = s
            break
    require(found is not None, "بخش پایش برنامه یافت نشد.", 404)
    params = found.get("params") if isinstance(found, dict) else None
    require(isinstance(params, dict), "پارامترهای بخش پایش برنامه ناقص است.", 400)

    form_type_id = int(params.get("form_type_id"))
    mode = str(params.get("mode") or "province")
    county_id = int(params.get("county_id") or 0)

    # If this section was created with auto mode, pick the latest period again.
    if bool(params.get("auto")):
        sel = resolve_latest_period(
            db=db,
            org_id=int(r.org_id),
            form_type_id=form_type_id,
            mode=mode,
            county_id=county_id,
        )
        year = int(sel["year"])
        period_type = str(sel["period_type"])
        period_no = int(sel["period_no"])
        params.update({"year": year, "period_type": period_type, "period_no": period_no})
    else:
        year = int(params.get("year"))
        period_type = str(params.get("period_type"))
        period_no = int(params.get("period_no"))

    data = build_program_report(
        db=db,
        org_id=int(r.org_id),
        form_type_id=form_type_id,
        year=year,
        period_type=period_type,
        period_no=period_no,
        mode=mode,
        county_id=county_id,
    )

    table_html = request.app.state.templates.get_template("reports/_program_table.html").render({"data": data})
    scope_label = data.get("scope_label") or ""
    title = f"{data.get('form_type', {}).get('title', 'پایش برنامه')} — {scope_label} — {data.get('current_label', '')}".strip(" —")

    found["table_html"] = table_html
    found["title"] = title
    found["params"] = params

    r.content_json = dump_doc(doc)
    _audit(db, r.id, user.id, action="regenerate_program_section", field="program_sections", before=before_doc.get("program_sections"), after=doc.get("program_sections"), comment=f"id={section_id}")
    db.commit()

    doc = load_doc(r.content_json)
    return request.app.state.templates.TemplateResponse("reports/_sections.html", {"request": request, "report": r, "doc": doc, "user": user, "can_edit": _can_edit(user, r)})

@router.post("/{report_id}/upload")
async def upload_file(
    request: Request,
    report_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    r = db.get(Report, report_id)
    require(r is not None, "گزارش یافت نشد", 404)
    require(can_view_report(user, r.org_id, r.county_id, r.current_owner_id))
    require(_can_edit(user, r), "در این وضعیت امکان آپلود وجود ندارد.")

    form = await request.form()
    # Be tolerant to different field names from various clients/JS versions.
    up = form.get("file") or form.get("reportFile") or form.get("upload") or form.get("attachment")
    # Some clients may send multiple values under the same key.
    if isinstance(up, (list, tuple)):
        up = up[0] if up else None
    require(up is not None, "فایل ارسال نشد", 400)

    # NOTE: request.form() returns a Starlette UploadFile instance (not FastAPI's subclass).
    # Rely on duck-typing instead of isinstance() to avoid false negatives.
    if getattr(up, "filename", None) and hasattr(up, "read"):
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        ext = os.path.splitext(up.filename)[1]
        fname = f"report_{report_id}_{uuid.uuid4().hex}{ext}"
        dest = os.path.join(UPLOAD_DIR, fname)
        max_bytes = int(settings.MAX_UPLOAD_MB) * 1024 * 1024
        size = 0
        with open(dest, "wb") as out:
            while True:
                chunk = await up.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    try:
                        out.close()
                        os.remove(dest)
                    except Exception:
                        pass
                    require(False, f"فایل معتبر نیست (حداکثر {settings.MAX_UPLOAD_MB}MB).", 400)
                out.write(chunk)
        url = f"/uploads/{fname}"
        att = ReportAttachment(report_id=r.id, uploaded_by_id=user.id, filename=up.filename, url=url)
        db.add(att)
        db.commit()
        _audit(db, r.id, user.id, action="upload_attachment", field="attachment", before=None, after={"id": att.id, "filename": up.filename, "url": url})
        db.commit()
        return {"url": url, "name": up.filename, "id": att.id}
    require(False, "فایل معتبر نیست", 400)

@router.post("/{report_id}/action", response_class=HTMLResponse)
def do_action(
    request: Request,
    report_id: int,
    action: str = Form(...),
    recipient_id: str = Form(""),
    comment: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    r = db.get(Report, report_id)
    require(r is not None, "گزارش یافت نشد", 404)
    require(can_view_report(user, r.org_id, r.county_id, r.current_owner_id))
    require(_can_act(user, r, action), "این اقدام برای شما/این وضعیت مجاز نیست")

    recipients = _eligible_recipients(db, r, action)
    rid = int(recipient_id) if recipient_id.strip().isdigit() else None

    if action != "final_approve":
        require(recipients, "برای این اقدام گیرنده‌ای وجود ندارد.", 400)
        if rid is None:
            rid = recipients[0].id
        require(any(u.id == rid for u in recipients), "گیرنده انتخاب‌شده معتبر نیست.", 400)

    from_status = r.status
    to_status = get_transition(r.kind, r.status, action).to_status

    r.status = to_status
    if action == "final_approve":
        r.current_owner_id = None
    else:
        r.current_owner_id = rid

    db.add(WorkflowLog(
        report_id=r.id,
        actor_id=user.id,
        from_status=from_status.value,
        to_status=to_status.value,
        action=action,
        comment=comment or "",
    ))

    # Update aggregation
    doc = load_doc(r.content_json)
    doc["aggregation"] = aggregate_content(db, r.id)
    doc = _sync_sections(doc, _linked_submission_ids(db, r.id))
    r.content_json = dump_doc(doc)

    # Notifications (Unread -> badge)
    if action == "final_approve":
        notify(db, r.created_by_id, f"گزارش #{r.id} تأیید نهایی شد.", report_id=r.id, type="final")
    else:
        action_fa = {
            "submit_for_review": "ارسال برای بررسی",
            "approve": "ارسال مرحله بعد",
            "request_revision": "نیاز به اصلاح",
        }.get(action, action)
        notify(db, rid, f"گزارش #{r.id} برای شما ارسال شد ({action_fa}).", report_id=r.id, type="report")
        if action == "request_revision":
            # also notify actor (optional)
            notify(
                db,
                user.id,
                f"برای گزارش #{r.id} نیاز به اصلاح اعلام شد و برای اصلاح برگشت داده شد.",
                report_id=r.id,
                type="info",
            )

    db.commit()

    # Refresh actions box after transition
    actions2 = allowed_actions(user, r)
    action_recipients2 = {a: _eligible_recipients(db, r, a) for a in actions2}



    return request.app.state.templates.TemplateResponse(
        "reports/_actions.html",
        {"request": request, "report": r,
            "doc": load_doc(r.content_json), "actions": actions2, "action_recipients": action_recipients2, "user": user},
    )