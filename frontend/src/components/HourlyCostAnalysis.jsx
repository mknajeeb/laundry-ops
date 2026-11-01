import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import {
  Box,
  IconButton,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableRow,
  Tooltip,
  Typography,
} from "@mui/material";
import {
  burdenCaption,
  formatBurdenPercent,
  formatHourlyRate,
  formatOtImpact,
  formatOtImpactPercent,
  hourlyCostTooltipLines,
  hourlyTargetColor,
  targetComparisonText,
} from "../payroll/hourlyCostDisplay";

export function HourlyCostInfo({ analysis, size = 16 }) {
  const lines = hourlyCostTooltipLines(analysis);
  if (!lines.length) return null;
  return (
    <Tooltip
      arrow
      enterTouchDelay={0}
      title={
        <Stack spacing={0.25} sx={{ py: 0.25 }}>
          {lines.map((line) => (
            <Typography key={line} variant="caption" component="div" sx={{ lineHeight: 1.35 }}>
              {line}
            </Typography>
          ))}
        </Stack>
      }
    >
      <IconButton
        size="small"
        aria-label="Hourly cost details"
        onClick={(event) => event.stopPropagation()}
        sx={{ p: 0.25 }}
      >
        <InfoOutlinedIcon sx={{ fontSize: size }} />
      </IconButton>
    </Tooltip>
  );
}

function MetricRow({ label, value, valueColor }) {
  return (
    <TableRow>
      <TableCell sx={{ borderBottomColor: "divider", py: 0.75 }}>{label}</TableCell>
      <TableCell
        align="right"
        sx={{
          borderBottomColor: "divider",
          py: 0.75,
          fontWeight: 700,
          whiteSpace: "nowrap",
          color: valueColor || "text.primary",
        }}
      >
        {value}
      </TableCell>
    </TableRow>
  );
}

export function HourlyCostPanel({ analysis, loading, error }) {
  return (
    <Box sx={{ mb: 2 }}>
      <Stack direction="row" spacing={0.5} alignItems="center" sx={{ mb: 0.75 }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
          Hourly cost analysis
        </Typography>
        <HourlyCostInfo analysis={analysis} />
      </Stack>
      {loading ? (
        <Typography variant="body2" color="text.secondary">
          Updating hourly cost…
        </Typography>
      ) : null}
      {error ? (
        <Typography variant="body2" color="error">
          {error}
        </Typography>
      ) : null}
      {!loading && !error && analysis ? (
        <>
          <Table size="small" sx={{ maxWidth: 520 }}>
            <TableBody>
              <MetricRow label="Base wage" value={formatHourlyRate(analysis.base_wage)} />
              <MetricRow
                label="Base cost/hr — no OT premium"
                value={formatHourlyRate(analysis.base_cost_per_hour)}
              />
              <MetricRow
                label="Effective cost/hr — with OT"
                value={formatHourlyRate(analysis.effective_cost_per_hour)}
                valueColor={hourlyTargetColor(analysis)}
              />
              <MetricRow
                label="OT impact/hr"
                value={`${formatOtImpact(analysis.ot_impact_per_hour)} (${formatOtImpactPercent(analysis.ot_impact_percent)})`}
              />
              <MetricRow
                label="Employer burden"
                value={
                  analysis.burden_percent == null
                    ? burdenCaption(analysis) || "—"
                    : `${formatBurdenPercent(analysis.burden_percent)} ${burdenCaption(analysis)}`
                }
              />
            </TableBody>
          </Table>
          {targetComparisonText(analysis) ? (
            <Typography
              variant="caption"
              sx={{ display: "block", mt: 0.75, fontWeight: 700, color: hourlyTargetColor(analysis) }}
            >
              {targetComparisonText(analysis)}
            </Typography>
          ) : null}
          {analysis.burden_status === "estimated" ? (
            <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
              Estimated from prior finalized payroll. Not a finalized expense.
            </Typography>
          ) : null}
          {analysis.base_wage_blended ? (
            <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
              Base wage is the hours-weighted regular rate for this period.
            </Typography>
          ) : null}
        </>
      ) : null}
    </Box>
  );
}
