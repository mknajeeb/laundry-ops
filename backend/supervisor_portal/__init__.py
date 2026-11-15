"""Supervisor portal (Track 2).

Isolated from the Operations Planner (Track 1). This package does not write
shift sessions, planned schedules, breaks, payroll, or task-assignment rows.

Contracts it reuses:
- Employee identity: ``users.id`` plus the existing Rinse user map.
- Folding output and auto-approval: ``management_wf_folder_performance`` and
  ``rinse_performance_auto_approve``. Auto-approval is not modified here.
- Session exclude / published rate: ``rinse_performance_approvals``.
- Task verification: read-only ``cleaning_task_activity.dashboard_summary``.
- Reporting dates: existing ET ``shift_date_et`` / ``business_today``.

Scoring weights are stored as drafts. The engine refuses to activate a formula.
"""
