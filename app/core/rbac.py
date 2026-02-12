from __future__ import annotations

from fastapi import HTTPException

from app.db.models.user import User, Role

# -------------------------------------------------------------------
# Permission matrix (Source of truth: policy.png)
# -------------------------------------------------------------------

class Perm:
    # Forms
    FORMS_SUBMIT = "forms.submit"
    FORMS_TEMPLATE_CREATE = "forms.template.create"
    FORMS_TEMPLATE_DELETE = "forms.template.delete"
    FORMS_TEMPLATE_UPDATE = "forms.template.update"

    FORMS_VIEW_ALL = "forms.view_all"
    FORMS_VIEW_COUNTY = "forms.view_county"
    FORMS_VIEW_ORG = "forms.view_org"
    FORMS_VIEW_PROVINCE_SCOPE = "forms.view_province_scope"

    # Master data
    MASTERDATA_MANAGE = "masterdata.manage"

    # Reports
    REPORTS_CREATE = "reports.create"
    REPORTS_DELETE = "reports.delete"
    REPORTS_VIEW_ALL = "reports.view_all"
    REPORTS_VIEW_COUNTY = "reports.view_county"
    REPORTS_VIEW_ORG = "reports.view_org"
    REPORTS_VIEW_QUEUE_OWN = "reports.view_queue_own"

    # Workflow
    WORKFLOW_APPROVE = "workflow.approve"
    WORKFLOW_EDIT_CONTENT = "workflow.edit_content"
    WORKFLOW_FINAL_APPROVE = "workflow.final_approve"
    WORKFLOW_REQUEST_REVISION = "workflow.request_revision"
    WORKFLOW_SUBMIT_FOR_REVIEW = "workflow.submit_for_review"


ALL_PERMISSIONS: list[str] = [
    # forms
    Perm.FORMS_SUBMIT,
    Perm.FORMS_TEMPLATE_CREATE,
    Perm.FORMS_TEMPLATE_DELETE,
    Perm.FORMS_TEMPLATE_UPDATE,
    Perm.FORMS_VIEW_ALL,
    Perm.FORMS_VIEW_COUNTY,
    Perm.FORMS_VIEW_ORG,
    Perm.FORMS_VIEW_PROVINCE_SCOPE,
    # masterdata
    Perm.MASTERDATA_MANAGE,
    # reports
    Perm.REPORTS_CREATE,
    Perm.REPORTS_DELETE,
    Perm.REPORTS_VIEW_ALL,
    Perm.REPORTS_VIEW_COUNTY,
    Perm.REPORTS_VIEW_ORG,
    Perm.REPORTS_VIEW_QUEUE_OWN,
    # workflow
    Perm.WORKFLOW_APPROVE,
    Perm.WORKFLOW_EDIT_CONTENT,
    Perm.WORKFLOW_FINAL_APPROVE,
    Perm.WORKFLOW_REQUEST_REVISION,
    Perm.WORKFLOW_SUBMIT_FOR_REVIEW,
]

ROLE_PERMISSIONS: dict[Role, set[str]] = {
    Role.ORG_COUNTY_MANAGER: {
        Perm.FORMS_SUBMIT,
        Perm.FORMS_VIEW_COUNTY,
        Perm.FORMS_VIEW_ORG,
        Perm.REPORTS_VIEW_COUNTY,
        Perm.REPORTS_VIEW_QUEUE_OWN,
        Perm.WORKFLOW_APPROVE,
        Perm.WORKFLOW_EDIT_CONTENT,
        Perm.WORKFLOW_REQUEST_REVISION,
        Perm.WORKFLOW_SUBMIT_FOR_REVIEW,
    },
    Role.ORG_COUNTY_EXPERT: {
        Perm.FORMS_SUBMIT,
        Perm.FORMS_VIEW_COUNTY,
        Perm.FORMS_VIEW_ORG,
        Perm.REPORTS_CREATE,
        Perm.REPORTS_DELETE,
        Perm.REPORTS_VIEW_COUNTY,
        Perm.REPORTS_VIEW_QUEUE_OWN,
        Perm.WORKFLOW_EDIT_CONTENT,
        Perm.WORKFLOW_SUBMIT_FOR_REVIEW,
    },
    Role.ORG_PROV_MANAGER: {
        Perm.FORMS_VIEW_ORG,
        Perm.FORMS_VIEW_PROVINCE_SCOPE,
        Perm.REPORTS_VIEW_ORG,
        Perm.REPORTS_VIEW_QUEUE_OWN,
        Perm.WORKFLOW_APPROVE,
        Perm.WORKFLOW_EDIT_CONTENT,
        Perm.WORKFLOW_FINAL_APPROVE,
        Perm.WORKFLOW_REQUEST_REVISION,
        Perm.WORKFLOW_SUBMIT_FOR_REVIEW,
    },
    Role.ORG_PROV_EXPERT: {
        Perm.FORMS_SUBMIT,
        Perm.FORMS_TEMPLATE_CREATE,
        Perm.FORMS_TEMPLATE_DELETE,
        Perm.FORMS_TEMPLATE_UPDATE,
        Perm.FORMS_VIEW_ORG,
        Perm.FORMS_VIEW_PROVINCE_SCOPE,
        Perm.REPORTS_CREATE,
        Perm.REPORTS_DELETE,
        Perm.REPORTS_VIEW_ORG,
        Perm.REPORTS_VIEW_QUEUE_OWN,
        Perm.WORKFLOW_APPROVE,
        Perm.WORKFLOW_EDIT_CONTENT,
        Perm.WORKFLOW_REQUEST_REVISION,
        Perm.WORKFLOW_SUBMIT_FOR_REVIEW,
    },
    Role.SECRETARIAT_ADMIN: {
        Perm.FORMS_TEMPLATE_CREATE,
        Perm.FORMS_TEMPLATE_DELETE,
        Perm.FORMS_TEMPLATE_UPDATE,
        Perm.FORMS_VIEW_ALL,
        Perm.FORMS_VIEW_COUNTY,
        Perm.FORMS_VIEW_ORG,
        Perm.FORMS_VIEW_PROVINCE_SCOPE,
        Perm.MASTERDATA_MANAGE,
        Perm.REPORTS_VIEW_ALL,
        Perm.REPORTS_VIEW_COUNTY,
        Perm.REPORTS_VIEW_ORG,
        Perm.REPORTS_VIEW_QUEUE_OWN,
        Perm.WORKFLOW_EDIT_CONTENT,
        Perm.WORKFLOW_FINAL_APPROVE,
        Perm.WORKFLOW_REQUEST_REVISION,
        Perm.WORKFLOW_SUBMIT_FOR_REVIEW,
    },
    Role.SECRETARIAT_USER: {
        Perm.FORMS_TEMPLATE_CREATE,
        Perm.FORMS_TEMPLATE_DELETE,
        Perm.FORMS_TEMPLATE_UPDATE,
        Perm.FORMS_VIEW_ALL,
        Perm.FORMS_VIEW_COUNTY,
        Perm.FORMS_VIEW_ORG,
        Perm.FORMS_VIEW_PROVINCE_SCOPE,
        Perm.REPORTS_VIEW_ALL,
        Perm.REPORTS_VIEW_COUNTY,
        Perm.REPORTS_VIEW_ORG,
        Perm.REPORTS_VIEW_QUEUE_OWN,
        Perm.WORKFLOW_APPROVE,
        Perm.WORKFLOW_EDIT_CONTENT,
        Perm.WORKFLOW_REQUEST_REVISION,
        Perm.WORKFLOW_SUBMIT_FOR_REVIEW,
    },
}

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def require(condition: bool, msg: str = "دسترسی غیرمجاز", status_code: int = 403) -> None:
    if not condition:
        raise HTTPException(status_code=status_code, detail=msg)

def has_perm(user: User, perm: str) -> bool:
    perms = ROLE_PERMISSIONS.get(user.role, set())
    return perm in perms

def is_secretariat(user: User) -> bool:
    return user.role in (Role.SECRETARIAT_ADMIN, Role.SECRETARIAT_USER)

def is_provincial(user: User) -> bool:
    return user.role in (Role.ORG_PROV_EXPERT, Role.ORG_PROV_MANAGER)

def is_county(user: User) -> bool:
    return user.role in (Role.ORG_COUNTY_EXPERT, Role.ORG_COUNTY_MANAGER)

# ---- common "can_*" helpers used across routers ----

def can_manage_masterdata(user: User) -> bool:
    return has_perm(user, Perm.MASTERDATA_MANAGE)

def can_submit_data(user: User) -> bool:
    return has_perm(user, Perm.FORMS_SUBMIT)

def can_create_form(user: User) -> bool:
    return has_perm(user, Perm.FORMS_TEMPLATE_CREATE) or has_perm(user, Perm.FORMS_TEMPLATE_UPDATE)

def can_view_forms(user: User) -> bool:
    # For simplicity, any of view_* implies access to /forms listing
    return any(has_perm(user, p) for p in (
        Perm.FORMS_VIEW_ALL, Perm.FORMS_VIEW_ORG, Perm.FORMS_VIEW_COUNTY, Perm.FORMS_VIEW_PROVINCE_SCOPE
    ))

def can_create_report(user: User) -> bool:
    return has_perm(user, Perm.REPORTS_CREATE)

def can_delete_report(user: User) -> bool:
    return has_perm(user, Perm.REPORTS_DELETE)

def can_view_reports_all(user: User) -> bool:
    return has_perm(user, Perm.REPORTS_VIEW_ALL)

def can_view_reports_org(user: User) -> bool:
    return has_perm(user, Perm.REPORTS_VIEW_ORG)

def can_view_reports_county(user: User) -> bool:
    return has_perm(user, Perm.REPORTS_VIEW_COUNTY)

def can_view_reports_queue_own(user: User) -> bool:
    return has_perm(user, Perm.REPORTS_VIEW_QUEUE_OWN)


# -------------------------------------------------------------------
# Backwards-compatible helpers (used by existing routers)
# -------------------------------------------------------------------

def can_view_report(
    user: User,
    org_id: int | None,
    county_id: int | None,
    current_owner_id: int | None = None,
) -> bool:
    """Report-level visibility check.

    Signature is kept to match existing router usage.
    Rules (policy.png):
      - reports.view_all: can see any report
      - reports.view_org: can see reports of own org
      - reports.view_county: can see reports of own county
      - reports.view_queue_own: can see reports currently assigned to user
    """

    if has_perm(user, Perm.REPORTS_VIEW_ALL):
        return True

    if org_id is not None and has_perm(user, Perm.REPORTS_VIEW_ORG) and user.org_id == org_id:
        return True

    if (
        county_id is not None
        and has_perm(user, Perm.REPORTS_VIEW_COUNTY)
        and getattr(user, "county_id", None) == county_id
    ):
        return True

    if (
        current_owner_id is not None
        and has_perm(user, Perm.REPORTS_VIEW_QUEUE_OWN)
        and user.id == current_owner_id
    ):
        return True

    return False
