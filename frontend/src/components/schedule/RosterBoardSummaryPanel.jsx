import { Box, Chip, Collapse, Stack, Typography } from "@mui/material";
import { SCHEDULE_THEME } from "../../payroll/scheduleTheme";

function Metric({ label, value, highlight }) {
  return (
    <Box
      sx={{
        minWidth: 76,
        px: 1,
        py: 0.75,
        borderRadius: 1.5,
        bgcolor: highlight ? "error.50" : "rgba(255,255,255,0.9)",
        border: "1px solid",
        borderColor: highlight ? "error.light" : "rgba(148,163,184,0.35)",
        flex: "0 0 auto",
      }}
    >
      <Typography variant="caption" color="text.secondary" lineHeight={1.1} display="block">
        {label}
      </Typography>
      <Typography variant="body2" fontWeight={800} color={highlight ? "error.main" : "inherit"}>
        {value}
      </Typography>
    </Box>
  );
}

export default function RosterBoardSummaryPanel({
  weekSummary,
  daySummary,
  categoryCosts,
  hasUnsaved,
  draftCount,
  publishedCount,
  collapsed,
  onToggleCollapse,
  focusDayLabel,
}) {
  return (
    <Box
      sx={{
        ...SCHEDULE_THEME.stickyBar,
        position: "sticky",
        top: 0,
        zIndex: 25,
        py: 1.25,
        px: 1,
        mb: 2,
        borderRadius: 2,
      }}
    >
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: collapsed ? 0 : 1 }}>
        <Box>
          <Typography variant="subtitle2" fontWeight={800}>
            Live roster summary
          </Typography>
          <Stack direction="row" spacing={0.5} sx={{ mt: 0.25 }}>
            {hasUnsaved ? <Chip size="small" color="warning" label="Unsaved changes" /> : null}
            <Chip size="small" variant="outlined" label={`${draftCount ?? 0} draft`} />
            <Chip size="small" variant="outlined" color="success" label={`${publishedCount ?? 0} published`} />
          </Stack>
        </Box>
        {onToggleCollapse ? (
          <Typography
            component="button"
            variant="caption"
            onClick={onToggleCollapse}
            sx={{ border: 0, bgcolor: "transparent", cursor: "pointer", fontWeight: 700 }}
          >
            {collapsed ? "Expand" : "Collapse"}
          </Typography>
        ) : null}
      </Stack>
      <Collapse in={!collapsed}>
        <Typography variant="overline" color="text.secondary" sx={{ display: "block", mb: 0.5 }}>
          Week totals
        </Typography>
        <Stack direction="row" spacing={0.75} sx={{ overflowX: "auto", pb: 0.5, mb: 1.5 }}>
          <Metric label="Workers" value={weekSummary?.unique_worker_count ?? weekSummary?.total_people ?? 0} />
          <Metric label="Shifts" value={weekSummary?.total_people ?? 0} />
          <Metric label="Hours" value={Number(weekSummary?.total_scheduled_hours || 0).toFixed(0)} />
          <Metric label="Est. cost" value={`$${Number(weekSummary?.estimated_payroll_cost || 0).toFixed(0)}`} />
          <Metric label="W-2" value={`$${Number(categoryCosts?.w2 || 0).toFixed(0)}`} />
          <Metric label="1099" value={`$${Number(categoryCosts?.contractor_1099 || 0).toFixed(0)}`} />
          <Metric label="Temp" value={`$${Number(categoryCosts?.temp || 0).toFixed(0)}`} />
          <Metric
            label="OT risk"
            value={weekSummary?.overtime_risk_count ?? 0}
            highlight={(weekSummary?.overtime_risk_count ?? 0) > 0}
          />
          <Metric
            label="Gaps"
            value={weekSummary?.open_coverage_gaps ?? 0}
            highlight={(weekSummary?.open_coverage_gaps ?? 0) > 0}
          />
          <Metric label="Underused" value={(weekSummary?.underused_workers || []).length} />
          <Metric label="Heavy" value={(weekSummary?.heavy_workers || []).length} />
        </Stack>
        {daySummary && focusDayLabel ? (
          <>
            <Typography variant="overline" color="text.secondary" sx={{ display: "block", mb: 0.5 }}>
              {focusDayLabel}
            </Typography>
            <Stack direction="row" spacing={0.75} sx={{ overflowX: "auto", pb: 0.5 }}>
              <Metric label="Workers" value={daySummary.total_people ?? 0} />
              <Metric label="Morning" value={daySummary.morning_count ?? 0} />
              <Metric label="Afternoon" value={daySummary.afternoon_count ?? 0} />
              <Metric label="Rinse" value={daySummary.rinse_count ?? 0} />
              <Metric label="Drop Off" value={daySummary.drop_off_count ?? 0} />
              <Metric label="Operator" value={daySummary.operator_count ?? 0} />
              <Metric label="Folder" value={daySummary.folder_count ?? 0} />
              <Metric label="Hours" value={Number(daySummary.total_scheduled_hours || 0).toFixed(1)} />
              <Metric label="Est. cost" value={`$${Number(daySummary.estimated_payroll_cost || 0).toFixed(0)}`} />
            </Stack>
          </>
        ) : null}
      </Collapse>
    </Box>
  );
}
