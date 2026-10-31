import {
  Box,
  Button,
  Collapse,
  IconButton,
  Stack,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";
import {
  CompletionBadge,
  VerificationBadge,
  ChecklistBadge,
  OverallBadge,
  TaskStatusBadge,
} from "./TaskStatusBadge";
import {
  formatDashboardDateTime,
  formatDashboardTime,
  participationTimeLine,
} from "./taskDashboardFormat";
import {
  friendlyStatusLabel,
  participationLabel,
  participationStatusOf,
  participationSummary,
} from "./taskDashboardLabels";

function formatDuration(seconds) {
  if (seconds == null) return null;
  const sec = Math.max(0, Number(seconds) || 0);
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

/**
 * One primary card per assignment (shared groups counted once).
 */
export default function TaskAssignmentCard({
  row,
  expanded,
  onToggle,
  readOnly,
  hideLabor,
  canApprove,
  canManual,
  onApprove,
  onReject,
  onManual,
  onEditRecord,
  onVoidRecord,
  rejectId,
  reason,
  setReason,
  onConfirmReject,
  onCancelReject,
}) {
  const employees = (row.assigned_employees || []).join(", ") || "Unassigned";
  const modeLabel =
    row.execution_mode === "shared" ? "Shared" : row.shared ? "Group" : null;
  const checklistItems = row.shared_checklist_items || [];
  const showParticipation = Boolean(row.shared || row.execution_mode === "shared" || row.overall_status);
  const requiredItems = checklistItems.filter((item) => item.required !== false);
  const checklistDone = requiredItems.filter((item) =>
    ["completed", "approved", "verified"].includes(String(item.status || "").toLowerCase())
  ).length;
  const finishedCount = (row.contributions || []).filter(
    (c) => participationStatusOf(c) === "finished"
  ).length;
  const summary = participationSummary({
    finished: row.employees_finished ?? finishedCount,
    assigned: row.employees_assigned ?? (row.contributions || []).length,
    checklistDone: row.checklist_done ?? checklistDone,
    checklistRequired: row.checklist_required ?? requiredItems.length,
  });
  const verifyLocked = row.verification_eligible === false;

  return (
    <Box
      sx={{
        border: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
        borderRadius: 2,
        bgcolor: "#fff",
        boxShadow: VEEWASH_DASHBOARD.cardShadow,
        overflow: "hidden",
      }}
    >
      <Stack
        direction={{ xs: "column", sm: "row" }}
        alignItems={{ xs: "stretch", sm: "center" }}
        justifyContent="space-between"
        spacing={1}
        sx={{ px: 1.5, py: 1.25, cursor: "pointer" }}
        onClick={onToggle}
      >
        <Box sx={{ minWidth: 0, flex: 1 }}>
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <Typography
              variant="subtitle1"
              sx={{ fontWeight: 800, color: VEEWASH_DASHBOARD.wfCharcoal, lineHeight: 1.2 }}
            >
              {row.role_label || row.role}
            </Typography>
            {modeLabel ? (
              <TaskStatusBadge
                label={modeLabel}
                sx={{ bgcolor: VEEWASH_DASHBOARD.snapshotBg, color: VEEWASH_DASHBOARD.primaryBlueDark }}
              />
            ) : null}
            {row.has_manual_completion && !readOnly ? (
              <TaskStatusBadge label="Manual entry" />
            ) : null}
          </Stack>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.35 }}>
            {employees}
            {row.timing_label ? ` · ${row.timing_label}` : ""}
          </Typography>
          {showParticipation ? (
            <Typography variant="body2" sx={{ mt: 0.35, fontWeight: 700, color: VEEWASH_DASHBOARD.wfCharcoal }}>
              {summary}
            </Typography>
          ) : null}
        </Box>
        <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap>
          {row.overall_status ? (
            <OverallBadge status={row.overall_status} />
          ) : (
            <>
              <CompletionBadge status={row.completion_status} />
              <VerificationBadge status={row.verification_status} />
            </>
          )}
          <IconButton
            size="small"
            onClick={(e) => {
              e.stopPropagation();
              onToggle();
            }}
            aria-label={expanded ? "Collapse" : "Expand"}
          >
            {expanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
          </IconButton>
        </Stack>
      </Stack>

      <Collapse in={expanded} timeout="auto" unmountOnExit>
        <Box
          sx={{
            px: 1.5,
            pb: 1.5,
            pt: 0.5,
            borderTop: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
            bgcolor: VEEWASH_DASHBOARD.pageBackground,
          }}
        >
          {checklistItems.length > 0 ? (
            <Box sx={{ mb: 1.25 }}>
              <Typography
                variant="caption"
                sx={{ fontWeight: 700, color: VEEWASH_DASHBOARD.monitoringText, letterSpacing: 0.3 }}
              >
                CHECKLIST
              </Typography>
              <Stack spacing={0.5} sx={{ mt: 0.5 }}>
                {checklistItems.map((item) => (
                  <Stack
                    key={item.task_code || item.id}
                    direction="row"
                    justifyContent="space-between"
                    alignItems="center"
                    spacing={1}
                  >
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                      {item.task_name || item.task_code}
                    </Typography>
                    <Stack direction="row" spacing={0.5} alignItems="center">
                      <ChecklistBadge status={item.display_status || item.status} />
                      {item.completed_by_name ? (
                        <Typography variant="caption" color="text.secondary">
                          {item.completed_by_name}
                          {item.completed_at
                            ? ` · ${formatDashboardTime(item.completed_at)}`
                            : ""}
                        </Typography>
                      ) : null}
                    </Stack>
                  </Stack>
                ))}
              </Stack>
              {row.checklist_complete === false ? (
                <Typography variant="caption" color="warning.dark" sx={{ display: "block", mt: 0.5 }}>
                  Required checklist items are not all checked off — assignment stays In Progress.
                </Typography>
              ) : null}
            </Box>
          ) : null}

          <Typography
            variant="caption"
            sx={{ fontWeight: 700, color: VEEWASH_DASHBOARD.monitoringText, letterSpacing: 0.3 }}
          >
            PARTICIPANTS
          </Typography>
          <Stack spacing={1} sx={{ mt: 0.75 }}>
            {(row.contributions || []).map((c) => {
              const act = c.activity || {};
              const duration = hideLabor ? null : formatDuration(act.duration_seconds);
              const participation = participationStatusOf(c);
              return (
                <Box
                  key={`${c.employee_id}-${act.id || c.responsibility_id}`}
                  sx={{
                    bgcolor: "#fff",
                    borderRadius: 1.5,
                    border: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
                    px: 1.25,
                    py: 1,
                  }}
                >
                  <Stack
                    direction={{ xs: "column", sm: "row" }}
                    justifyContent="space-between"
                    alignItems={{ xs: "flex-start", sm: "center" }}
                    spacing={1}
                  >
                    <Box>
                      <Typography variant="body2" sx={{ fontWeight: 800 }}>
                        {c.employee_name}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {showParticipation
                          ? participationTimeLine(c)
                          : act.timestamp_kind === "checklist_checkoff"
                            ? `Checked off ${formatDashboardDateTime(act.checked_off_at || act.ended_at)}`
                            : `${formatDashboardDateTime(act.started_at)} → ${formatDashboardDateTime(
                                act.ended_at
                              )}`}
                        {duration ? ` · ${duration}` : ""}
                      </Typography>
                    </Box>
                    <Stack direction="row" spacing={0.5} alignItems="center" flexWrap="wrap" useFlexGap>
                      <TaskStatusBadge
                        label={
                          showParticipation
                            ? participationLabel(participation)
                            : friendlyStatusLabel(c.status || act.status)
                        }
                      />
                      {!readOnly && canApprove && !verifyLocked && String(c.status) === "pending_approval" && act.id ? (
                        <>
                          <Button size="small" variant="contained" onClick={() => onApprove(act.id)}
                            sx={{ bgcolor: VEEWASH_DASHBOARD.teal, "&:hover": { bgcolor: VEEWASH_DASHBOARD.tealDark } }}>
                            Approve
                          </Button>
                          <Button size="small" color="warning" onClick={() => onReject(act.id)}>
                            Reject
                          </Button>
                        </>
                      ) : null}
                      {!readOnly && canManual && act.id ? (
                        <>
                          <Button size="small" onClick={() => onEditRecord?.(row, c, act)}>
                            Edit
                          </Button>
                          <Button size="small" color="error" onClick={() => onVoidRecord?.(row, c, act)}>
                            Remove
                          </Button>
                        </>
                      ) : null}
                      {!readOnly && canManual && c.can_manual_complete ? (
                        <Button size="small" variant="outlined" onClick={() => onManual(row, c, "record")}>
                          Add / Record
                        </Button>
                      ) : null}
                      {!readOnly && canManual && c.can_correct && act.id ? (
                        <Button size="small" onClick={() => onManual(row, c, "correct")}>
                          Correct
                        </Button>
                      ) : null}
                    </Stack>
                  </Stack>

                  {(c.group_items || []).length > 0 ? (
                    <Stack spacing={0.35} sx={{ mt: 0.75, pl: 0.5 }}>
                      {c.group_items.map((gi) => (
                        <Stack
                          key={gi.task_code || gi.id}
                          direction="row"
                          justifyContent="space-between"
                          alignItems="center"
                        >
                          <Typography variant="caption">
                            {gi.task_name || gi.task_code}
                          </Typography>
                          <Stack direction="row" spacing={0.5} alignItems="center">
                            <ChecklistBadge status={gi.display_status || gi.status} />
                            {!readOnly &&
                            canApprove &&
                            !verifyLocked &&
                            (gi.display_status === "pending_approval" ||
                              gi.display_status === "pending_verification") &&
                            gi.activity_id ? (
                              <>
                                <Button size="small" onClick={() => onApprove(gi.activity_id)}>
                                  Verify
                                </Button>
                                <Button size="small" color="warning" onClick={() => onReject(gi.activity_id)}>
                                  Needs correction
                                </Button>
                              </>
                            ) : null}
                          </Stack>
                        </Stack>
                      ))}
                    </Stack>
                  ) : null}

                  {rejectId != null && act.id != null && rejectId === act.id ? (
                    <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mt: 1 }}>
                      <Box
                        component="input"
                        value={reason}
                        onChange={(e) => setReason(e.target.value)}
                        placeholder="Reason for rejection"
                        style={{
                          flex: 1,
                          padding: "8px 10px",
                          borderRadius: 8,
                          border: `1px solid ${VEEWASH_DASHBOARD.monitoringBorder}`,
                        }}
                      />
                      <Button size="small" color="warning" variant="contained" onClick={onConfirmReject}>
                        Confirm
                      </Button>
                      <Button size="small" onClick={onCancelReject}>
                        Cancel
                      </Button>
                    </Stack>
                  ) : null}
                </Box>
              );
            })}
          </Stack>
        </Box>
      </Collapse>
    </Box>
  );
}
