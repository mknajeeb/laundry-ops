import { Box, Typography } from "@mui/material";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

const ROLE_ACCENT = {
  fold: VEEWASH_DASHBOARD.tealDark,
  sort: VEEWASH_DASHBOARD.primaryBlueDark,
  wash: VEEWASH_DASHBOARD.rushCopper,
};

function formatHours(value) {
  const n = Number(value || 0);
  return Number.isInteger(n) ? `${n}` : n.toFixed(1);
}

function formatCurrency(value) {
  const n = Number(value || 0);
  return n.toLocaleString(undefined, { style: "currency", currency: "USD" });
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

export default function WeeklyScheduleSummaryBar({ summary, showCost, compact = false }) {
  if (!summary) return null;

  const metrics = [
    { label: compact ? "Employees" : "Employees Scheduled", value: summary.employeesScheduled, accent: VEEWASH_DASHBOARD.primaryBlueDark },
    { label: compact ? "Hours" : "Total Hours", value: formatHours(summary.totalHours), accent: VEEWASH_DASHBOARD.tealDark },
    { label: "Wash", value: summary.washCount, accent: ROLE_ACCENT.wash },
    { label: "Sort", value: summary.sortCount, accent: ROLE_ACCENT.sort },
    { label: "Fold", value: summary.foldCount, accent: ROLE_ACCENT.fold },
  ];

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
        mb: compact ? 1 : 1.5,
        px: compact ? { xs: 1, md: 1.25 } : { xs: 1.25, md: 1.5 },
        py: compact ? 0.65 : 1,
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
          <Box key={metric.label} component="span" sx={{ display: "inline-flex", alignItems: "center" }}>
            {index > 0 ? (
              <Typography
                component="span"
                variant="body2"
                sx={{ color: "divider", mx: { xs: 0.75, md: 1.25 }, display: { xs: "none", sm: "inline" } }}
              >
                |
              </Typography>
            ) : null}
            <SummaryMetric {...metric} compact={compact} />
          </Box>
        ))}
      </Box>
    </Box>
  );
}
