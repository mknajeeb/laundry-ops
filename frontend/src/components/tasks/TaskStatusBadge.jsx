import { Chip } from "@mui/material";
import { useI18n } from "../../i18n/I18nContext";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";
import { taskStatusLabel } from "./taskEmployeeI18n";
import {
  completionLabel,
  verificationLabel,
  checklistItemLabel,
  overallLabel,
} from "./taskDashboardLabels";

const CHECKLIST_STATUS_KEYS = {
  pending: "tasks.pin.notCheckedOff",
  completed: "tasks.pin.checkedOff",
  approved: "tasks.pin.status.verified",
  pending_verification: "tasks.pin.status.pending_verification",
  pending_approval: "tasks.pin.status.pending_verification",
  rejected: "tasks.pin.status.needs_correction",
};

const STYLES = {
  "Not Started": {
    bg: VEEWASH_DASHBOARD.monitoringBg,
    color: VEEWASH_DASHBOARD.monitoringText,
    border: VEEWASH_DASHBOARD.monitoringBorder,
  },
  "In Progress": {
    bg: VEEWASH_DASHBOARD.primaryBlueLight,
    color: VEEWASH_DASHBOARD.primaryBlueDark,
    border: VEEWASH_DASHBOARD.primaryBlueBorder,
  },
  Completed: {
    bg: VEEWASH_DASHBOARD.tealLight,
    color: VEEWASH_DASHBOARD.tealDark,
    border: VEEWASH_DASHBOARD.tealBorder,
  },
  Finished: {
    bg: VEEWASH_DASHBOARD.snapshotBg,
    color: VEEWASH_DASHBOARD.primaryBlueDark,
    border: VEEWASH_DASHBOARD.primaryBlueBorder,
  },
  "Pending Verification": {
    bg: VEEWASH_DASHBOARD.pendingLight,
    color: VEEWASH_DASHBOARD.pendingDark,
    border: VEEWASH_DASHBOARD.pendingBorder,
  },
  "Waiting for Verification": {
    bg: VEEWASH_DASHBOARD.pendingLight,
    color: VEEWASH_DASHBOARD.pendingDark,
    border: VEEWASH_DASHBOARD.pendingBorder,
  },
  "Partially Verified": {
    bg: VEEWASH_DASHBOARD.pendingLight,
    color: VEEWASH_DASHBOARD.pendingDark,
    border: VEEWASH_DASHBOARD.pendingBorder,
  },
  Verified: {
    bg: VEEWASH_DASHBOARD.tealLight,
    color: VEEWASH_DASHBOARD.tealDark,
    border: VEEWASH_DASHBOARD.tealBorder,
  },
  "Needs Correction": {
    bg: "#fef2f2",
    color: "#b91c1c",
    border: "rgba(185, 28, 28, 0.35)",
  },
  "Not Required": {
    bg: VEEWASH_DASHBOARD.snapshotBg,
    color: VEEWASH_DASHBOARD.monitoringText,
    border: VEEWASH_DASHBOARD.snapshotBorder,
  },
  "Not checked off": {
    bg: VEEWASH_DASHBOARD.monitoringBg,
    color: VEEWASH_DASHBOARD.monitoringText,
    border: VEEWASH_DASHBOARD.monitoringBorder,
  },
  "Checked off": {
    bg: VEEWASH_DASHBOARD.tealLight,
    color: VEEWASH_DASHBOARD.tealDark,
    border: VEEWASH_DASHBOARD.tealBorder,
  },
};

export function TaskStatusBadge({ label, tone, sx }) {
  const text = String(label || "Not Started");
  const style = STYLES[tone || text] || STYLES["Not Started"];
  return (
    <Chip
      size="small"
      label={text}
      sx={{
        height: 24,
        fontWeight: 700,
        fontSize: "0.72rem",
        bgcolor: style.bg,
        color: style.color,
        border: `1px solid ${style.border}`,
        "& .MuiChip-label": { px: 1 },
        ...sx,
      }}
    />
  );
}

export function CompletionBadge({ status }) {
  const { t } = useI18n();
  const tone = completionLabel(status);
  return <TaskStatusBadge label={taskStatusLabel(t, status) || tone} tone={tone} />;
}

export function OverallBadge({ status }) {
  const { t } = useI18n();
  const tone = overallLabel(status);
  return <TaskStatusBadge label={taskStatusLabel(t, status) || tone} tone={tone} />;
}

export function VerificationBadge({ status }) {
  const { t } = useI18n();
  const tone = verificationLabel(status);
  if (tone === "Not Required") return null;
  const label =
    String(status || "") === "partial"
      ? t("tasks.dashboard.partiallyVerified")
      : taskStatusLabel(t, status) || tone;
  return <TaskStatusBadge label={label} tone={tone} />;
}

export function ChecklistBadge({ status }) {
  const { t } = useI18n();
  const tone = checklistItemLabel(status);
  const key = CHECKLIST_STATUS_KEYS[String(status || "").toLowerCase()];
  return <TaskStatusBadge label={key ? t(key) : tone} tone={tone} />;
}
