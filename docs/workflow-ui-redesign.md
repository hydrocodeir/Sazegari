# Sazegari Workflow Platform Redesign

This redesign treats the dashboard as a workflow operations platform. UI elements now map to the local state machine in `app/core/workflow.py` and to Camunda artifacts in `camunda/`.

## Design System

- Typography: self-hosted Persian fonts remain the base, with a tighter enterprise scale for headings, body, labels, and tables.
- Palette: authority navy, workflow blue, approval green, warning amber, error red, slate neutrals.
- Layout: persistent RTL sidebar, sticky top bar, command palette, responsive mobile drawer, dense admin tables, mobile report cards.
- Components: KPI cards, workflow badges, SLA pills, saved-view tabs, decision panels, timelines, skeleton loaders, modal/drawer/toast states.
- Accessibility: visible focus states are inherited from form controls; icons are Lucide, not emoji; reduced-motion is respected in CSS.

## Role-Aware Navigation

Navigation is driven by `ROLE_NAV` in `app/core/workflow.py`.

- County expert: dashboard, my tasks, create report, reports, tracking, notifications.
- County manager: dashboard, my tasks, reports, tracking, notifications.
- Province expert: dashboard, my tasks, create report, reports, tracking, manager view, archive, notifications.
- Province manager: dashboard, my tasks, reports, tracking, manager view, archive, notifications.
- Secretariat user: dashboard, my tasks, reports, tracking, archive, notifications, audit logs.
- Secretariat admin: all workflow sections plus admin settings.

## Workflow Status Model

`WORKFLOW_STAGES` defines the UI/BPM catalog:

| Status | UI Label | BPMN Task | Form | SLA |
|---|---|---|---|---|
| `draft` | تهیه پیش‌نویس | `PrepareReportDraft` | `report-draft-form` | 72h |
| `county_manager_review` | بازبینی مدیر شهرستان | `ReviewByCountyManager` | `report-review-form` | 48h |
| `prov_expert_review` | بازبینی کارشناس استان | `ReviewByProvinceExpert` | `report-review-form` | 48h |
| `prov_manager_review` | بازبینی مدیر استان | `ReviewByProvinceManager` | `report-review-form` | 48h |
| `secretariat_user_review` | بازبینی کارشناس دبیرخانه | `ReviewBySecretariatExpert` | `report-review-form` | 72h |
| `secretariat_admin_review` | بازبینی مدیر دبیرخانه | `ReviewBySecretariatManager` | `report-review-form` | 72h |
| `needs_revision` | برگشت برای اصلاح | `ReviseReport` | `report-draft-form` | 48h |
| `final_approved` | تایید نهایی | `ArchiveApprovedReport` | service task | done |

## Screen Mapping

- Dashboard: shows queue counts, workflow status distribution, SLA risk, bottleneck cards, recent reports, and recent `WorkflowLog` entries.
- My Tasks / Reports: table and mobile cards show current workflow step, assignee, status tone, SLA and quick open action.
- Create Report: wizard preview maps to draft start form and `DetermineInitialRoute`.
- Report Detail: workflow workspace with header summary, current assignee, stage tracker, content builder, attachments, comments/notes, decision panel, timeline and audit trail.
- Manager Dashboard: province manager cockpit preserves county filters and program analytics while using the same KPI/status language.
- Admin/Audit: exposed through role-aware navigation for secretariat roles.

## Camunda Model

Artifacts:

- `camunda/report-approval-workflow.bpmn`
- `camunda/route-report-review.dmn`
- `camunda/report-draft-form.form`
- `camunda/report-review-form.form`
- `camunda/administrative-report-workflow.bpmn`
- `camunda/administrative-report-routing.dmn`
- `camunda/administrative-report-draft-form.form`
- `camunda/administrative-report-review-form.form`
- `camunda/administrative-report-archive-form.form`

The BPMN uses Camunda user tasks with `zeebe:userTask`, candidate groups matching application roles, and form IDs matching the `.form` files. The business rule task `DetermineInitialRoute` calls DMN decision `route_report_review` with `bindingType="deployment"` and stores the result in `routing`.

Important FEEL expressions:

- Initial county path: `=routing.nextStep = "county_manager"`
- County manager approve: `=decision = "approve"`
- Province expert approve: `=decision = "approve"`
- Province manager final county approval: `=reportKind = "county" and decision = "finalApprove"`
- Province manager approve provincial: `=reportKind = "provincial" and decision = "approve"`
- Secretariat manager final approval: `=decision = "finalApprove"`
- Review form recipient requirement: `=decision = "finalApprove" or recipientUserId != null`

## Implementation Notes

- The Python state machine remains the runtime source of truth for the existing app.
- The Camunda model is the target BPM architecture and deployable process package.
- The redesigned UI consumes the same status/action vocabulary as the BPMN/DMN/forms.
- Existing report editor, attachment upload, PDF preview, HTMX actions and audit logs are preserved.

## General Administrative BPM Model

The generalized target model covers the requested enterprise roles:

| Role | Main UI Surface | BPMN Task | Form |
|---|---|---|---|
| Expert | Create Report, My Tasks | `CreateReportDraft`, `ReviseReport` | `administrative-report-draft-form` |
| Supervisor | My Tasks, Report Detail | `ReviewBySupervisor` | `administrative-report-review-form` |
| Department Manager | Manager Dashboard, Report Detail | `ReviewByDepartmentManager` | `administrative-report-review-form` |
| Senior Manager | Manager Dashboard, Report Detail | `ReviewBySeniorManager` | `administrative-report-review-form` |
| Archive Officer | Archive/Search | `ArchiveReport` | `administrative-report-archive-form` |
| Admin | Admin Panel, Audit Logs | `AdminOverrideReview` | `administrative-report-review-form` |

The process starts with a draft, evaluates DMN routing, moves through supervisor and manager review, supports reject/return/escalate/finalize/admin override decisions, and ends with either archived or rejected. The archive task is explicit so the Archive/Search screen corresponds to a real human task and audit event.

## DMN and FEEL Contract

`administrative-report-routing.dmn` decides the next role, SLA hours, escalation flag, and priority band from these variables:

- `priority`
- `riskScore`
- `revisionCount`
- `slaBreached`

The BPMN gateways use FEEL expressions such as `=decision = "approve"`, `=decision = "return"`, and `=decision = "escalate" or routing.escalate = true`. The review form uses FEEL validation to require revision instructions for returns and escalation reasons for escalation/admin override.

## Data Model Proposal

The current SQLAlchemy models can support the redesign without a disruptive migration. A future Camunda-backed migration should add:

- `process_instance_key`, `task_key`, `business_key`
- `priority`, `risk_score`, `sla_due_at`, `sla_breached`
- `archived_at`, `archived_by_id`, `archive_reference`
- `rejected_at`, `rejected_by_id`, `escalation_reason`
- `version`, `related_report_id`, `last_activity_at`

These fields would let the redesigned dashboard query workflow queues, SLA risk, archive history, and audit timelines directly from persisted BPM state.

## Implementation Plan

1. Preserve the existing FastAPI/Jinja/HTMX business logic as the active runtime.
2. Add workflow metadata so UI badges, navigation, steps, forms, roles, and actions share one vocabulary.
3. Replace the visual shell with an RTL-ready sidebar, top bar, command palette, notifications, and role-aware navigation.
4. Redesign dashboard, inbox/report list, report detail workspace, decision panel, manager dashboard, archive/search, audit, and admin entry points.
5. Add Camunda BPMN, DMN, FEEL, and Forms artifacts for both the current app-specific flow and the generalized administrative role model.
6. Validate Python templates, CSS build, BPMN lint, DMN lint, and form JSON parsing before deployment.
