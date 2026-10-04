import { Box, Button, Typography } from "@mui/material";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";
import { roleStyle } from "./weeklyScheduleRoles";
import { summaryRoleLines, summaryTotalsMetrics, summaryUnallocatedText } from "./weeklyScheduleSummaryLines";

const BREAK_ACCENT = "#9a3412";
const TOTAL_ACCENTS = {
  people: VEEWASH_DASHBOARD.primaryBlueDark,
  days: VEEWASH_DASHBOARD.tealDark,
  break: BREAK_ACCENT,
  net: VEEWASH_DASHBOARD.tealDark,
};

function formatCurrency(value) {
  const n = Number(value || 0);
  return n.toLocaleString(undefined, { style: "currency", currency: "USD" });
}

function SummaryMetric({ label, value, accent, compact = false }) {
  return (
    <Box component="span" sx={{ display: "inline-flex", alignItems: "baseline", gap: 0.5, whiteSpace: "nowrap", flexShrink: 0 }}>
      <Typography
        component="span"
        variant="body2"
        sx={{ color: "text.secondary", fontWeight: 600, fontSize: compact ? "0.75rem" : "0.8125rem" }}
      >
        {label}:
      </Typography>
      <Typography
        component="span"
        variant="body2"
        sx={{ fontWeight: 800, color: accent || "text.primary", fontSize: compact ? "0.8125rem" : "0.875rem" }}
      >
        {value}
      </Typography>
    </Box>
  );
}

function Separator() {
  return (
    <Typography component="span" variant="body2" sx={{ color: "divider", flexShrink: 0 }}>
      |
    </Typography>
  );
}

/** One horizontal line; scrolls sideways instead of wrapping, with the category label pinned left. */
function SummaryLine({ label, children, compact, lineKey }) {
  return (
    <Box
      data-summary-line={lineKey}
      sx={{
        display: "flex",
        flexWrap: "nowrap",
        alignItems: "baseline",
        columnGap: compact ? 1 : 1.5,
        overflowX: "auto",
        whiteSpace: "nowrap",
        scrollbarWidth: "thin",
        py: compact ? 0.15 : 0.25,
      }}
    >
      {label ? (
        <Typography
          component="span"
          variant="caption"
          sx={{
            position: "sticky",
            left: 0,
            zIndex: 1,
            bgcolor: "#fff",
            pr: 0.75,
            fontWeight: 800,
            fontSize: "0.66rem",
            letterSpacing: "0.05em",
            textTransform: "uppercase",
            color: "text.secondary",
            minWidth: compact ? 64 : 80,
            flexShrink: 0,
          }}
        >
          {label}
        </Typography>
      ) : null}
      {children}
    </Box>
  );
}

/**
 * Week totals for what is on screen. Line one: employees, gross, break, and net hours. Then one line per
 * role category with "X people · Y hours" per role. With roles selected, every number covers only those
 * roles. `noRolesSelected` replaces the zeros with a prompt to select all roles.
 */
export default function WeeklyScheduleSummaryBar({
  summary,
  showCost,
  compact = false,
  showBreaks = true,
  noRolesSelected = false,
  noRolesText = "No roles selected",
  onSelectAllRoles,
}) {
  if (!summary) return null;

  const frame = {
    mb: compact ? 0.5 : 1.5,
    px: compact ? { xs: 0.75, md: 1 } : { xs: 1.25, md: 1.5 },
    py: compact ? 0.4 : 1,
    borderRadius: compact ? 1.5 : 2,
    bgcolor: "#fff",
    border: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
    boxShadow: compact ? "none" : VEEWASH_DASHBOARD.cardShadow,
  };

  if (noRolesSelected) {
    return (
      <Box className="weekly-schedule-print-summary" data-summary-no-roles sx={{ ...frame, display: "flex", alignItems: "center" }}>
        <Typography variant="body2" sx={{ fontWeight: 700, color: "text.secondary" }}>
          {`${noRolesText}—`}
        </Typography>
        {onSelectAllRoles ? (
          <Button size="small" onClick={onSelectAllRoles} sx={{ fontWeight: 800, py: 0, minWidth: 0, textTransform: "none" }}>
            Select all
          </Button>
        ) : null}
      </Box>
    );
  }

  const totals = summaryTotalsMetrics(summary, { showBreaks, compact });
  if (showCost) totals.push({ key: "cost", label: "Estimated Labor Cost", value: formatCurrency(summary.estimatedCost) });
  const roleLines = summaryRoleLines(summary);
  const unallocated = summaryUnallocatedText(summary, { showBreaks });

  return (
    <Box className="weekly-schedule-print-summary" sx={frame}>
      {!compact ? (
        <Typography
          variant="overline"
          sx={{
            display: "block",
            fontWeight: 800,
            letterSpacing: "0.1em",
            color: VEEWASH_DASHBOARD.primaryBlueDark,
            mb: 0.5,
            fontSize: "0.68rem",
          }}
        >
          Week Summary
        </Typography>
      ) : null}
      <SummaryLine compact={compact} lineKey="totals">
        {totals.map((metric, index) => (
          <Box key={metric.key} component="span" sx={{ display: "inline-flex", alignItems: "baseline", columnGap: compact ? 1 : 1.5 }}>
            {index > 0 ? <Separator /> : null}
            <SummaryMetric
              label={metric.label}
              value={metric.value}
              accent={metric.key === "cost" ? VEEWASH_DASHBOARD.pendingDark : TOTAL_ACCENTS[metric.key]}
              compact={compact}
            />
          </Box>
        ))}
      </SummaryLine>
      {roleLines.map((line) => (
        <SummaryLine key={line.code || "ungrouped"} label={line.label} compact={compact} lineKey={line.code || "ungrouped"}>
          {line.items.map((item, index) => (
            <Box
              key={item.role}
              component="span"
              data-summary-role={item.role}
              sx={{ display: "inline-flex", alignItems: "baseline", columnGap: compact ? 1 : 1.5 }}
            >
              {index > 0 ? <Separator /> : null}
              <SummaryMetric label={item.label} value={item.value} accent={roleStyle(item.role).accent} compact={compact} />
            </Box>
          ))}
        </SummaryLine>
      ))}
      {unallocated ? (
        <SummaryLine compact={compact} lineKey="unallocated">
          <Box component="span" data-summary-role="__unallocated_break" sx={{ display: "inline-flex" }}>
            <SummaryMetric
              label={showBreaks ? "Unallocated break" : "Role hours"}
              value={unallocated}
              accent={BREAK_ACCENT}
              compact={compact}
            />
          </Box>
        </SummaryLine>
      ) : null}
    </Box>
  );
}
