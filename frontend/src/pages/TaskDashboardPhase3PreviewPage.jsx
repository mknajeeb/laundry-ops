/**
 * Local visual preview for Phase 3 Task Dashboard (no auth / no API).
 * Route: /dev/task-dashboard-phase3-preview
 * Not linked from production nav.
 */
import { useMemo, useState } from "react";
import { Box, Button, Stack, Typography } from "@mui/material";
import TaskAssignmentCard from "../components/tasks/TaskAssignmentCard";
import TaskRecordDialog from "../components/tasks/TaskRecordDialog";
import TaskManualCompletionDialog from "../components/tasks/TaskManualCompletionDialog";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";
import { formatDashboardDate } from "../components/tasks/taskDashboardFormat";

const MOCK_SHARED = {
  assignment_key: "g:2026-10-30:floor-washer",
  role: "agroup_floor_washer",
  role_label: "Floor & Washer",
  execution_mode: "shared",
  shared: true,
  timing_label: "Anytime",
  assigned_employees: ["Maria Perez", "Rocio"],
  overall_status: "in_progress",
  completion_status: "in_progress",
  verification_status: "not_required",
  verification_eligible: false,
  checklist_complete: false,
  checklist_status: "not_started",
  employees_finished: 1,
  employees_assigned: 2,
  checklist_done: 0,
  checklist_required: 2,
  has_manual_completion: false,
  shared_checklist_items: [
    { task_code: "floor_cleaning", task_name: "Floor Cleaning", required: true, status: "pending" },
    { task_code: "washer_cleaning", task_name: "Washer Cleaning", required: true, status: "pending" },
  ],
  contributions: [
    {
      employee_id: 11,
      employee_name: "Maria Perez",
      status: "completed",
      participation_status: "finished",
      activity: {
        id: 77,
        started_at: "2026-10-30 09:00:00",
        ended_at: "2026-10-30 09:35:00",
        duration_seconds: 2100,
        completion_source: "pin",
        business_date: "2026-10-30",
      },
      can_manual_complete: true,
    },
    {
      employee_id: 12,
      employee_name: "Rocio",
      status: "pending",
      participation_status: "not_started",
      activity: null,
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

function Metric({ label, value, accent }) {
  return (
    <Box
      sx={{
        p: 1.25,
        minWidth: 100,
        flex: "1 1 100px",
        borderRadius: 2,
        bgcolor: "#fff",
        border: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
        borderLeft: `3px solid ${accent || VEEWASH_DASHBOARD.primaryBlue}`,
        boxShadow: VEEWASH_DASHBOARD.cardShadow,
      }}
    >
      <Typography variant="caption" color="text.secondary" display="block">
        {label}
      </Typography>
      <Typography variant="h5" sx={{ fontWeight: 800, color: VEEWASH_DASHBOARD.wfCharcoal }}>
        {value}
      </Typography>
    </Box>
  );
}

function DashboardShell({ title, readOnly, hideLabor, children, extraActions }) {
  return (
    <Box sx={{ bgcolor: VEEWASH_DASHBOARD.pageBackground, minHeight: "100vh", pb: 4 }}>
      <Box sx={{ maxWidth: 1100, mx: "auto", px: { xs: 1.5, sm: 2 }, pt: 2 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="flex-end" sx={{ mb: 2 }}>
          <Box>
            <Typography variant="h5" sx={{ fontWeight: 900, color: VEEWASH_DASHBOARD.wfCharcoal }}>
              {title}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {formatDashboardDate("2026-10-30")}
              {readOnly ? " · Read-only" : ""}
            </Typography>
          </Box>
          {extraActions}
        </Stack>
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 1.5 }}>
          <Metric label="Assigned" value={2} />
          <Metric label="Started" value={2} accent={VEEWASH_DASHBOARD.primaryBlue} />
          <Metric label="Completed" value={readOnly ? 1 : 1} accent={VEEWASH_DASHBOARD.teal} />
          <Metric label="Verified" value={0} accent={VEEWASH_DASHBOARD.tealDark} />
          <Metric label="Pending verification" value={1} accent={VEEWASH_DASHBOARD.pending} />
          {!hideLabor ? (
            <Metric label="Time spent" value="1h 8m" accent={VEEWASH_DASHBOARD.wfCharcoal} />
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
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 2 }}>
        Floor &amp; Washer is In Progress and is not included in Completed or Pending verification.
        Those totals are Lint Cleaning only. Phase 3 preview · view={view}
      </Typography>
    </DashboardShell>
  );
}
