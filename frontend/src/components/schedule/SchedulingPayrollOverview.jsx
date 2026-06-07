import { useMemo, useState } from "react";
import {
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Collapse,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import { SCHEDULE_THEME } from "../../payroll/scheduleTheme";
import {
  PERIOD_OPTIONS,
  SCHEDULE_ESTIMATE_LABEL,
  buildPayrollPeriodOverview,
  computePeriodMetrics,
  periodDateRange,
  buildCalendarBundle,
} from "../../payroll/schedulePeriodSummary";
import { formatWeekRangeLabel } from "../../utils/businessTime";

function money(n) {
  return `$${Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function MetricTile({ label, value, highlight, sub }) {
  return (
    <Box
      sx={{
        minWidth: 80,
        px: 1,
        py: 0.75,
        borderRadius: 1.5,
        bgcolor: highlight ? "error.50" : "rgba(255,255,255,0.9)",
        border: "1px solid",
        borderColor: highlight ? "error.light" : "divider",
        flex: "0 0 auto",
      }}
    >
      <Typography variant="caption" color="text.secondary" display="block" lineHeight={1.1}>
        {label}
      </Typography>
      <Typography variant="body2" fontWeight={800}>
        {value}
      </Typography>
      {sub ? (
        <Typography variant="caption" color="text.secondary">
          {sub}
        </Typography>
      ) : null}
    </Box>
  );
}

function PeriodCard({ card, expanded, onToggleExpand, children }) {
  if (!card) return null;
  return (
    <Card sx={{ ...SCHEDULE_THEME.card, height: "100%" }}>
      <CardContent>
        <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
          <Box sx={{ flex: 1 }}>
            <Typography variant="overline" color="text.secondary" fontWeight={800}>
              {card.card_title}
            </Typography>
            <Chip size="small" label={card.subtitle} sx={{ mt: 0.5, mb: 0.5, fontWeight: 600 }} />
            <Typography variant="body2" color="text.secondary">
              {card.period_label || formatWeekRangeLabel(card.work_week_start, card.work_week_end)}
            </Typography>
            {card.payment_day_label && card.payment_date ? (
              <Typography variant="body2" sx={{ mt: 0.5 }}>
                Payment: {card.payment_day_label}, {card.payment_date}
              </Typography>
            ) : null}
          </Box>
          {card.daily_breakdown?.length ? (
            <Button size="small" endIcon={expanded ? <ExpandLessIcon /> : <ExpandMoreIcon />} onClick={onToggleExpand}>
              Daily
            </Button>
          ) : null}
        </Stack>

        <Typography variant="h5" fontWeight={800} color="primary.main" sx={{ my: 1 }}>
          {money(card.estimated_cost)}
        </Typography>

        <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap sx={{ mb: 1 }}>
          <MetricTile label="Hours" value={Number(card.total_scheduled_hours || 0).toFixed(0)} />
          <MetricTile label="Workers" value={card.total_workers} />
          <MetricTile label="W-2" value={money(card.w2_cost)} />
          <MetricTile label="1099" value={money(card.contractor_1099_cost)} />
          <MetricTile label="Temp" value={money(card.temp_cost)} />
          <MetricTile
            label="OT risk"
            value={card.overtime_risk_count}
            highlight={card.overtime_risk_count > 0}
          />
        </Stack>

        <Stack spacing={0.25}>
          <Typography variant="caption" color="text.secondary">
            Published schedule cost: {money(card.published_schedule_cost)}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Draft schedule cost: {money(card.draft_schedule_cost)}
          </Typography>
        </Stack>

        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
          {card.note}
        </Typography>

        <Collapse in={expanded}>{children}</Collapse>
      </CardContent>
    </Card>
  );
}

function DailyTable({ rows }) {
  if (!rows?.length) return null;
  return (
    <Table size="small" sx={{ mt: 1.5 }}>
      <TableHead>
        <TableRow>
          <TableCell>Day</TableCell>
          <TableCell align="right">Workers</TableCell>
          <TableCell align="right">Hours</TableCell>
          <TableCell align="right">Est. cost</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {rows.map((d) => (
          <TableRow key={d.date || d.day}>
            <TableCell>
              {d.short_label || d.day}
            </TableCell>
            <TableCell align="right">{d.people_count}</TableCell>
            <TableCell align="right">{Number(d.hours || 0).toFixed(1)}</TableCell>
            <TableCell align="right">{money(d.cost)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export default function SchedulingPayrollOverview({
  periodId,
  onPeriodChange,
  draftEntries,
  workers,
  settings,
  calendarSettings,
  anchorYmd,
  plannerWeek,
}) {
  const [expandLast, setExpandLast] = useState(false);
  const [expandCurrent, setExpandCurrent] = useState(false);
  const [expandNext, setExpandNext] = useState(false);

  const overview = useMemo(
    () =>
      buildPayrollPeriodOverview({
        entries: draftEntries,
        workers,
        settings,
        calendarSettings,
        anchorYmd,
        plannerWeek,
      }),
    [draftEntries, workers, settings, calendarSettings, anchorYmd, plannerWeek],
  );

  const bundle = overview.bundle;

  const chipMetrics = useMemo(() => {
    const range = periodDateRange(periodId, {
      anchorYmd,
      plannerWeek,
      weekStartsOn: bundle.weekStartsOn,
      calendarBundle: bundle,
    });
    const { includeDraft, includePublished } = bundle.forecastFlags;
    const publishedOnly = periodId === "last_pay_period";
    return {
      range,
      metrics: computePeriodMetrics({
        entries: draftEntries,
        workers,
        settings,
        start: range.start,
        end: range.end,
        calendarBundle: bundle,
        includeDraft: publishedOnly ? false : includeDraft,
        includePublished,
        publishedOnlyCost: publishedOnly,
      }),
    };
  }, [periodId, draftEntries, workers, settings, bundle, anchorYmd, plannerWeek]);

  const { last, current, nextWeek, comparison } = overview;

  return (
    <Stack spacing={2} sx={{ mb: 2 }}>
      <Typography variant="subtitle2" fontWeight={800}>
        Payroll period summary
      </Typography>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
        Work week and payment day come from Payroll calendar settings — not hard-coded.
      </Typography>

      <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
        {PERIOD_OPTIONS.map((p) => (
          <Chip
            key={p.id}
            label={p.label}
            clickable
            color={periodId === p.id ? "primary" : "default"}
            onClick={() => onPeriodChange?.(p.id)}
            sx={{ minHeight: 38, fontWeight: 600 }}
          />
        ))}
      </Stack>

      <Box sx={{ p: 1.25, borderRadius: 2, bgcolor: SCHEDULE_THEME.accentSoft }}>
        <Typography variant="caption" color="text.secondary" fontWeight={700}>
          Selected: {chipMetrics.range.label}
        </Typography>
        <Stack direction="row" spacing={0.75} sx={{ overflowX: "auto", mt: 0.75 }}>
          <MetricTile label="Cost" value={money(chipMetrics.metrics.estimated_cost)} />
          <MetricTile label="Hours" value={Number(chipMetrics.metrics.total_scheduled_hours || 0).toFixed(0)} />
          <MetricTile label="Workers" value={chipMetrics.metrics.total_workers} />
          <MetricTile label="OT risk" value={chipMetrics.metrics.overtime_risk_count} highlight={chipMetrics.metrics.overtime_risk_count > 0} />
        </Stack>
      </Box>

      <Stack direction={{ xs: "column", lg: "row" }} spacing={2}>
        <Box sx={{ flex: 1 }}>
          <PeriodCard card={last} expanded={expandLast} onToggleExpand={() => setExpandLast((v) => !v)}>
            <DailyTable rows={last.daily_breakdown} />
          </PeriodCard>
        </Box>
        <Box sx={{ flex: 1 }}>
          <PeriodCard card={current} expanded={expandCurrent} onToggleExpand={() => setExpandCurrent((v) => !v)}>
            <DailyTable rows={current.daily_breakdown} />
          </PeriodCard>
        </Box>
      </Stack>

      <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
        <Box sx={{ flex: 1 }}>
          <PeriodCard card={nextWeek} expanded={expandNext} onToggleExpand={() => setExpandNext((v) => !v)}>
            <DailyTable rows={nextWeek.daily_breakdown} />
          </PeriodCard>
        </Box>
        <Box sx={{ flex: 1 }}>
          <Card sx={{ ...SCHEDULE_THEME.card, height: "100%" }}>
            <CardContent>
              <Typography variant="overline" fontWeight={800}>
                Comparison
              </Typography>
              <Chip size="small" label={comparison.subtitle} sx={{ mb: 1.5 }} />
              <Stack spacing={1.5}>
                <Box>
                  <Typography variant="body2" color="text.secondary">
                    Last payroll period (published schedule)
                  </Typography>
                  <Typography variant="h6" fontWeight={800}>
                    {money(comparison.last_cost)}
                  </Typography>
                </Box>
                <Box>
                  <Typography variant="body2" color="text.secondary">
                    Upcoming payroll expected
                  </Typography>
                  <Typography variant="h6" fontWeight={800} color="primary.main">
                    {money(comparison.upcoming_cost)}
                  </Typography>
                </Box>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                  <Chip
                    label={`Cost ${comparison.cost_delta.label}`}
                    color={comparison.cost_delta.value > 0 ? "warning" : comparison.cost_delta.value < 0 ? "success" : "default"}
                    sx={{ fontWeight: 700 }}
                  />
                  <Chip label={`Hours ${comparison.hours_delta.label}`} variant="outlined" />
                  <Chip label={`Workers ${comparison.workers_delta.label}`} variant="outlined" />
                  <Chip
                    label={`OT risk ${comparison.ot_delta.label}`}
                    color={comparison.ot_delta.value > 0 ? "warning" : "default"}
                    variant="outlined"
                  />
                </Stack>
                <Typography variant="caption" color="text.secondary">
                  Not final payroll — schedule-based until payroll batch is built.
                </Typography>
              </Stack>
            </CardContent>
          </Card>
        </Box>
      </Stack>
    </Stack>
  );
}
