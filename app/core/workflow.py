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
        recipient_roles=(Role.ORG_COUNTY_EXPERT,),
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
