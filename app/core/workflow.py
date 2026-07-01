"""Workflow / State Machine for reports.

This module centralizes *all* workflow rules in one place.

Goals:
1) No scattered if/else chains across routers and templates
2) Rules are data-driven, testable, and easy to extend
3) One source of truth for:
   - allowed actions per (kind, status, role)
   - state transitions
   - recipient (next owner) eligibility
   - content editability per state
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from sqlalchemy.orm import Session

from app.db.models.report import Report, ReportKind, ReportStatus
from app.db.models.user import Role, User


Action = str  # "submit_for_review" | "approve" | "request_revision" | "final_approve"


@dataclass(frozen=True, slots=True)
class Transition:
    """One transition edge in the state machine."""

    kind: ReportKind
    from_status: ReportStatus
    action: Action
    to_status: ReportStatus
    # If action requires choosing a recipient, this defines eligible roles.
    # For "final_approve" it must be empty.
    recipient_roles: tuple[Role, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkflowStage:
    """UI/BPM catalog entry for one report workflow state."""

    status: ReportStatus
    label: str
    actor_roles: tuple[Role, ...]
    sla_hours: int
    tone: str
    camunda_task_id: str
    camunda_form_id: str = ""


WORKFLOW_STAGES: tuple[WorkflowStage, ...] = (
    WorkflowStage(
        status=ReportStatus.DRAFT,
        label="تهیه پیش‌نویس",
        actor_roles=(Role.ORG_COUNTY_EXPERT, Role.ORG_PROV_EXPERT),
        sla_hours=72,
        tone="draft",
        camunda_task_id="PrepareReportDraft",
        camunda_form_id="report-draft-form",
    ),
    WorkflowStage(
        status=ReportStatus.COUNTY_MANAGER_REVIEW,
        label="بازبینی مدیر شهرستان",
        actor_roles=(Role.ORG_COUNTY_MANAGER,),
        sla_hours=48,
        tone="review",
        camunda_task_id="ReviewByCountyManager",
        camunda_form_id="report-review-form",
    ),
    WorkflowStage(
        status=ReportStatus.PROV_EXPERT_REVIEW,
        label="بازبینی کارشناس استان",
        actor_roles=(Role.ORG_PROV_EXPERT,),
        sla_hours=48,
        tone="review",
        camunda_task_id="ReviewByProvinceExpert",
        camunda_form_id="report-review-form",
    ),
    WorkflowStage(
        status=ReportStatus.PROV_MANAGER_REVIEW,
        label="بازبینی مدیر استان",
        actor_roles=(Role.ORG_PROV_MANAGER,),
        sla_hours=48,
        tone="review",
        camunda_task_id="ReviewByProvinceManager",
        camunda_form_id="report-review-form",
    ),
    WorkflowStage(
        status=ReportStatus.SECRETARIAT_USER_REVIEW,
        label="بازبینی کارشناس دبیرخانه",
        actor_roles=(Role.SECRETARIAT_USER,),
        sla_hours=72,
        tone="review",
        camunda_task_id="ReviewBySecretariatExpert",
        camunda_form_id="report-review-form",
    ),
    WorkflowStage(
        status=ReportStatus.SECRETARIAT_ADMIN_REVIEW,
        label="بازبینی مدیر دبیرخانه",
        actor_roles=(Role.SECRETARIAT_ADMIN,),
        sla_hours=72,
        tone="review",
        camunda_task_id="ReviewBySecretariatManager",
        camunda_form_id="report-review-form",
    ),
    WorkflowStage(
        status=ReportStatus.NEEDS_REVISION,
        label="برگشت برای اصلاح",
        actor_roles=(
            Role.ORG_COUNTY_EXPERT,
            Role.ORG_COUNTY_MANAGER,
            Role.ORG_PROV_EXPERT,
            Role.ORG_PROV_MANAGER,
            Role.SECRETARIAT_USER,
            Role.SECRETARIAT_ADMIN,
        ),
        sla_hours=48,
        tone="returned",
        camunda_task_id="ReviseReport",
        camunda_form_id="report-draft-form",
    ),
    WorkflowStage(
        status=ReportStatus.FINAL_APPROVED,
        label="تایید نهایی",
        actor_roles=(),
        sla_hours=0,
        tone="approved",
        camunda_task_id="ArchiveApprovedReport",
    ),
)


STATUS_TONES: dict[ReportStatus, str] = {
    stage.status: stage.tone for stage in WORKFLOW_STAGES
}
STATUS_TONES[ReportStatus.SECRETARIAT_REVIEW] = "review"


ACTION_META: dict[Action, dict[str, str]] = {
    "submit_for_review": {
        "label": "ارسال برای بررسی",
        "tone": "primary",
        "icon": "send",
        "dmn": "approve",
    },
    "approve": {
        "label": "تایید و ارسال مرحله بعد",
        "tone": "success",
        "icon": "check-circle-2",
        "dmn": "approve",
    },
    "request_revision": {
        "label": "برگشت برای اصلاح",
        "tone": "warning",
        "icon": "undo-2",
        "dmn": "return",
    },
    "final_approve": {
        "label": "تایید نهایی",
        "tone": "success",
        "icon": "badge-check",
        "dmn": "finalApprove",
    },
}


ROLE_NAV: dict[Role, tuple[str, ...]] = {
    Role.ORG_COUNTY_EXPERT: ("dashboard", "my_tasks", "create_report", "reports", "tracking", "notifications"),
    Role.ORG_COUNTY_MANAGER: ("dashboard", "my_tasks", "reports", "tracking", "notifications"),
    Role.ORG_PROV_EXPERT: ("dashboard", "my_tasks", "create_report", "reports", "tracking", "manager", "archive", "notifications"),
    Role.ORG_PROV_MANAGER: ("dashboard", "my_tasks", "reports", "tracking", "manager", "archive", "notifications"),
    Role.SECRETARIAT_USER: ("dashboard", "my_tasks", "reports", "tracking", "archive", "notifications", "audit"),
    Role.SECRETARIAT_ADMIN: (
        "dashboard",
        "my_tasks",
        "reports",
        "tracking",
        "manager",
        "archive",
        "notifications",
        "audit",
        "admin",
    ),
}


def workflow_stage(status: ReportStatus) -> WorkflowStage | None:
    """Return UI/BPM stage metadata for a report status."""
    if status == ReportStatus.SECRETARIAT_REVIEW:
        status = ReportStatus.SECRETARIAT_ADMIN_REVIEW
    for stage in WORKFLOW_STAGES:
        if stage.status == status:
            return stage
    return None


def status_tone(status: ReportStatus | str) -> str:
    if isinstance(status, str):
        try:
            status = ReportStatus(status)
        except ValueError:
            return "review"
    return STATUS_TONES.get(status, "review")


def workflow_path(kind: ReportKind) -> tuple[ReportStatus, ...]:
    """Canonical happy path used by steppers, reports, and BPMN docs."""
    if kind == ReportKind.COUNTY:
        return (
            ReportStatus.DRAFT,
            ReportStatus.COUNTY_MANAGER_REVIEW,
            ReportStatus.PROV_EXPERT_REVIEW,
            ReportStatus.PROV_MANAGER_REVIEW,
            ReportStatus.FINAL_APPROVED,
        )
    return (
        ReportStatus.DRAFT,
        ReportStatus.PROV_MANAGER_REVIEW,
        ReportStatus.SECRETARIAT_USER_REVIEW,
        ReportStatus.SECRETARIAT_ADMIN_REVIEW,
        ReportStatus.FINAL_APPROVED,
    )


def workflow_progress(kind: ReportKind, status: ReportStatus) -> dict[str, object]:
    """Return a serializable progress model for report detail screens."""
    path = workflow_path(kind)
    normalized_status = ReportStatus.SECRETARIAT_ADMIN_REVIEW if status == ReportStatus.SECRETARIAT_REVIEW else status
    if normalized_status == ReportStatus.NEEDS_REVISION:
        current_index = max(0, len(path) - 4)
    else:
        current_index = path.index(normalized_status) if normalized_status in path else 0
    total = max(1, len(path) - 1)
    return {
        "current_index": current_index,
        "percent": int(round((current_index / total) * 100)),
        "stages": [
            {
                "status": item.value,
                "label": (workflow_stage(item).label if workflow_stage(item) else item.value),
                "tone": status_tone(item),
                "state": "done" if i < current_index else ("active" if i == current_index else "upcoming"),
            }
            for i, item in enumerate(path)
        ],
    }


def nav_items_for_role(role: Role) -> tuple[str, ...]:
    return ROLE_NAV.get(role, ("dashboard", "reports", "notifications"))


# ---- Helpers to query recipients ----


def _users_by_role(db: Session, role: Role, report: Report) -> list[User]:
    q = db.query(User).filter(User.role == role)

    # Secretariat roles are global.
    if role in (Role.SECRETARIAT_USER, Role.SECRETARIAT_ADMIN):
        return q.all()

    # Org-scoped roles
    q = q.filter(User.org_id == report.org_id)

    # County-scoped roles
    if role in (Role.ORG_COUNTY_EXPERT, Role.ORG_COUNTY_MANAGER):
        # For county report, county_id always exists.
        if report.county_id is None:
            # Report is provincial; county experts/managers in same org are allowed.
            return q.all()
        return q.filter(User.county_id == report.county_id).all()

    return q.all()


def get_recipients(db: Session, report: Report, action: Action) -> list[User]:
    """Eligible recipients for a given action.

    This is fully driven by the transition configuration.
    """
    t = get_transition(report.kind, report.status, action)
    if not t.recipient_roles:
        return []
    recipients: list[User] = []
    for role in t.recipient_roles:
        recipients.extend(_users_by_role(db, role, report))
    # De-dup (same user could match multiple role clauses in future)
    seen: set[int] = set()
    out: list[User] = []
    for u in recipients:
        if u.id not in seen:
            seen.add(u.id)
            out.append(u)
    return out


# ---- State machine configuration ----


TRANSITIONS: tuple[Transition, ...] = (
    # --- County report workflow ---
    Transition(
        kind=ReportKind.COUNTY,
        from_status=ReportStatus.DRAFT,
        action="submit_for_review",
        to_status=ReportStatus.COUNTY_MANAGER_REVIEW,
        recipient_roles=(Role.ORG_COUNTY_MANAGER,),
    ),
    Transition(
        kind=ReportKind.COUNTY,
        from_status=ReportStatus.NEEDS_REVISION,
        action="submit_for_review",
        to_status=ReportStatus.COUNTY_MANAGER_REVIEW,
        recipient_roles=(Role.ORG_COUNTY_MANAGER,),
    ),
    # approve path: county_manager -> prov_expert -> prov_manager -> final
    Transition(
        kind=ReportKind.COUNTY,
        from_status=ReportStatus.COUNTY_MANAGER_REVIEW,
        action="approve",
        to_status=ReportStatus.PROV_EXPERT_REVIEW,
        recipient_roles=(Role.ORG_PROV_EXPERT,),
    ),
    Transition(
        kind=ReportKind.COUNTY,
        from_status=ReportStatus.PROV_EXPERT_REVIEW,
        action="approve",
        to_status=ReportStatus.PROV_MANAGER_REVIEW,
        recipient_roles=(Role.ORG_PROV_MANAGER,),
    ),
    Transition(
        kind=ReportKind.COUNTY,
        from_status=ReportStatus.PROV_MANAGER_REVIEW,
        action="final_approve",
        to_status=ReportStatus.FINAL_APPROVED,
        recipient_roles=(),
    ),
    # request revision (back edges)
    Transition(
        kind=ReportKind.COUNTY,
        from_status=ReportStatus.COUNTY_MANAGER_REVIEW,
        action="request_revision",
        to_status=ReportStatus.NEEDS_REVISION,
        recipient_roles=(Role.ORG_COUNTY_EXPERT,),
    ),
    Transition(
        kind=ReportKind.COUNTY,
        from_status=ReportStatus.PROV_EXPERT_REVIEW,
        action="request_revision",
        to_status=ReportStatus.COUNTY_MANAGER_REVIEW,
        recipient_roles=(Role.ORG_COUNTY_MANAGER,),
    ),
    Transition(
        kind=ReportKind.COUNTY,
        from_status=ReportStatus.PROV_MANAGER_REVIEW,
        action="request_revision",
        to_status=ReportStatus.PROV_EXPERT_REVIEW,
        recipient_roles=(Role.ORG_PROV_EXPERT,),
    ),

    # --- Provincial report workflow ---
    Transition(
        kind=ReportKind.PROVINCIAL,
        from_status=ReportStatus.DRAFT,
        action="submit_for_review",
        to_status=ReportStatus.PROV_MANAGER_REVIEW,
        recipient_roles=(Role.ORG_PROV_MANAGER,),
    ),
    Transition(
        kind=ReportKind.PROVINCIAL,
        from_status=ReportStatus.NEEDS_REVISION,
        action="submit_for_review",
        to_status=ReportStatus.PROV_MANAGER_REVIEW,
        recipient_roles=(Role.ORG_PROV_MANAGER,),
    ),
    # approve path: prov_manager -> secretariat_user -> secretariat_admin -> final
    Transition(
        kind=ReportKind.PROVINCIAL,
        from_status=ReportStatus.PROV_MANAGER_REVIEW,
        action="approve",
        to_status=ReportStatus.SECRETARIAT_USER_REVIEW,
        recipient_roles=(Role.SECRETARIAT_USER,),
    ),
    Transition(
        kind=ReportKind.PROVINCIAL,
        from_status=ReportStatus.SECRETARIAT_USER_REVIEW,
        action="approve",
        to_status=ReportStatus.SECRETARIAT_ADMIN_REVIEW,
        recipient_roles=(Role.SECRETARIAT_ADMIN,),
    ),
    Transition(
        kind=ReportKind.PROVINCIAL,
        from_status=ReportStatus.SECRETARIAT_ADMIN_REVIEW,
        action="final_approve",
        to_status=ReportStatus.FINAL_APPROVED,
        recipient_roles=(),
    ),
    # request revision (per your spec)
    Transition(
        kind=ReportKind.PROVINCIAL,
        from_status=ReportStatus.PROV_MANAGER_REVIEW,
        action="request_revision",
        to_status=ReportStatus.NEEDS_REVISION,
        # Provincial report must return only to provincial expert (drafter), not to county experts.
        recipient_roles=(Role.ORG_PROV_EXPERT,),
    ),
    Transition(
        kind=ReportKind.PROVINCIAL,
        from_status=ReportStatus.SECRETARIAT_USER_REVIEW,
        action="request_revision",
        to_status=ReportStatus.PROV_MANAGER_REVIEW,
        recipient_roles=(Role.ORG_PROV_MANAGER,),
    ),
    Transition(
        kind=ReportKind.PROVINCIAL,
        from_status=ReportStatus.SECRETARIAT_ADMIN_REVIEW,
        action="request_revision",
        to_status=ReportStatus.SECRETARIAT_USER_REVIEW,
        recipient_roles=(Role.SECRETARIAT_USER,),
    ),
)


def get_transition(kind: ReportKind, status: ReportStatus, action: Action) -> Transition:
    for t in TRANSITIONS:
        if t.kind == kind and t.from_status == status and t.action == action:
            return t
    # Legacy support: previous SECRETARIAT_REVIEW behaves like SECRETARIAT_ADMIN_REVIEW
    if kind == ReportKind.PROVINCIAL and status == ReportStatus.SECRETARIAT_REVIEW:
        if action == "final_approve":
            return Transition(
                kind=kind,
                from_status=status,
                action=action,
                to_status=ReportStatus.FINAL_APPROVED,
                recipient_roles=(),
            )
        if action == "request_revision":
            return Transition(
                kind=kind,
                from_status=status,
                action=action,
                to_status=ReportStatus.PROV_MANAGER_REVIEW,
                recipient_roles=(Role.ORG_PROV_MANAGER,),
            )
    raise KeyError("unknown transition")


def allowed_actions_for_status(kind: ReportKind, status: ReportStatus) -> tuple[Action, ...]:
    actions: list[Action] = []
    for t in TRANSITIONS:
        if t.kind == kind and t.from_status == status:
            if t.action not in actions:
                actions.append(t.action)
    # legacy
    if kind == ReportKind.PROVINCIAL and status == ReportStatus.SECRETARIAT_REVIEW:
        actions.extend(["final_approve", "request_revision"])
    return tuple(actions)


def allowed_actions(user: User, report: Report) -> list[Action]:
    """Actions the *current owner* can execute."""
    if report.status == ReportStatus.FINAL_APPROVED:
        return []
    if report.current_owner_id != user.id:
        return []

    candidates = allowed_actions_for_status(report.kind, report.status)

    # Role gate: user must be a valid actor for this state.
    # This keeps the config simple while still safe.
    role_allowed: dict[tuple[ReportKind, ReportStatus], tuple[Role, ...]] = {
        # county
        (ReportKind.COUNTY, ReportStatus.DRAFT): (Role.ORG_COUNTY_EXPERT,),
        (ReportKind.COUNTY, ReportStatus.NEEDS_REVISION): (Role.ORG_COUNTY_EXPERT, Role.ORG_COUNTY_MANAGER, Role.ORG_PROV_EXPERT, Role.ORG_PROV_MANAGER),
        (ReportKind.COUNTY, ReportStatus.COUNTY_MANAGER_REVIEW): (Role.ORG_COUNTY_MANAGER,),
        (ReportKind.COUNTY, ReportStatus.PROV_EXPERT_REVIEW): (Role.ORG_PROV_EXPERT,),
        (ReportKind.COUNTY, ReportStatus.PROV_MANAGER_REVIEW): (Role.ORG_PROV_MANAGER,),
        # provincial
        (ReportKind.PROVINCIAL, ReportStatus.DRAFT): (Role.ORG_PROV_EXPERT,),
        (ReportKind.PROVINCIAL, ReportStatus.NEEDS_REVISION): (Role.ORG_COUNTY_EXPERT, Role.ORG_PROV_MANAGER, Role.SECRETARIAT_USER, Role.SECRETARIAT_ADMIN, Role.ORG_PROV_EXPERT),
        (ReportKind.PROVINCIAL, ReportStatus.PROV_MANAGER_REVIEW): (Role.ORG_PROV_MANAGER,),
        (ReportKind.PROVINCIAL, ReportStatus.SECRETARIAT_USER_REVIEW): (Role.SECRETARIAT_USER,),
        (ReportKind.PROVINCIAL, ReportStatus.SECRETARIAT_ADMIN_REVIEW): (Role.SECRETARIAT_ADMIN,),
        (ReportKind.PROVINCIAL, ReportStatus.SECRETARIAT_REVIEW): (Role.SECRETARIAT_ADMIN,),
    }

    allowed_roles = role_allowed.get((report.kind, report.status), ())
    if allowed_roles and user.role not in allowed_roles:
        return []
    return list(candidates)


def can_edit(user: User, report: Report) -> bool:
    """Whether user can edit report content *right now*.

Rule: Only current owner can edit; editability depends on workflow state.
"""
    if report.current_owner_id != user.id:
        return False
    if report.status == ReportStatus.FINAL_APPROVED:
        return False

    editable: dict[tuple[ReportKind, ReportStatus], tuple[Role, ...]] = {
        # county
        (ReportKind.COUNTY, ReportStatus.DRAFT): (Role.ORG_COUNTY_EXPERT,),
        (ReportKind.COUNTY, ReportStatus.NEEDS_REVISION): (Role.ORG_COUNTY_EXPERT, Role.ORG_COUNTY_MANAGER, Role.ORG_PROV_EXPERT, Role.ORG_PROV_MANAGER),
        (ReportKind.COUNTY, ReportStatus.COUNTY_MANAGER_REVIEW): (Role.ORG_COUNTY_MANAGER,),
        (ReportKind.COUNTY, ReportStatus.PROV_EXPERT_REVIEW): (Role.ORG_PROV_EXPERT,),
        (ReportKind.COUNTY, ReportStatus.PROV_MANAGER_REVIEW): (Role.ORG_PROV_MANAGER,),
        # provincial
        (ReportKind.PROVINCIAL, ReportStatus.DRAFT): (Role.ORG_PROV_EXPERT,),
        (ReportKind.PROVINCIAL, ReportStatus.NEEDS_REVISION): (Role.ORG_COUNTY_EXPERT, Role.ORG_PROV_MANAGER, Role.SECRETARIAT_USER, Role.SECRETARIAT_ADMIN, Role.ORG_PROV_EXPERT),
        (ReportKind.PROVINCIAL, ReportStatus.PROV_MANAGER_REVIEW): (Role.ORG_PROV_MANAGER,),
        (ReportKind.PROVINCIAL, ReportStatus.SECRETARIAT_USER_REVIEW): (Role.SECRETARIAT_USER,),
        (ReportKind.PROVINCIAL, ReportStatus.SECRETARIAT_ADMIN_REVIEW): (Role.SECRETARIAT_ADMIN,),
        (ReportKind.PROVINCIAL, ReportStatus.SECRETARIAT_REVIEW): (Role.SECRETARIAT_ADMIN,),
    }
    allowed_roles = editable.get((report.kind, report.status), ())
    return (not allowed_roles) or (user.role in allowed_roles)


def can_delete(user: User, report: Report) -> bool:
    """Delete rule: experts can delete reports only in their own level."""
    if report.status == ReportStatus.FINAL_APPROVED:
        return False
    if user.org_id != report.org_id:
        return False
    if report.kind == ReportKind.COUNTY:
        return (
            user.role == Role.ORG_COUNTY_EXPERT
            and report.county_id is not None
            and user.county_id == report.county_id
            and report.current_owner_id == user.id
        )
    # provincial
    return user.role == Role.ORG_PROV_EXPERT and report.current_owner_id == user.id
