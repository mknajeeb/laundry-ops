import { useState } from "react";
import {
  Box,
  Button,
  Collapse,
  IconButton,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import ActivityRemarks from "./ActivityRemarks";
import InstructionHint from "./InstructionHint";
import { useI18n } from "../../i18n/I18nContext";
import { localizedConfigured, localizedInstruction, taskStatusLabel } from "./taskEmployeeI18n";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";
import { CompletionDetails } from "../../opsMobile/TaskCompletionInputs";
import { ChecklistBadge, TaskStatusBadge } from "./TaskStatusBadge";
import {
  formatDashboardDate,
  formatDashboardDateTime,
  formatDashboardTime,
  participationTimeLine,
} from "./taskDashboardFormat";
import {
  formatDurationHm,
  participationStatusOf,
  showPerEmployeeChecklist,
} from "./taskDashboardLabels";
import { checklistSummary, employeeCheckSummary, responsibilityLabel, visibleSectionLabel } from "./sharedChecklistOwnership";

function ChecklistItemTitle({ item, label }) {
  const { locale } = useI18n();
  const name =
    localizedConfigured(
      { task_name: item.task_name || item.task_label, task_name_es: item.task_name_es },
      locale,
      "task_name",
      "task_name_es",
    ) || item.task_code;
  const instructions = localizedInstruction(item, locale);
  return (
    <>
      <Typography variant="body2" sx={{ fontWeight: 600 }}>
        {name}
      </Typography>
      <InstructionHint text={instructions} label={label} />
    </>
  );
}

function formatDuration(seconds) {
  if (seconds == null) return null;
  return formatDurationHm(seconds);
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
  onEditParticipation,
  onExcuse,
  onEditRecord,
  onVoidRecord,
  rejectId,
  reason,
  setReason,
  onConfirmReject,
  onCancelReject,
  onAddRemark,
}) {
  const { locale, t } = useI18n();
  const [supervisorRemark, setSupervisorRemark] = useState("");
  const employees = (row.assigned_employees || []).join(" + ") || t("tasks.dashboard.unassigned");
  const checklistItems = row.shared_checklist_items || [];
  const instructions = localizedInstruction(row, locale);
  const activityName = localizedConfigured(
    { name: row.role_label || row.role, name_es: row.name_es },
    locale,
    "name",
    "name_es",
  );
  const showParticipation = Boolean(row.shared || row.execution_mode === "shared" || row.overall_status);
  const summary = checklistSummary(row);
  const checklistRequired = summary.required;
  const checklistProgress = summary.done;
  const statusText =
    row.overall_status === "verified" && row.verification_status && row.verification_status !== "verified"
      ? taskStatusLabel(t, row.completion_status || "completed")
      : taskStatusLabel(t, row.overall_status || row.status);
  const verifyLocked = row.verification_eligible === false;
  const sectionHeadings = (row.checklist_sections || [])
    .map((section) => ({
      ...section,
      title: visibleSectionLabel(
        (locale === "es" &&
          checklistItems.find((item) => item.section_label === section.section_label)?.section_label_es) ||
          section.section_label,
        (row.checklist_sections || []).length,
      ),
    }))
    .filter((section) => section.title);

  return (
    <Box
      sx={{
        border: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
        borderRadius: 2,
        bgcolor: "#fff",
        boxShadow: VEEWASH_DASHBOARD.cardShadow,
        overflow: "hidden",
        breakInside: "avoid",
        pageBreakInside: "avoid",
      }}
      className="task-print-card"
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
              {activityName || row.role_label || row.role}
            </Typography>
            <InstructionHint text={instructions} />
            {row.has_manual_completion && !readOnly ? (
              <TaskStatusBadge label={t("tasks.dashboard.manualEntry")} tone="Finished" />
            ) : null}
          </Stack>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.2 }}>
            {formatDashboardDate(row.business_date)}
            {" · "}
            {employees}
            {row.timing_label ? ` · ${row.timing_label}` : ""}
          </Typography>
          <Typography variant="body2" sx={{ mt: 0.15, color: VEEWASH_DASHBOARD.wfCharcoal }}>
            {checklistRequired
              ? t("tasks.dashboard.itemsCompleted", { done: checklistProgress, required: checklistRequired })
              : t("tasks.dashboard.noChecklist")}
            {" · "}
            {statusText}
          </Typography>
          {hideLabor && row.activity_started_at ? (
            <Typography variant="caption" color="text.secondary" display="block">
              {t("tasks.dashboard.started", { time: formatDashboardDateTime(row.activity_started_at) })}
            </Typography>
          ) : null}
        </Box>
        <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap>
          <IconButton
            size="small"
            onClick={(e) => {
              e.stopPropagation();
              onToggle();
            }}
            aria-label={expanded ? t("tasks.dashboard.collapse") : t("tasks.dashboard.expand")}
          >
            {expanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
          </IconButton>
        </Stack>
      </Stack>

      <Collapse in={expanded} timeout="auto">
        <Box
          sx={{
            px: 1.5,
            pb: 1.5,
            pt: 0.5,
            borderTop: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
            bgcolor: VEEWASH_DASHBOARD.pageBackground,
          }}
        >
          {!readOnly && canApprove ? (
            <TextField
              className="no-print"
              size="small"
              fullWidth
              label={t("tasks.dashboard.supervisorRemark")}
              value={supervisorRemark}
              onChange={(e) => setSupervisorRemark(e.target.value)}
              sx={{ mb: 1, bgcolor: "#fff" }}
            />
          ) : null}
          {checklistItems.length > 0 ? (
            <Box sx={{ mb: 1.25 }}>
              <Typography
                variant="caption"
                sx={{ fontWeight: 700, color: VEEWASH_DASHBOARD.monitoringText, letterSpacing: 0.3 }}
              >
                CHECKLIST
              </Typography>
              {sectionHeadings.length ? (
                <Stack spacing={0.25} sx={{ mt: 0.5 }}>
                  {sectionHeadings.map((section) => (
                    <Stack key={section.section_label || section.title} direction="row" spacing={1} alignItems="center">
                      <Typography variant="caption" sx={{ fontWeight: 700 }}>
                        {section.title}
                        {section.status_label ? ` · ${section.status_label}` : ""}
                      </Typography>
                      {canApprove && section.pending_activity_ids?.length ? (
                        <Button
                          size="small"
                          onClick={() => onApprove?.(section.pending_activity_ids, supervisorRemark)}
                          sx={{ textTransform: "none", fontWeight: 800 }}
                        >
                          Verify section
                        </Button>
                      ) : null}
                    </Stack>
                  ))}
                </Stack>
              ) : null}
              <Stack spacing={0.5} sx={{ mt: 0.5 }}>
                {checklistItems.map((item) => (
                  <Stack
                    key={item.task_code || item.id}
                    direction="row"
                    justifyContent="space-between"
                    alignItems="center"
                    spacing={1}
                  >
                    <Box>
                      <Stack direction="row" alignItems="center" spacing={0.25}>
                        <ChecklistItemTitle item={item} label={t("tasks.pin.itemInstructions")} />
                      </Stack>
                      <Typography variant="caption" color="text.secondary" display="block">
                        {responsibilityLabel(item)}
                      </Typography>
                      <CompletionDetails completionInput={item.completion_input} schema={item.input_schema} />
                    </Box>
                    <Stack spacing={0.25} alignItems="flex-end">
                      {(item.employee_checks || []).length ? (
                        employeeCheckSummary(item.employee_checks).map((check) => (
                          <Typography key={check.userId} variant="caption" color="text.secondary">
                            {check.name}
                            {" · "}
                            {check.status === "excused"
                              ? t("tasks.pin.excused")
                              : check.done
                                ? t("tasks.pin.checkedOff")
                                : t("tasks.pin.notCheckedOff")}
                            {check.done && !hideLabor && check.completedAt
                              ? ` · ${formatDashboardTime(check.completedAt)}`
                              : ""}
                          </Typography>
                        ))
                      ) : (
                        <Stack direction="row" spacing={0.5} alignItems="center">
                          <ChecklistBadge status={item.display_status || item.status} />
                          {item.completed_by_name ? (
                            <Typography variant="caption" color="text.secondary">
                              {item.completed_by_name}
                              {!hideLabor && item.completed_at
                                ? ` · ${formatDashboardTime(item.completed_at)}`
                                : ""}
                            </Typography>
                          ) : null}
                        </Stack>
                      )}
                    </Stack>
                  </Stack>
                ))}
              </Stack>
            </Box>
          ) : null}

          {!readOnly || (row.remarks || []).length ? (
            <ActivityRemarks
              remarks={readOnly ? [] : row.remarks || []}
              items={checklistItems}
              readOnly={readOnly || !onAddRemark}
              busy={false}
              onAdd={
                readOnly || !onAddRemark
                  ? undefined
                  : (body, taskCode) => onAddRemark(body, taskCode)
              }
            />
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
                      {hideLabor ? null : (
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
                      )}
                    </Box>
                    <Stack direction="row" spacing={0.5} alignItems="center" flexWrap="wrap" useFlexGap>
                      <TaskStatusBadge
                        label={
                          showParticipation
                            ? taskStatusLabel(t, participation)
                            : taskStatusLabel(t, c.status || act.status)
                        }
                      />
                      {!readOnly && canApprove && !verifyLocked && String(c.status) === "pending_approval" && act.id ? (
                        <>
                          <Button size="small" variant="contained" onClick={() => onApprove(act.id, supervisorRemark)}
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
                      {!readOnly && canManual ? (
                        <Button size="small" variant="outlined" onClick={() => onEditParticipation?.(row, c)}>
                          {t("tasks.dashboard.editParticipation")}
                        </Button>
                      ) : null}
                      {!readOnly && canManual && c.participation_requirement !== "excused" ? (
                        <Button size="small" onClick={() => onExcuse?.(row, c)}>
                          {t("tasks.dashboard.excuse")}
                        </Button>
                      ) : null}
                    </Stack>
                  </Stack>

                  {!(row.remarks || []).length && c.activity?.employee_remark?.text ? (
                    <Typography variant="caption" display="block" sx={{ mt: 0.5 }}>
                      Employee remark: {c.activity.employee_remark.text}
                    </Typography>
                  ) : null}
                  {!(row.remarks || []).length && c.activity?.supervisor_remark?.text ? (
                    <Typography variant="caption" display="block">
                      Supervisor remark: {c.activity.supervisor_remark.text}
                    </Typography>
                  ) : null}
                  {showPerEmployeeChecklist(row, c) ? (
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
