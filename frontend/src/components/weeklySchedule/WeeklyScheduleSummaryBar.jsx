import { Box, Typography } from "@mui/material";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";
import { formatHours, roleStyle } from "./weeklyScheduleRoles";

function formatCurrency(value) {
  const n = Number(value || 0);
  return n.toLocaleString(undefined, { style: "currency", currency: "USD" });
}

function peopleText(count) {
  const n = Number(count || 0);
  return `${n} ${n === 1 ? "person" : "people"}`;
}

/** "8 people · 42.5 hours" — distinct employees and net hours for one role. */
function roleMetricValue(row, daysOnly) {
  if (daysOnly) return peopleText(row.employees);
  const hours = Math.round(Number(row.hours || 0) * 100) / 100;
  return `${peopleText(row.employees)} · ${hours} ${hours === 1 ? "hour" : "hours"}`;
}

function SummaryMetric({ label, value, accent, compact = false }) {
  return (
    <Box component="span" sx={{ display: "inline-flex", alignItems: "baseline", gap: 0.5 }}>
      <Typography
        component="span"
        variant="body2"
        sx={{
          color: "text.secondary",
          fontWeight: 600,
          fontSize: compact ? "0.75rem" : "0.8125rem",
        }}
      >
        {label}:
      </Typography>
      <Typography
        component="span"
        variant="body2"
        sx={{
          fontWeight: 800,
          color: accent || "text.primary",
          fontSize: compact ? "0.8125rem" : "0.875rem",
        }}
      >
        {value}
      </Typography>
    </Box>
  );
}

/**
 * Week totals for what is on screen. With roles selected, every number covers only those roles:
 * employees assigned one of them (each counted once) and their net hours in the selected roles.
 */
export default function WeeklyScheduleSummaryBar({ summary, showCost, compact = false, showBreaks = true }) {
  if (!summary) return null;

  const daysOnly = summary.daysOnly === true;
  const filtered = Array.isArray(summary.roleFilter);
  const metrics = [
    {
      label: filtered ? "Selected roles" : compact ? "Employees" : "Employees Scheduled",
      value: filtered ? peopleText(summary.employeesScheduled) : summary.employeesScheduled,
      accent: VEEWASH_DASHBOARD.primaryBlueDark,
    },
    daysOnly
      ? {
          label: compact ? "Days" : "Total Days",
          value: summary.totalDays,
          accent: VEEWASH_DASHBOARD.tealDark,
        }
      : showBreaks
        ? {
            label: compact ? "Net hrs" : "Net Hours",
            value: formatHours(summary.totalHours),
            accent: VEEWASH_DASHBOARD.tealDark,
          }
        : {
            label: compact ? "Hours" : "Total Hours",
            value: formatHours(summary.totalHours),
            accent: VEEWASH_DASHBOARD.tealDark,
          },
  ];
  if (!daysOnly && showBreaks) {
    metrics.splice(
      1,
      0,
      { label: compact ? "Gross hrs" : "Gross Hours", value: formatHours(summary.grossHours) },
      {
        label: compact ? "Break hrs" : "Break Hours",
        value: Number(summary.unscheduledBreakHours || 0) > 0
          ? `${formatHours(summary.breakHours)} (${formatHours(summary.unscheduledBreakHours)} not scheduled)`
          : formatHours(summary.breakHours),
        accent: "#9a3412",
      },
    );
  }

  for (const row of summary.roles || []) {
    metrics.push({
      label: row.label,
      value: roleMetricValue(row, daysOnly),
      accent: roleStyle(row.role).accent,
      role: row.role,
    });
  }

  if (showCost) {
    metrics.push({
      label: "Estimated Labor Cost",
      value: formatCurrency(summary.estimatedCost),
      accent: VEEWASH_DASHBOARD.pendingDark,
    });
  }

  return (
    <Box
      className="weekly-schedule-print-summary"
      sx={{
        mb: compact ? 0.5 : 1.5,
        px: compact ? { xs: 0.75, md: 1 } : { xs: 1.25, md: 1.5 },
        py: compact ? 0.4 : 1,
        borderRadius: compact ? 1.5 : 2,
        bgcolor: "#fff",
        border: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
        boxShadow: compact ? "none" : VEEWASH_DASHBOARD.cardShadow,
      }}
    >
      {!compact ? (
        <Typography
          variant="overline"
          sx={{
            display: "block",
            fontWeight: 800,
            letterSpacing: "0.1em",
            color: VEEWASH_DASHBOARD.primaryBlueDark,
            mb: 0.75,
            fontSize: "0.68rem",
          }}
        >
          Week Summary
        </Typography>
      ) : null}
      <Box
        sx={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          columnGap: compact ? { xs: 1, md: 1.5 } : { xs: 1.5, md: 2.5 },
          rowGap: compact ? 0.35 : 0.75,
        }}
      >
        {metrics.map((metric, index) => (
          <Box
            key={metric.role || metric.label}
            component="span"
            data-summary-role={metric.role || undefined}
            sx={{ display: "inline-flex", alignItems: "center" }}
          >
            {index > 0 ? (
              <Typography
                component="span"
                variant="body2"
                sx={{ color: "divider", mx: { xs: 0.75, md: 1.25 }, display: { xs: "none", sm: "inline" } }}
              >
                |
              </Typography>
            ) : null}
            <SummaryMetric label={metric.label} value={metric.value} accent={metric.accent} compact={compact} />
          </Box>
        ))}
      </Box>
    </Box>
  );
}
