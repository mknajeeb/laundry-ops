import { Box, Chip, Stack, Typography } from "@mui/material";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

const WF_SUPERVISOR_NOTE =
  "Cleaning scans alone do not mark WF complete. Use second weight-entry or complete-cleaning.";

/** Badge color by pending-why key (display only). */
function pendingWhyChipColor(key) {
  if (key === "same_ts_weight_dupes") return { bg: "#fff3e0", color: "#e65100", border: "#ffcc80" };
  if (key === "cleaning_started_not_completed" || key === "awaiting_complete_cleaning") {
    return { bg: "#e3f2fd", color: VEEWASH_DASHBOARD.primaryBlueDark, border: VEEWASH_DASHBOARD.primaryBlueBorder };
  }
  if (String(key || "").startsWith("hd_")) {
    return { bg: "#f3e5f5", color: "#6a1b9a", border: "#ce93d8" };
  }
  return { bg: "#fce4ec", color: "#c62828", border: "#f48fb1" };
}

export function PendingWhyBadge({ row, size = "small" }) {
  if (row?.at_vendor_status !== "Pending") return null;
  const label = row.pending_why_label;
  if (!label) return null;
  const colors = pendingWhyChipColor(row.pending_why_key);
  return (
    <Chip
      label={label}
      size={size}
      sx={{
        mt: 0.75,
        height: "auto",
        maxWidth: "100%",
        "& .MuiChip-label": {
          whiteSpace: "normal",
          lineHeight: 1.35,
          py: 0.5,
          px: 0.75,
          fontWeight: 600,
          fontSize: size === "small" ? "0.6875rem" : "0.75rem",
        },
        bgcolor: colors.bg,
        color: colors.color,
        border: "1px solid",
        borderColor: colors.border,
      }}
    />
  );
}

export function RushPendingWhyPanel({ summary, showSupervisorNote = true }) {
  const total = summary?.total_rush_pending ?? 0;
  if (!total) return null;

  const lines = [
    { key: "missing_second_weight", label: "missing second weight", count: summary?.missing_second_weight },
    { key: "same_ts_weight_dupes", label: "have only duplicate same-time weight uploads", count: summary?.same_ts_weight_dupes },
    { key: "missing_complete_cleaning", label: "missing complete-cleaning", count: summary?.missing_complete_cleaning },
    { key: "cleaning_started_not_completed", label: "cleaning started, not completed", count: summary?.cleaning_started_not_completed },
    { key: "hd_missing_second_add_photos", label: "HD missing second add-photos", count: summary?.hd_missing_second_add_photos },
    { key: "hd_issue_interruption", label: "HD issue/workitem before second add-photos", count: summary?.hd_issue_interruption },
  ].filter((item) => (item.count ?? 0) > 0);

  if (!lines.length) return null;

  return (
    <Stack
      spacing={0.75}
      sx={{
        mt: 1.25,
        p: 1.25,
        borderRadius: 2,
        border: "1px solid",
        borderColor: VEEWASH_DASHBOARD.snapshotBorder,
        bgcolor: VEEWASH_DASHBOARD.snapshotBg,
      }}
    >
      <Typography variant="subtitle2" fontWeight={700} sx={{ color: VEEWASH_DASHBOARD.primaryBlueDark }}>
        Why are these still pending?
      </Typography>
      <Typography variant="caption" color="text.secondary" display="block">
        {total} Rush Pending bag{total === 1 ? "" : "s"} — scan/action needed:
      </Typography>
      <Stack component="ul" spacing={0.35} sx={{ m: 0, pl: 2.25 }}>
        {lines.map((item) => (
          <Typography key={item.key} component="li" variant="caption" color="text.primary">
            <Box component="span" fontWeight={700}>{item.count}</Box>
            {" "}
            {item.label}
          </Typography>
        ))}
      </Stack>
      {showSupervisorNote ? (
        <Typography
          variant="caption"
          sx={{
            mt: 0.5,
            pt: 0.75,
            borderTop: "1px solid",
            borderColor: "divider",
            color: "text.secondary",
            fontStyle: "italic",
          }}
        >
          {WF_SUPERVISOR_NOTE}
        </Typography>
      ) : null}
    </Stack>
  );
}

export { WF_SUPERVISOR_NOTE };
