import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Autocomplete,
  Box,
  Button,
  Checkbox,
  Chip,
  FormControl,
  InputLabel,
  Menu,
  MenuItem,
  Paper,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import FileDownloadIcon from "@mui/icons-material/FileDownload";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getLaborCostAnalysis } from "../api";
import {
  CHART_METRICS,
  LABOR_COLUMNS,
  formatColumnValue,
  formatComparisonChange,
  formatDifference,
  formatHours,
  formatImpact,
  formatMoney,
  formatPercent,
  formatRate,
  laborCostCsv,
} from "../payroll/laborCostExport";
import { hourlyTargetColor } from "../payroll/hourlyCostDisplay";
import { VEEWASH_BRAND } from "../theme/veewashBrand";

const PRESETS = [
  { value: "current_week", label: "Current Week" },
  { value: "last_week", label: "Last Week" },
  { value: "last_4_weeks", label: "Last 4 Weeks" },
  { value: "last_8_weeks", label: "Last 8 Weeks" },
  { value: "last_12_weeks", label: "Last 12 Weeks" },
  { value: "this_month", label: "This Month" },
  { value: "last_month", label: "Last Month" },
  { value: "last_3_months", label: "Last 3 Months" },
  { value: "custom", label: "Custom Range" },
];

function targetPhrase(summary) {
  if (!summary || summary.target_delta_per_hour == null || summary.target_status === "unavailable") {
    return "—";
  }
  const delta = Number(summary.target_delta_per_hour);
  const target = formatRate(summary.labor_cost_target);
  if (summary.target_status === "above") return `+$${Math.abs(delta).toFixed(2)}/hr above ${target}`;
  if (Math.abs(delta) <= 0.005) return `At ${target}`;
  return `-$${Math.abs(delta).toFixed(2)}/hr below ${target}`;
}

function KpiCard({ label, value, hint, color = "text.primary", info }) {
  const body = (
    <Paper variant="outlined" sx={{ p: 1.25, minWidth: 0, height: "100%" }}>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", lineHeight: 1.3 }}>
        {label}
      </Typography>
      <Typography variant="h6" sx={{ color, fontWeight: 700, lineHeight: 1.25, mt: 0.25 }}>
        {value}
      </Typography>
      {hint ? (
        <Typography variant="caption" color="text.secondary">
          {hint}
        </Typography>
      ) : null}
    </Paper>
  );
  if (!info) return body;
  return (
    <Tooltip title={info} placement="top">
      {body}
    </Tooltip>
  );
}

function MetricTile({ label, value }) {
  return (
    <Box sx={{ minWidth: 140 }}>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="body1" fontWeight={700}>
        {value}
      </Typography>
    </Box>
  );
}

function LaborChartTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <Paper sx={{ p: 1, maxWidth: 280 }}>
      <Typography variant="caption" fontWeight={700} display="block">
        {row.label}
      </Typography>
      <Typography variant="caption" display="block">
        Employer rate {formatRate(row.employer_effective_rate)}
      </Typography>
      <Typography variant="caption" display="block">
        Employee rate {formatRate(row.employee_effective_rate)}
      </Typography>
      <Typography variant="caption" display="block">
        Hours {formatHours(row.payable_hours)} · OT {formatHours(row.ot_hours)} ({formatPercent(row.ot_percent)})
      </Typography>
      <Typography variant="caption" display="block">
        Gross {formatMoney(row.gross_pay)} · Employer payroll cost {formatMoney(row.total_employer_cost)}
      </Typography>
      <Typography variant="caption" display="block">
        OT premium {formatMoney(row.ot_premium)} · Employer OT premium {formatMoney(row.employer_ot_premium)}
      </Typography>
      {row.previous_label ? (
        <Typography variant="caption" display="block">
          Comparison {row.previous_label}: {formatChartValue(row.metric_kind, row.previous_value)}
        </Typography>
      ) : null}
    </Paper>
  );
}

function ComparisonTable({ rows, mismatch }) {
  if (!rows?.length) return null;
  return (
    <TableContainer sx={{ overflowX: "auto" }}>
      <Table size="small" sx={{ minWidth: mismatch ? 860 : 640 }}>
        <TableHead>
          <TableRow>
            <TableCell>Metric</TableCell>
            <TableCell align="right">Previous</TableCell>
            <TableCell align="right">Current</TableCell>
            <TableCell align="right">Difference</TableCell>
            <TableCell align="right">Change</TableCell>
            {mismatch ? <TableCell align="right">Per week</TableCell> : null}
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.key}>
              <TableCell>{row.label}</TableCell>
              <TableCell align="right">{formatMetric(row, row.previous)}</TableCell>
              <TableCell align="right">{formatMetric(row, row.current)}</TableCell>
              <TableCell align="right">{formatDifference(row)}</TableCell>
              <TableCell align="right">{formatComparisonChange(row)}</TableCell>
              {mismatch ? (
                <TableCell align="right">
                  {row.current_per_week == null
                    ? "—"
                    : `${formatMetric(row, row.previous_per_week)} → ${formatMetric(row, row.current_per_week)}`}
                </TableCell>
              ) : null}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}

function formatMetric(row, value) {
  if (row.unit === "hours") return formatHours(value);
  if (row.unit === "money") return formatMoney(value);
  if (row.unit === "rate") return formatRate(value);
  if (row.unit === "percentage_points") return formatPercent(value);
  return value == null ? "—" : String(value);
}

function ClassificationCard({ title, block, rateLabel }) {
  const empty = !block || !block.worker_count;
  return (
    <Paper variant="outlined" sx={{ p: 1.5, flex: "1 1 240px" }}>
      <Typography variant="subtitle2" fontWeight={700}>
        {title}
      </Typography>
      {empty ? (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          None in this selection.
        </Typography>
      ) : (
        <Stack spacing={0.5} sx={{ mt: 1 }}>
          <Typography variant="body2">Workers {block.worker_count}</Typography>
          <Typography variant="body2">Gross {formatMoney(block.gross_pay)}</Typography>
          <Typography variant="body2">Employer payroll taxes {formatMoney(block.employer_expenses)}</Typography>
          <Typography variant="body2">Employer payroll cost {formatMoney(block.total_employer_cost)}</Typography>
          <Typography variant="body2">
            {rateLabel || block.employee_rate_label}: {formatRate(block.employee_effective_rate)}
          </Typography>
          <Typography variant="body2">Employer rate {formatRate(block.employer_effective_rate)}</Typography>
          <Typography variant="body2">
            OT {formatHours(block.ot_hours)} ({formatPercent(block.ot_percent)}) · premium {formatMoney(block.ot_premium)}
          </Typography>
          <Typography variant="body2">Employer OT impact {formatRate(block.employer_ot_impact_per_hour)}</Typography>
        </Stack>
      )}
    </Paper>
  );
}

export default function LaborCostAnalysisPanel() {
  const [preset, setPreset] = useState("current_week");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [frequency, setFrequency] = useState("weekly");
  const [compare, setCompare] = useState("none");
  const [compareStart, setCompareStart] = useState("");
  const [compareEnd, setCompareEnd] = useState("");
  const [classification, setClassification] = useState("all");
  const [status, setStatus] = useState("finalized");
  const [userIds, setUserIds] = useState([]);
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [metric, setMetric] = useState("employer_effective_rate");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState({ key: "employer_ot_premium", dir: "desc" });
  const [optionalKeys, setOptionalKeys] = useState([]);
  const [columnAnchor, setColumnAnchor] = useState(null);
  const [expandedId, setExpandedId] = useState(null);
  const [compareEmployeeId, setCompareEmployeeId] = useState("");

  const requestRef = useRef(0);
  const loadReport = useCallback(async () => {
    if (preset === "custom" && (!start || !end || start > end)) return;
    if (compare === "custom" && (!compareStart || !compareEnd || compareStart > compareEnd)) return;
    const requestId = requestRef.current + 1;
    requestRef.current = requestId;
    setLoading(true);
    setError("");
    const params = { preset, frequency, compare, classification, status };
    if (preset === "custom") {
      params.start = start;
      params.end = end;
    }
    if (compare === "custom") {
      params.compare_start = compareStart;
      params.compare_end = compareEnd;
    }
    if (userIds.length) params.user_ids = userIds.join(",");
    try {
      const res = await getLaborCostAnalysis(params);
      if (requestRef.current !== requestId) return;
      setReport(res.data);
    } catch (err) {
      if (requestRef.current !== requestId) return;
      setReport(null);
      setError(err?.response?.data?.error || err?.response?.data?.detail || "Labor Cost Analysis could not be loaded.");
    } finally {
      if (requestRef.current === requestId) setLoading(false);
    }
  }, [preset, start, end, frequency, compare, compareStart, compareEnd, classification, status, userIds]);

  useEffect(() => {
    loadReport();
  }, [loadReport]);

  const summary = report?.summary;
  const definitions = report?.definitions || {};
  const directory = report?.directory || [];
  const visibleColumns = useMemo(
    () => LABOR_COLUMNS.filter((col) => !col.optional || optionalKeys.includes(col.key)),
    [optionalKeys],
  );
  const employees = useMemo(() => {
    const rows = (report?.employees || []).filter((row) => {
      const name = String(row.employee_name || "").toLowerCase();
      return !search.trim() || name.includes(search.trim().toLowerCase());
    });
    const { key, dir } = sort;
    const factor = dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const av = a[key];
      const bv = b[key];
      if (typeof av === "string" || typeof bv === "string") {
        return String(av || "").localeCompare(String(bv || "")) * factor;
      }
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return (Number(av) - Number(bv)) * factor;
    });
  }, [report, search, sort]);

  const chartMetric = CHART_METRICS.find((item) => item.key === metric) || CHART_METRICS[0];
  const chartData = (report?.chart?.buckets || []).map((bucket, index) => {
    const previous = report?.chart?.comparison_buckets?.[index];
    return {
      ...bucket,
      previous_value: previous ? previous[metric] : null,
      previous_label: previous?.label || "",
      metric_kind: chartMetric.kind,
    };
  });
  const selectedCompareEmployee = (report?.comparison?.employees || []).find(
    (item) => `${item.user_id}|${item.classification_label}` === compareEmployeeId,
  );
  const waitingForDates =
    (preset === "custom" && (!start || !end || start > end)) ||
    (compare === "custom" && (!compareStart || !compareEnd || compareStart > compareEnd));

  function toggleSort(key) {
    setSort((prev) => (prev.key === key ? { key, dir: prev.dir === "asc" ? "desc" : "asc" } : { key, dir: "desc" }));
  }

  function downloadCsv() {
    const blob = new Blob([laborCostCsv(employees)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "labor-cost-analysis.csv";
    link.click();
    URL.revokeObjectURL(url);
  }

  const dataLabel = summary?.data_label || "";
  const chipColor = dataLabel === "Actual" ? "success" : dataLabel.startsWith("Mixed") || dataLabel === "Estimated" ? "warning" : "default";

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1} sx={{ mb: 1 }}>
        <Box>
          <Typography variant="h6" fontWeight={700} sx={{ color: VEEWASH_BRAND.primaryDark }}>
            Labor Cost Analysis
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {report?.filters?.range_label || "Payroll week"}{" "}
            {report?.filters?.start ? `· ${report.filters.start} to ${report.filters.end}` : ""}
            {report?.rules?.week_starts_on_label ? ` · Payroll weeks start on ${report.rules.week_starts_on_label}` : ""}
          </Typography>
        </Box>
        {dataLabel ? <Chip size="small" label={dataLabel} color={chipColor} /> : null}
      </Stack>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1.5 }}>
        {definitions.employer_payroll_cost ||
          "Employer Payroll Cost is gross earnings plus recorded employer payroll taxes. Workers' compensation is included only when it was already stored. Employee withholding is excluded."}
      </Typography>

      <Paper variant="outlined" sx={{ p: 1.5, mb: 1.5 }}>
        <Stack spacing={1.25}>
          <Stack direction={{ xs: "column", md: "row" }} spacing={1} useFlexGap flexWrap="wrap">
            <FormControl size="small" sx={{ minWidth: 150 }}>
              <InputLabel>Frequency</InputLabel>
              <Select label="Frequency" value={frequency} onChange={(e) => setFrequency(e.target.value)}>
                <MenuItem value="weekly">Weekly</MenuItem>
                <MenuItem value="biweekly">Biweekly</MenuItem>
                <MenuItem value="monthly">Monthly</MenuItem>
              </Select>
            </FormControl>
            <FormControl size="small" sx={{ minWidth: 180 }}>
              <InputLabel>Date range</InputLabel>
              <Select label="Date range" value={preset} onChange={(e) => setPreset(e.target.value)}>
                {PRESETS.map((item) => (
                  <MenuItem key={item.value} value={item.value}>
                    {item.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl size="small" sx={{ minWidth: 170 }}>
              <InputLabel>Payroll status</InputLabel>
              <Select label="Payroll status" value={status} onChange={(e) => setStatus(e.target.value)}>
                <MenuItem value="finalized">Finalized Only</MenuItem>
                <MenuItem value="open">Open / Estimated</MenuItem>
                <MenuItem value="all">All</MenuItem>
              </Select>
            </FormControl>
            <FormControl size="small" sx={{ minWidth: 150 }}>
              <InputLabel>Workers</InputLabel>
              <Select label="Workers" value={classification} onChange={(e) => setClassification(e.target.value)}>
                <MenuItem value="all">All Workers</MenuItem>
                <MenuItem value="w2">W-2 Only</MenuItem>
                <MenuItem value="contractor_1099">1099 Only</MenuItem>
              </Select>
            </FormControl>
            <FormControl size="small" sx={{ minWidth: 220 }}>
              <InputLabel>Compare with</InputLabel>
              <Select label="Compare with" value={compare} onChange={(e) => setCompare(e.target.value)}>
                <MenuItem value="none">No Comparison</MenuItem>
                <MenuItem value="previous_period">Previous Period</MenuItem>
                <MenuItem value="previous_equivalent">Previous Equivalent Range</MenuItem>
                <MenuItem value="custom">Custom Comparison Range</MenuItem>
              </Select>
            </FormControl>
          </Stack>
          {preset === "custom" ? (
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
              <TextField size="small" label="Start date" type="date" value={start} onChange={(e) => setStart(e.target.value)} InputLabelProps={{ shrink: true }} />
              <TextField size="small" label="End date" type="date" value={end} onChange={(e) => setEnd(e.target.value)} InputLabelProps={{ shrink: true }} />
            </Stack>
          ) : null}
          {compare === "custom" ? (
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
              <TextField size="small" label="Comparison start" type="date" value={compareStart} onChange={(e) => setCompareStart(e.target.value)} InputLabelProps={{ shrink: true }} />
              <TextField size="small" label="Comparison end" type="date" value={compareEnd} onChange={(e) => setCompareEnd(e.target.value)} InputLabelProps={{ shrink: true }} />
            </Stack>
          ) : null}
          <Autocomplete
            multiple
            size="small"
            options={directory}
            value={directory.filter((item) => userIds.includes(item.user_id))}
            getOptionLabel={(item) => item.employee_name || "Employee"}
            isOptionEqualToValue={(a, b) => a.user_id === b.user_id}
            onChange={(_, value) => setUserIds(value.map((item) => item.user_id))}
            renderInput={(params) => <TextField {...params} label="Employees" placeholder="All workers in this range" />}
          />
          {report?.rules?.payroll_week ? (
            <Typography variant="caption" color="text.secondary">
              {report.rules.payroll_week} {report.rules.biweekly}
            </Typography>
          ) : null}
        </Stack>
      </Paper>

      {loading ? (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          Loading labor cost…
        </Typography>
      ) : null}
      {error ? (
        <Alert severity="error" sx={{ mb: 1 }}>
          {error}
        </Alert>
      ) : null}
      {report && !report.employee_detail ? (
        <Alert severity="info" sx={{ mb: 1 }}>
          Employee names are hidden for this login. Workforce totals are still included above the employee table.
        </Alert>
      ) : null}
      {(report?.coverage?.notes || []).map((note) => (
        <Alert key={note} severity={note.startsWith("Mixed") || note.startsWith("These employer") ? "warning" : "info"} sx={{ mb: 1 }}>
          {note}
        </Alert>
      ))}

      {waitingForDates ? (
        <Alert severity="info" sx={{ mb: 1 }}>
          {preset === "custom" && (!start || !end || start > end)
            ? "Enter a start date and an end date."
            : "Enter a comparison start date and end date."}
        </Alert>
      ) : null}

      {summary && !waitingForDates ? (
        <>
          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: { xs: "1fr 1fr", md: "repeat(3, 1fr)", lg: "repeat(6, 1fr)" },
              gap: 1,
              mb: 1,
            }}
          >
            <KpiCard
              label="Average Employer Cost/hr"
              value={formatRate(summary.employer_effective_rate)}
              hint="Team average · Employer Payroll Cost"
              color={hourlyTargetColor({
                effective_cost_per_hour: summary.employer_effective_rate,
                target_status: summary.target_status,
              })}
              info={definitions.employer_effective_rate}
            />
            <KpiCard
              label={summary.employee_rate_label || "Average Employee Rate/hr"}
              value={formatRate(summary.employee_effective_rate)}
              hint="Gross ÷ payable hours"
              info={definitions.employee_effective_rate}
            />
            <KpiCard label="OT %" value={formatPercent(summary.ot_percent)} info={definitions.ot_percent} />
            <KpiCard label="OT Premium" value={formatMoney(summary.ot_premium)} info={definitions.ot_premium} />
            <KpiCard label="Total Employer Cost" value={formatMoney(summary.total_employer_cost)} info={definitions.employer_payroll_cost} />
            <KpiCard
              label="Difference From Target"
              value={targetPhrase(summary)}
              hint="Team average, not one employee"
              color={hourlyTargetColor({
                effective_cost_per_hour: summary.employer_effective_rate,
                target_status: summary.target_status,
              })}
              info={definitions.target}
            />
          </Box>

          <Accordion disableGutters elevation={0} sx={{ border: "1px solid", borderColor: "divider", mb: 1.5 }}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="body2" fontWeight={700}>
                More workforce and payroll figures
              </Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Stack direction="row" useFlexGap flexWrap="wrap" spacing={2}>
                <MetricTile label="Total workers" value={summary.worker_count ?? "—"} />
                <MetricTile label="W-2 workers" value={summary.w2_worker_count ?? "—"} />
                <MetricTile label="1099 workers" value={summary.contractor_1099_worker_count ?? "—"} />
                <MetricTile label="Payable hours" value={formatHours(summary.payable_hours)} />
                <MetricTile label="Regular hours" value={formatHours(summary.regular_hours)} />
                <MetricTile label="OT hours" value={formatHours(summary.ot_hours)} />
                <MetricTile label="Gross wages" value={formatMoney(summary.gross_pay)} />
                <MetricTile label="Employer payroll taxes" value={formatMoney(summary.employer_expenses)} />
                <MetricTile label="Total OT wages" value={formatMoney(summary.ot_wages)} />
                <MetricTile label="Employer OT premium" value={formatMoney(summary.employer_ot_premium)} />
                <MetricTile label="Employer rate without OT premium" value={formatRate(summary.employer_rate_without_ot)} />
                <MetricTile label="Employer OT impact/hr" value={formatRate(summary.employer_ot_impact_per_hour)} />
                <MetricTile
                  label="Employer burden %"
                  value={`${formatPercent(summary.employer_burden_percent)} ${summary.employer_burden_label || ""}`.trim()}
                />
                <MetricTile label="Employee rate without OT premium" value={formatRate(summary.employee_rate_without_ot)} />
                <MetricTile label="Employee OT impact/hr" value={formatRate(summary.employee_ot_impact_per_hour)} />
              </Stack>
            </AccordionDetails>
          </Accordion>

          <Paper variant="outlined" sx={{ p: 1.5, mb: 1.5 }}>
            <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 1 }}>
              Overtime Analysis
            </Typography>
            <Stack direction="row" useFlexGap flexWrap="wrap" spacing={2}>
              <MetricTile label="OT hours" value={formatHours(summary.ot_hours)} />
              <MetricTile label="OT %" value={formatPercent(summary.ot_percent)} />
              <MetricTile label="OT premium" value={formatMoney(summary.ot_premium)} />
              <MetricTile label="Total OT wages" value={formatMoney(summary.ot_wages)} />
              <MetricTile label="Employer OT premium" value={formatMoney(summary.employer_ot_premium)} />
              <MetricTile label="Employee OT impact/hr" value={formatImpact(summary.employee_ot_impact_per_hour)} />
              <MetricTile label="Employer OT impact/hr" value={formatImpact(summary.employer_ot_impact_per_hour)} />
              <MetricTile label="Employee OT impact %" value={formatPercent(summary.employee_ot_impact_percent)} />
              <MetricTile label="Employer OT impact %" value={formatPercent(summary.employer_ot_impact_percent)} />
            </Stack>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
              {definitions.no_ot_premium} {definitions.ot_wages} {definitions.employer_ot_premium}
            </Typography>
          </Paper>

          <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 1 }}>
            Workforce classification
          </Typography>
          <Stack direction={{ xs: "column", md: "row" }} spacing={1} sx={{ mb: 1.5 }}>
            <ClassificationCard title="All Workers" block={report.by_classification?.all} />
            <ClassificationCard title="W-2 Employees" block={report.by_classification?.w2} rateLabel="Employee Effective Rate" />
            <ClassificationCard title="1099 Contractors" block={report.by_classification?.contractor_1099} rateLabel="Worker Gross Rate" />
            {report.by_classification?.temp ? (
              <ClassificationCard title="Temp" block={report.by_classification.temp} rateLabel="Worker Gross Rate" />
            ) : null}
          </Stack>

          <Paper variant="outlined" sx={{ p: 1.5, mb: 1.5 }}>
            <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" alignItems={{ sm: "center" }} sx={{ mb: 1 }}>
              <Typography variant="subtitle1" fontWeight={700}>
                Trend
              </Typography>
              <FormControl size="small" sx={{ minWidth: 280 }}>
                <InputLabel>Chart metric</InputLabel>
                <Select label="Chart metric" value={metric} onChange={(e) => setMetric(e.target.value)}>
                  {CHART_METRICS.map((item) => (
                    <MenuItem key={item.key} value={item.key}>
                      {item.label}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Stack>
            {report.comparison?.mode && report.comparison.mode !== "none" && !report.chart?.comparison_aligned ? (
              <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
                The chart shows the selected range. Previous and current totals are in the comparison table.
              </Typography>
            ) : null}
            <Box sx={{ width: "100%", height: 280 }}>
              <ResponsiveContainer>
                <LineChart data={chartData} margin={{ top: 16, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="label" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
                  <YAxis tick={{ fontSize: 11 }} />
                  <ChartTooltip content={<LaborChartTooltip />} />
                  <Legend />
                  {chartMetric.target && summary.labor_cost_target != null ? (
                    <ReferenceLine
                      y={Number(summary.labor_cost_target)}
                      stroke={VEEWASH_BRAND.gold}
                      strokeDasharray="4 4"
                      label={`${formatRate(summary.labor_cost_target)} target`}
                    />
                  ) : null}
                  <Line
                    type="monotone"
                    dataKey={metric}
                    name={chartMetric.label}
                    stroke={VEEWASH_BRAND.primary}
                    strokeWidth={2}
                    connectNulls={false}
                    dot
                  />
                  {report.chart?.comparison_aligned ? (
                    <Line
                      type="monotone"
                      dataKey="previous_value"
                      name="Comparison"
                      stroke={VEEWASH_BRAND.gold}
                      strokeDasharray="5 5"
                      connectNulls={false}
                      dot
                    />
                  ) : null}
                </LineChart>
              </ResponsiveContainer>
            </Box>
          </Paper>

          <Paper variant="outlined" sx={{ p: 1.5, mb: 1.5 }}>
            <Typography variant="subtitle1" fontWeight={700}>
              Period comparison
            </Typography>
            {report.comparison?.mode === "none" || !report.comparison?.rows ? (
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                Choose Previous Period, Previous Equivalent Range, or a custom range to compare.
              </Typography>
            ) : (
              <>
                <Typography variant="body2" sx={{ mt: 0.5, mb: 1 }}>
                  {report.comparison.scope_note}
                </Typography>
                <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
                  {report.comparison.previous_label} compared with {report.comparison.current_label}
                  {report.comparison.duration_mismatch ? " · different lengths, so per-week figures are shown" : ""}
                </Typography>
                <ComparisonTable rows={report.comparison.rows} mismatch={report.comparison.duration_mismatch} />
                {report.employee_detail && report.comparison.employees?.length ? (
                  <Box sx={{ mt: 1.5 }}>
                    <FormControl size="small" sx={{ minWidth: 240, mb: 1 }}>
                      <InputLabel>Employee comparison</InputLabel>
                      <Select
                        label="Employee comparison"
                        value={compareEmployeeId}
                        onChange={(e) => setCompareEmployeeId(e.target.value)}
                      >
                        <MenuItem value="">Select an employee</MenuItem>
                        {report.comparison.employees.map((item) => (
                          <MenuItem key={`${item.user_id}-${item.classification_label}`} value={`${item.user_id}|${item.classification_label}`}>
                            {item.employee_name} ({item.classification_label})
                          </MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                    {selectedCompareEmployee ? (
                      <ComparisonTable rows={selectedCompareEmployee.rows} mismatch={report.comparison.duration_mismatch} />
                    ) : null}
                  </Box>
                ) : null}
              </>
            )}
          </Paper>

          <Paper variant="outlined" sx={{ p: 1.5 }}>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }} sx={{ mb: 1 }}>
              <Box sx={{ flex: 1 }}>
                <Typography variant="subtitle1" fontWeight={700}>
                  Employees
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  Select a row for the employee period trend. The target color is for this employee.
                </Typography>
              </Box>
              <TextField size="small" label="Search name" value={search} onChange={(e) => setSearch(e.target.value)} />
              <Button size="small" variant="outlined" onClick={(e) => setColumnAnchor(e.currentTarget)}>
                Columns
              </Button>
              <Button size="small" variant="outlined" startIcon={<FileDownloadIcon />} onClick={downloadCsv} disabled={!employees.length}>
                CSV
              </Button>
            </Stack>
            <Menu anchorEl={columnAnchor} open={Boolean(columnAnchor)} onClose={() => setColumnAnchor(null)}>
              {LABOR_COLUMNS.filter((col) => col.optional).map((col) => (
                <MenuItem
                  key={col.key}
                  onClick={() =>
                    setOptionalKeys((prev) =>
                      prev.includes(col.key) ? prev.filter((key) => key !== col.key) : [...prev, col.key],
                    )
                  }
                >
                  <Checkbox size="small" checked={optionalKeys.includes(col.key)} />
                  {col.label}
                </MenuItem>
              ))}
            </Menu>
            {!report.employee_detail ? (
              <Typography variant="body2" color="text.secondary">
                Employee rows are available to people who can view employee payroll detail.
              </Typography>
            ) : (
              <TableContainer sx={{ overflowX: "auto" }}>
                <Table size="small" stickyHeader sx={{ minWidth: 980 }}>
                  <TableHead>
                    <TableRow>
                      {visibleColumns.map((col) => (
                        <TableCell
                          key={col.key}
                          align={col.numeric ? "right" : "left"}
                          sx={{ cursor: "pointer", whiteSpace: "nowrap" }}
                          onClick={() => toggleSort(col.key)}
                        >
                          {col.label}
                          {sort.key === col.key ? (sort.dir === "asc" ? " ↑" : " ↓") : ""}
                        </TableCell>
                      ))}
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {employees.map((emp) => {
                      const rowKey = `${emp.user_id}-${emp.worker_category}`;
                      const open = expandedId === rowKey;
                      return (
                        <Fragment key={rowKey}>
                          <TableRow
                            hover
                            onClick={() => setExpandedId(open ? null : `${emp.user_id}-${emp.worker_category}`)}
                            sx={{ cursor: "pointer" }}
                          >
                            {visibleColumns.map((col) => (
                              <TableCell
                                key={col.key}
                                align={col.numeric ? "right" : "left"}
                                sx={{
                                  whiteSpace: "nowrap",
                                  color:
                                    col.key === "employer_effective_rate" || col.key === "target_delta_per_hour"
                                      ? hourlyTargetColor({
                                          effective_cost_per_hour: emp.employer_effective_rate,
                                          target_status: emp.target_status,
                                        })
                                      : "inherit",
                                }}
                              >
                                {col.key === "employee_effective_rate" && emp.employee_rate_label === "Worker Gross Rate"
                                  ? formatColumnValue(col, emp)
                                  : col.key === "employer_burden_percent"
                                    ? `${formatPercent(emp.employer_burden_percent)} ${emp.employer_burden_label || ""}`.trim()
                                    : col.key === "base_wage" && emp.base_wage_blended
                                      ? `${formatRate(emp.base_wage)} blended`
                                      : formatColumnValue(col, emp)}
                              </TableCell>
                            ))}
                          </TableRow>
                          {open ? (
                            <TableRow>
                              <TableCell colSpan={visibleColumns.length}>
                                <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
                                  This employee versus the {formatRate(emp.labor_cost_target)} target.{" "}
                                  {targetPhrase(emp)}. One employee over the target does not mean the team average is over the target.
                                  Rates use this employee's historical payroll, not today's profile rate.
                                </Typography>
                                {emp.periods?.length ? (
                                  <Box sx={{ width: "100%", height: 160, mb: 1 }}>
                                    <ResponsiveContainer>
                                      <LineChart data={emp.periods}>
                                        <XAxis dataKey="label" tick={{ fontSize: 10 }} />
                                        <YAxis tick={{ fontSize: 10 }} />
                                        <ChartTooltip />
                                        <Line
                                          type="monotone"
                                          dataKey="employer_effective_rate"
                                          name="Employer cost/hr"
                                          stroke={VEEWASH_BRAND.primary}
                                          dot
                                        />
                                      </LineChart>
                                    </ResponsiveContainer>
                                  </Box>
                                ) : (
                                  <Typography variant="body2">No period detail in this range.</Typography>
                                )}
                                {emp.classifications?.length > 1 ? (
                                  <Box sx={{ mb: 1 }}>
                                    <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
                                      Weekly overtime is calculated once for the whole week. These rows show which classification worked those hours.
                                      Estimated employer burden is not a stored payroll tax.
                                    </Typography>
                                    <Table size="small">
                                      <TableHead>
                                        <TableRow>
                                          <TableCell>Classification</TableCell>
                                          <TableCell align="right">Hours</TableCell>
                                          <TableCell align="right">OT hours</TableCell>
                                          <TableCell align="right">OT %</TableCell>
                                          <TableCell align="right">OT premium</TableCell>
                                          <TableCell align="right">Employer cost</TableCell>
                                          <TableCell align="right">Burden</TableCell>
                                        </TableRow>
                                      </TableHead>
                                      <TableBody>
                                        {emp.classifications.map((item) => (
                                          <TableRow key={item.worker_category}>
                                            <TableCell>{item.classification_label}</TableCell>
                                            <TableCell align="right">{formatHours(item.payable_hours)}</TableCell>
                                            <TableCell align="right">{formatHours(item.ot_hours)}</TableCell>
                                            <TableCell align="right">{formatPercent(item.ot_percent)}</TableCell>
                                            <TableCell align="right">{formatMoney(item.ot_premium)}</TableCell>
                                            <TableCell align="right">{formatMoney(item.total_employer_cost)}</TableCell>
                                            <TableCell align="right">
                                              {formatPercent(item.employer_burden_percent)} {item.employer_burden_label || ""}
                                            </TableCell>
                                          </TableRow>
                                        ))}
                                      </TableBody>
                                    </Table>
                                  </Box>
                                ) : null}
                                {emp.periods?.length ? (
                                  <Table size="small">
                                    <TableHead>
                                      <TableRow>
                                        <TableCell>Period</TableCell>
                                        <TableCell align="right">OT hours</TableCell>
                                        <TableCell align="right">OT %</TableCell>
                                        <TableCell align="right">OT premium</TableCell>
                                        <TableCell align="right">Burden</TableCell>
                                        <TableCell align="right">Employer cost/hr</TableCell>
                                        <TableCell align="right">Vs previous</TableCell>
                                      </TableRow>
                                    </TableHead>
                                    <TableBody>
                                      {emp.periods.map((period) => (
                                        <TableRow key={`${period.start}-${period.end}`}>
                                          <TableCell>{period.label}</TableCell>
                                          <TableCell align="right">{formatHours(period.ot_hours)}</TableCell>
                                          <TableCell align="right">{formatPercent(period.ot_percent)}</TableCell>
                                          <TableCell align="right">{formatMoney(period.ot_premium)}</TableCell>
                                          <TableCell align="right">
                                            {formatPercent(period.employer_burden_percent)} {period.employer_burden_label || ""}
                                          </TableCell>
                                          <TableCell align="right">{formatRate(period.employer_effective_rate)}</TableCell>
                                          <TableCell align="right">
                                            {period.delta_vs_previous
                                              ? `${formatImpact(period.delta_vs_previous.employer_effective_rate)}/hr · OT hours ${formatImpactHours(period.delta_vs_previous.ot_hours)}`
                                              : "—"}
                                          </TableCell>
                                        </TableRow>
                                      ))}
                                    </TableBody>
                                  </Table>
                                ) : null}
                              </TableCell>
                            </TableRow>
                          ) : null}
                        </Fragment>
                      );
                    })}
                    {!employees.length ? (
                      <TableRow>
                        <TableCell colSpan={visibleColumns.length}>
                          <Typography variant="body2" color="text.secondary">
                            No employees in this selection.
                          </Typography>
                        </TableCell>
                      </TableRow>
                    ) : null}
                  </TableBody>
                </Table>
              </TableContainer>
            )}
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
              {definitions.weighted_average}
            </Typography>
          </Paper>
        </>
      ) : null}
    </Box>
  );
}

function formatChartValue(kind, value) {
  if (kind === "hours") return formatHours(value);
  if (kind === "percent") return formatPercent(value);
  if (kind === "money") return formatMoney(value);
  return formatRate(value);
}

function formatImpactHours(value) {
  if (value == null) return "—";
  const n = Number(value);
  const sign = n > 0 ? "+" : "";
  return `${sign}${formatHours(n)}`;
}
