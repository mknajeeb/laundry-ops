import { Chip } from "@mui/material";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";
import {
  completionLabel,
  verificationLabel,
  checklistItemLabel,
} from "./taskDashboardLabels";

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
  "Pending Verification": {
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

export function TaskStatusBadge({ label, sx }) {
  const text = String(label || "Not Started");
  const style = STYLES[text] || STYLES["Not Started"];
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
  return <TaskStatusBadge label={completionLabel(status)} />;
}

export function VerificationBadge({ status }) {
  const label = verificationLabel(status);
  if (label === "Not Required") return null;
  return <TaskStatusBadge label={label} />;
}

export function ChecklistBadge({ status }) {
  return <TaskStatusBadge label={checklistItemLabel(status)} />;
}
