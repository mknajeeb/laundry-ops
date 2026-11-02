/**
 * Local visual preview for Phase 3 Task Dashboard (no auth / no API).
 * Route: /dev/task-dashboard-phase3-preview
 * Not linked from production nav.
 */
import { useMemo, useState } from "react";
import { Box, Button, Stack, Tooltip, Typography } from "@mui/material";
import TaskAssignmentCard from "../components/tasks/TaskAssignmentCard";
import TaskRecordDialog from "../components/tasks/TaskRecordDialog";
import TaskManualCompletionDialog from "../components/tasks/TaskManualCompletionDialog";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";
import { formatDashboardDate } from "../components/tasks/taskDashboardFormat";
import { dashboardHeadlineMetrics } from "../components/tasks/taskDashboardLabels";
import ActivityRemarks from "../components/tasks/ActivityRemarks";
import InstructionHint from "../components/tasks/InstructionHint";
import TaskVerificationReviewCard from "../components/tasks/TaskVerificationReviewCard";
import TaskDashboardMonthlyChart from "../components/tasks/TaskDashboardMonthlyChart";

const MOCK_SHARED = {
  assignment_key: "g:2026-10-30:floor-washer",
  role: "agroup_washer_cleaning",
  role_label: "Washer Cleaning",
  execution_mode: "shared",
  shared: true,
  timing_label: "Anytime",
  assigned_employees: ["Gabriela", "Yesenia"],
  instructions: "Shared washer activity. Check residue, then wipe the machines. One checklist. Each person keeps their own timer.",
  checklist_sections: [
    {
      section_label: "Machines",
      status: "pending_verification",
      status_label: "Pending Verification",
      pending_activity_ids: [107, 108],
    },
  ],
  remarks: [
    {
      id: 1,
      author_name: "Gabriela",
      author_role: "employee",
      body: "Residue in washer 4.",
      created_at_label: "2026-11-01 09:20:00 ET",
    },
    {
      id: 2,
      author_name: "Yesenia",
      author_role: "employee",
      task_code: "washer_cleaning",
      body: "Wiped washer 4 after the residue check.",
      created_at_label: "2026-11-01 09:26:00 ET",
    },
  ],
  remark_count: 2,
  overall_status: "pending_verification",
  completion_status: "completed",
  verification_status: "waiting",
  verification_eligible: true,
  checklist_complete: true,
  checklist_status: "completed",
  employees_finished: 2,
  employees_assigned: 2,
  checklist_done: 2,
  checklist_required: 2,
  has_manual_completion: false,
  shared_checklist_items: [
    {
      task_code: "custom_check_washer_residue",
      task_name: "Check Washer Residue",
      instructions: "Look inside each washer for leftover soap, lint, or debris before the next load.",
      section_label: "Machines",
      required: true,
      status: "completed",
      completed_by_name: "Gabriela",
      completed_at: "2026-11-01 09:24:58",
    },
    {
      task_code: "washer_cleaning",
      task_name: "Wipe down washers",
      instructions: "Wipe washer doors, gaskets, tops, and detergent compartments.",
      section_label: "Machines",
      required: true,
      status: "completed",
      completed_by_name: "Yesenia",
      completed_at: "2026-11-01 09:25:20",
    },
  ],
  contributions: [
    {
      employee_id: 56,
      employee_name: "Gabriela",
      status: "completed",
      participation_status: "finished",
      activity: {
        id: 105,
        started_at: "2026-11-01 09:00:11",
        ended_at: "2026-11-01 09:25:38",
        duration_seconds: 1527,
        completion_source: "pin",
        business_date: "2026-11-01",
        employee_remark: { text: "Residue was light.", author_user_id: 56, at: "2026-11-01 09:25:38" },
      },
    },
    {
      employee_id: 36,
      employee_name: "Yesenia",
      status: "completed",
      participation_status: "finished",
      group_items: [
        { task_code: "floor_cleaning", task_name: "Floor Brooming", display_status: "pending_verification" },
      ],
      activity: {
        id: 106,
        started_at: "2026-11-01 09:01:14",
        ended_at: "2026-11-01 09:25:41",
        duration_seconds: 1466,
        completion_source: "pin",
        business_date: "2026-11-01",
        employee_remark: { text: "Floor is dry.", author_user_id: 36, at: "2026-11-01 09:25:41" },
      },
    },
  ],
};

const MOCK_SOLO = {
  assignment_key: "solo:lint",
  role: "lint_cleaning",
  role_label: "Lint Cleaning",
  execution_mode: "individual",
  shared: false,
  timing_label: "9:00 AM",
  assigned_employees: ["Francis"],
  completion_status: "completed",
  verification_status: "waiting",
  has_manual_completion: false,
  contributions: [
    {
      employee_name: "Francis",
      status: "pending_approval",
      completion_status: "completed",
      verification_status: "waiting",
      activity: {
        id: 90,
        started_at: "2026-10-30 09:00:00",
        ended_at: "2026-10-30 09:32:00",
        duration_seconds: 1920,
        completion_source: "pin",
        business_date: "2026-10-30",
        status: "pending_approval",
      },
      can_approve: true,
    },
  ],
};

function Metric({ label, value, hint }) {
  return (
    <Tooltip title={hint || ""} enterTouchDelay={0} arrow>
      <Box
        sx={{
          px: 1,
          py: 0.6,
          minWidth: 88,
          borderRadius: 1.5,
          bgcolor: "#fff",
          border: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
        }}
      >
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", lineHeight: 1.1 }}>
          {label}
        </Typography>
        <Typography sx={{ fontWeight: 800, fontSize: "1.05rem", lineHeight: 1.2 }}>{value}</Typography>
      </Box>
    </Tooltip>
  );
}

const REVIEW_CARD = {
  assignment_key: "g:floor",
  role_label: "Washer Cleaning",
  instructions: "Shared washer activity. One checklist for the assignment.",
  checklist_sections: [
    {
      section_label: "Machines",
      status_label: "Pending Verification",
      pending_activity_ids: [107, 108],
    },
  ],
  remarks: [
    {
      id: 1,
      author_name: "Gabriela",
      author_role: "employee",
      body: "Residue in washer 4.",
      created_at_label: "2026-11-01 09:20:00 ET",
    },
  ],
  timing_label: "9:00 AM",
  assigned_employees: ["Gabriela", "Yesenia"],
  overall_label: "Pending Verification",
  overall_status: "pending_verification",
  can_approve_all: true,
  pending_activity_ids: [97, 98, 99, 100],
  participation: [
    {
      employee_id: 56,
      employee_name: "Gabriela",
      participation_status: "finished",
      participation_label: "Finished",
      started_at: "2026-11-01 09:00:11",
      finished_at: "2026-11-01 09:25:38",
    },
    {
      employee_id: 36,
      employee_name: "Yesenia",
      participation_status: "finished",
      participation_label: "Finished",
      started_at: "2026-11-01 09:01:14",
      finished_at: "2026-11-01 09:25:41",
    },
  ],
  checklist: [
    {
      task_code: "custom_check_washer_residue",
      task_label: "Check Washer Residue",
      checked_off: true,
      records: [
        {
          activity_id: 107,
          employee_name: "Gabriela",
          checked_off_at: "2026-11-01 09:24:58",
          status: "pending_approval",
        },
      ],
    },
    {
      task_code: "washer_cleaning",
      task_label: "Wipe down washers",
      section_label: "Machines",
      instructions: "Wipe washer doors, gaskets, tops, and detergent compartments.",
      checked_off: true,
      records: [
        {
          activity_id: 108,
          employee_name: "Yesenia",
          checked_off_at: "2026-11-01 09:25:20",
          status: "pending_approval",
        },
      ],
    },
  ],
};

function DashboardShell({ title, readOnly, hideLabor, children, extraActions, rows = [MOCK_SHARED, MOCK_SOLO] }) {
  const metrics = dashboardHeadlineMetrics(rows);
  return (
    <Box sx={{ bgcolor: VEEWASH_DASHBOARD.pageBackground, minHeight: "100vh", pb: 4 }}>
      <Box sx={{ maxWidth: 1100, mx: "auto", px: { xs: 1.5, sm: 2 }, pt: 2 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="flex-end" sx={{ mb: 2 }}>
          <Box>
            <Typography variant="h5" sx={{ fontWeight: 900, color: VEEWASH_DASHBOARD.wfCharcoal }}>
              {title}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {formatDashboardDate("2026-11-01")}
              {readOnly ? " · Read-only" : ""}
            </Typography>
          </Box>
          {extraActions}
        </Stack>
        <Typography variant="caption" sx={{ fontWeight: 700, color: "text.secondary" }}>
          Activities
        </Typography>
        <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap sx={{ mb: 0.75 }}>
          <Metric label="Assigned" value={metrics.activitiesAssigned} hint="Shared assignments count once." />
          <Metric label="Completed" value={metrics.completedActivities} hint="Finished assignments. Includes pending verification and verified." />
          <Metric label="Pending Verification" value={metrics.pendingVerification} hint="Finished and waiting for a supervisor." />
          <Metric label="Verified" value={metrics.verifiedActivities} hint="Supervisor approved. Also included in Completed." />
          <Metric label="Overdue" value={metrics.overdue} hint="Not finished after the planned time." />
        </Stack>
        <Typography variant="caption" sx={{ fontWeight: 700, color: "text.secondary" }}>
          Employee participation
        </Typography>
        <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap sx={{ mb: 1.25 }}>
          <Metric label="Assigned" value={metrics.employeesAssigned} hint="Each employee on each assignment." />
          <Metric label="Started" value={metrics.employeesStarted} hint="Participations that have started." />
          <Metric label="Finished" value={metrics.employeesFinished} hint="Participations that have finished." />
          {!hideLabor ? (
            <Metric label="Total Time" value={metrics.totalTimeLabel} hint="Sum of each employee's participation time." />
          ) : null}
        </Stack>
        {children}
      </Box>
    </Box>
  );
}

export default function TaskDashboardPhase3PreviewPage() {
  const params = useMemo(() => new URLSearchParams(window.location.search), []);
  const view = params.get("view") || "management";
  const [expanded, setExpanded] = useState(view === "expanded" || view === "edit" || view === "void" || view === "add");
  const [editOpen, setEditOpen] = useState(view === "edit");
  const [voidOpen, setVoidOpen] = useState(view === "void");
  const [addOpen, setAddOpen] = useState(view === "add");

  const readOnly = view === "rinse";
  const hideLabor = view === "rinse";

  if (view === "edit" || view === "void") {
    return (
      <DashboardShell title="Task Dashboard" readOnly={false}>
        <TaskAssignmentCard
          row={MOCK_SOLO}
          expanded={false}
          onToggle={() => {}}
          readOnly={false}
          hideLabor={false}
          canApprove
          canManual
        />
        <TaskRecordDialog
          open={editOpen || voidOpen}
          mode={voidOpen ? "void" : "edit"}
          activity={MOCK_SOLO.contributions[0].activity}
          assignmentLabel="Lint Cleaning"
          employeeName="Francis"
          onClose={() => {
            setEditOpen(false);
            setVoidOpen(false);
          }}
          onSubmit={async () => {}}
          busy={false}
        />
      </DashboardShell>
    );
  }

  if (view === "pin") {
    return (
      <Box sx={{ bgcolor: "#f4f7fb", minHeight: "100vh", p: 1.5 }}>
        <Box sx={{ maxWidth: 390, mx: "auto", bgcolor: "#fff", borderRadius: 2, p: 2 }}>
          <Stack direction="row" alignItems="center" spacing={0.5}>
            <Typography sx={{ fontWeight: 900, color: "#0f2744" }}>Washer Cleaning</Typography>
            <InstructionHint text={MOCK_SHARED.instructions} />
          </Stack>
          <Typography variant="body2" color="text.secondary">Shared Activity · your timer · one checklist</Typography>
          <Typography variant="body2">Check Washer Residue · Gabriela · 9:24 AM</Typography>
          <Typography variant="body2" sx={{ mb: 1.5 }}>Wipe down washers · Yesenia · 9:25 AM</Typography>
          <ActivityRemarks remarks={MOCK_SHARED.remarks} items={MOCK_SHARED.shared_checklist_items} onAdd={async () => {}} />
          <Button fullWidth variant="contained" color="success" sx={{ fontWeight: 800, textTransform: "none" }}>
            Finish My Participation
          </Button>
        </Box>
      </Box>
    );
  }

  if (view === "print") {
    return (
      <Box className="print-preview" sx={{ bgcolor: "#fff", minHeight: "100vh", p: 2, maxWidth: 800, mx: "auto" }}>
        <style>{`
          .print-preview button, .print-preview .MuiIconButton-root { display: none !important; }
        `}</style>
        <Typography sx={{ fontWeight: 900 }}>VeeWash Task Dashboard</Typography>
        <Typography variant="body2" sx={{ mb: 1 }}>2026-11-01 – 2026-11-01 ET · All · daily</Typography>
        <DashboardShell title="Task Dashboard" readOnly hideLabor={false} rows={[MOCK_SHARED]}>
          <TaskDashboardMonthlyChart
            data={{
              buckets: [
                { label: "Nov 1", chart: { not_started: 0, in_progress: 0, pending_verification: 1, verified: 0, overdue: 0, needs_correction: 0 } },
              ],
            }}
          />
          <TaskAssignmentCard
            row={MOCK_SHARED}
            expanded
            onToggle={() => {}}
            readOnly
            hideLabor={false}
            canApprove={false}
            canManual={false}
          />
        </DashboardShell>
      </Box>
    );
  }

  if (view === "review") {
    return (
      <Box sx={{ bgcolor: "#f4f7fb", minHeight: "100vh", p: 1.5 }}>
        <Box sx={{ maxWidth: 420, mx: "auto" }}>
          <Typography sx={{ fontWeight: 900, mb: 1 }}>Task Review</Typography>
          <Typography sx={{ fontWeight: 800, mb: 1 }}>Pending approvals (1)</Typography>
          <TaskVerificationReviewCard card={REVIEW_CARD} />
        </Box>
      </Box>
    );
  }

  if (view === "add") {
    return (
      <DashboardShell title="Task Dashboard" readOnly={false}>
        <TaskAssignmentCard
          row={MOCK_SOLO}
          expanded={false}
          onToggle={() => {}}
          readOnly={false}
          hideLabor={false}
          canApprove
          canManual
        />
        <TaskManualCompletionDialog
          open={addOpen}
          mode="manual"
          assignment={MOCK_SOLO}
          contribution={MOCK_SOLO.contributions[0]}
          onClose={() => setAddOpen(false)}
          onSubmit={async () => {}}
          busy={false}
        />
      </DashboardShell>
    );
  }

  return (
    <DashboardShell
      title="Task Dashboard"
      readOnly={readOnly}
      hideLabor={hideLabor}
      extraActions={
        !readOnly ? (
          <Button
            size="small"
            variant="contained"
            sx={{
              bgcolor: VEEWASH_DASHBOARD.primaryBlue,
              "&:hover": { bgcolor: VEEWASH_DASHBOARD.primaryBlueDark },
            }}
          >
            Manage tasks
          </Button>
        ) : null
      }
    >
      <TaskDashboardMonthlyChart
        data={{
          buckets: [
            { label: "Nov 1", chart: { not_started: 0, in_progress: 0, pending_verification: 2, verified: 0, overdue: 0, needs_correction: 0 } },
          ],
        }}
      />
      <Stack spacing={1.25} data-testid="assignment-list">
        <TaskAssignmentCard
          row={MOCK_SHARED}
          expanded={expanded || view === "expanded"}
          onToggle={() => setExpanded((v) => !v)}
          readOnly={readOnly}
          hideLabor={hideLabor}
          canApprove={!readOnly}
          canManual={!readOnly}
          onEditRecord={!readOnly ? () => setEditOpen(true) : undefined}
          onVoidRecord={!readOnly ? () => setVoidOpen(true) : undefined}
          onManual={!readOnly ? () => setAddOpen(true) : undefined}
        />
        <TaskAssignmentCard
          row={MOCK_SOLO}
          expanded={false}
          onToggle={() => {}}
          readOnly={readOnly}
          hideLabor={hideLabor}
          canApprove={!readOnly}
          canManual={!readOnly}
        />
      </Stack>
    </DashboardShell>
  );
}
