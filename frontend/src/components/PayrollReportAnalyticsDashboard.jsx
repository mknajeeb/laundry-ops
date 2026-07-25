import { useState } from "react";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  FormControl,
  InputLabel,
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
  Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import TrendingDownIcon from "@mui/icons-material/TrendingDown";
import TrendingFlatIcon from "@mui/icons-material/TrendingFlat";
import TrendingUpIcon from "@mui/icons-material/TrendingUp";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { VEEWASH_BRAND } from "../theme/veewashBrand";

function money(v) {
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function hours(v) {
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function pct(v) {
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return `${n.toFixed(2)}%`;
}

function formatValue(kind, v) {
  if (kind === "money") return money(v);
  if (kind === "hours") return hours(v);
  if (v == null) return "—";
  return String(v);
}

function TrendIcon({ direction }) {
  if (direction === "up") return <TrendingUpIcon sx={{ fontSize: 14, color: VEEWASH_BRAND.inkMuted }} />;
  if (direction === "down") return <TrendingDownIcon sx={{ fontSize: 14, color: VEEWASH_BRAND.inkMuted }} />;
  return <TrendingFlatIcon sx={{ fontSize: 14, color: VEEWASH_BRAND.inkSoft }} />;
}

function deltaLine(card) {
  if (card?.diff == null) return "vs prior —";
  const sign = card.diff > 0 ? "+" : "";
  const abs = formatValue(card.kind, Math.abs(card.diff));
  const signed = `${sign}${card.kind === "count" ? Math.abs(card.diff) : abs}`;
  if (card.pct == null) return signed;
  return `${signed} (${sign}${Number(card.pct).toFixed(1)}%)`;
}

function directionFor(diff) {
  if (diff == null || Math.abs(diff) < 0.005) return "flat";
  return diff > 0 ? "up" : "down";
}

/** Compact KPI card — no giant panels, just the number + a one-line delta. */
function KpiCard({ card }) {
  return (
    <Paper
      variant="outlined"
      sx={{
        p: 1.25,
        height: "100%",
        borderColor: VEEWASH_BRAND.borderSoft,
        background: "linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)",
      }}
    >
      <Typography
        variant="caption"
        sx={{ color: VEEWASH_BRAND.inkSoft, letterSpacing: 0.3, textTransform: "uppercase" }}
      >
        {card.label}
      </Typography>
      <Typography variant="h6" fontWeight={800} sx={{ color: VEEWASH_BRAND.ink, mt: 0.25, lineHeight: 1.15 }}>
        {formatValue(card.kind, card.current ?? card.value)}
      </Typography>
      <Stack direction="row" spacing={0.5} alignItems="center" sx={{ mt: 0.5 }}>
        <TrendIcon direction={card.direction} />
        <Typography variant="caption" fontWeight={600} sx={{ color: VEEWASH_BRAND.inkMuted }}>
          {deltaLine(card)}
        </Typography>
      </Stack>
    </Paper>
  );
}

/** Small OT chip-card used in the compact OT row (not a giant blue panel). */
function OtChip({ label, value, previous, kind, diff, diffPct }) {
  const direction = directionFor(diff);
  return (
    <Paper
      variant="outlined"
      sx={{
        p: 1.1,
        flex: 1,
        minWidth: 0,
        borderColor: VEEWASH_BRAND.borderSoft,
        background: VEEWASH_BRAND.primaryLight,
      }}
    >
      <Typography variant="caption" sx={{ color: VEEWASH_BRAND.inkSoft, textTransform: "uppercase" }}>
        {label}
      </Typography>
      <Typography variant="subtitle1" fontWeight={800} sx={{ color: VEEWASH_BRAND.ink, lineHeight: 1.2 }}>
        {kind === "pct" ? pct(value) : kind === "money" ? money(value) : hours(value)}
      </Typography>
      {previous != null ? (
        <Stack direction="row" spacing={0.5} alignItems="center" sx={{ mt: 0.25 }}>
          <TrendIcon direction={direction} />
          <Typography variant="caption" sx={{ color: VEEWASH_BRAND.inkMuted }}>
            {deltaLine({ diff, pct: diffPct, kind: kind === "pct" ? "hours" : kind })}
          </Typography>
        </Stack>
      ) : null}
    </Paper>
  );
}

function ChartCard({ title, children, height = 220 }) {
  return (
    <Paper variant="outlined" sx={{ p: 1.25, height: "100%", borderColor: VEEWASH_BRAND.borderSoft }}>
      <Typography variant="subtitle2" fontWeight={700} sx={{ color: VEEWASH_BRAND.primaryDark, mb: 0.75 }}>
        {title}
      </Typography>
      <Box sx={{ width: "100%", height }}>
        <ResponsiveContainer>{children}</ResponsiveContainer>
      </Box>
    </Paper>
  );
}

function SectionTitle({ children }) {
  return (
    <Typography variant="subtitle1" fontWeight={800} sx={{ color: VEEWASH_BRAND.primaryDark }}>
      {children}
    </Typography>
  );
}

const WORKFORCE_HEADERS = [
  "Category",
  "HC",
  "% Cost",
  "Regular Hrs",
  "OT Hrs",
  "Regular/Base Earnings",
  "OT Premium",
  "Gross",
  "Employer Tax",
  "Total Cost",
  "Avg Employer Cost",
];

const RECON_HEADERS = ["Category", "Base Earnings", "OT Premium"];

const EMPLOYEE_HEADERS = [
  "Employee",
  "Reg Hrs",
  "OT Hrs",
  "Regular/Base Earnings",
  "OT Premium",
  "Gross",
  "Total Cost",
];

function pctDelta(v) {
  if (v == null || !Number.isFinite(Number(v))) return "—";
  const n = Number(v);
  return `${n >= 0 ? "+" : ""}${n.toFixed(1)}%`;
}

/**
 * Payroll Dashboard v4 — report-aware month vs period comparison.
 */
export default function PayrollReportAnalyticsDashboard({
  analytics,
  summary,
  compareWith,
  trendRange,
  onCompareWithChange,
  onTrendRangeChange,
  onSelectEmployee,
}) {
  const [drillCategory, setDrillCategory] = useState(null);
  const [permissionNotice, setPermissionNotice] = useState(false);

  const mode = analytics?.comparison_mode || (analytics?.month_comparison?.length ? "month" : "period");
  const isMonth = mode === "month";
  const kpis = analytics?.kpis || [];
  const ot = analytics?.ot_summary;
  const narrative = analytics?.executive_narrative;
  const categories = analytics?.category_breakdown || [];
  const trendRows = isMonth
    ? analytics?.month_comparison || []
    : analytics?.period_comparison || [];
  const mix = analytics?.employment_mix || [];
  const chartTitles = analytics?.chart_titles || {};
  const compareOptions = analytics?.compare_with_options || [];
  const trendOptions = analytics?.trend_range_options || (isMonth ? [3, 4, 6, 12] : [3, 4, 5, 8]);
  const employeeSummariesByCategory = analytics?.employee_summaries_by_category || {};
  const canViewDetail = analytics?.access?.can_view_employee_detail !== false;

  const chartData = trendRows.map((p) => ({
    ...p,
    label: isMonth
      ? String(p.label || p.month || "").replace(/ \(month to date\)/, "").slice(0, 8)
      : String(p.pay_period_end || p.payroll_period || "").slice(5),
    fullLabel: p.label || p.payroll_period,
  }));
  const mixData = mix.map((p) => ({
    ...p,
    label: isMonth
      ? String(p.label || p.month || "").slice(0, 8)
      : String(p.pay_period_end || p.payroll_period || "").slice(5),
    fullLabel: p.label || p.payroll_period,
  }));

  const costTooltip = (value, name, item) => {
    const payload = item?.payload || {};
    if (name === "Gross" || name === "Gross Payroll") {
      return [
        `${money(value)} (Base ${money(payload.base_earnings)} + OT Prem ${money(payload.ot_premium)})`,
        "Gross Payroll",
      ];
    }
    return [money(value), name];
  };

  const drillCategoryLabel =
    categories.find((c) => c.worker_category === drillCategory)?.label || drillCategory;
  const drillEmployees = drillCategory ? employeeSummariesByCategory[drillCategory] || [] : [];

  const handleCategoryClick = (categoryKey) => {
    if (!canViewDetail) {
      setPermissionNotice(true);
      return;
    }
    setPermissionNotice(false);
    setDrillCategory(categoryKey);
  };

  const handleBack = () => {
    setDrillCategory(null);
    setPermissionNotice(false);
  };

  const handleEmployeeClick = (emp) => {
    if (typeof onSelectEmployee === "function") {
      onSelectEmployee(emp.user_id, emp.employee_name);
    }
  };

  const compareValue = compareWith || analytics?.compare_with || (isMonth ? "previous_month" : "previous_period");
  const trendValue = trendRange || analytics?.trend_range || 4;

  return (
    <Stack spacing={2} sx={{ mb: 1 }}>
      <Stack
        direction={{ xs: "column", sm: "row" }}
        justifyContent="space-between"
        alignItems={{ xs: "stretch", sm: "center" }}
        spacing={1}
      >
        <Box>
          <Typography variant="h6" fontWeight={700} sx={{ color: VEEWASH_BRAND.primaryDark }}>
            Payroll Dashboard
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {summary?.focus_period
              ? `Focus: ${summary.focus_period}${
                  summary?.previous_period ? ` · Previous: ${summary.previous_period}` : ""
                }`
              : isMonth
                ? "Select a month with Official Pay Date payroll."
                : "No complete payroll period in selection (all batches must be paid or finalized)."}
          </Typography>
        </Box>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
          <FormControl size="small" sx={{ minWidth: 200 }}>
            <InputLabel>Compare</InputLabel>
            <Select
              label="Compare"
              value={compareValue}
              onChange={(e) => onCompareWithChange?.(e.target.value)}
            >
              {(compareOptions.length
                ? compareOptions
                : isMonth
                  ? [
                      { value: "previous_month", label: "Previous month" },
                      { value: "same_month_last_year", label: "Same month last year" },
                    ]
                  : [
                      { value: "previous_period", label: "Previous payroll period" },
                      { value: "same_period_4_weeks_earlier", label: "Same period 4 weeks earlier" },
                    ]
              ).map((o) => (
                <MenuItem key={o.value} value={o.value}>{o.label}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl size="small" sx={{ minWidth: 180 }}>
            <InputLabel>Show Trend</InputLabel>
            <Select
              label="Show Trend"
              value={trendValue}
              onChange={(e) => onTrendRangeChange?.(Number(e.target.value))}
            >
              {trendOptions.map((n) => (
                <MenuItem key={n} value={n}>
                  {isMonth ? `Last ${n} Months` : `Last ${n} Periods`}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </Stack>
      </Stack>

      {narrative?.text ? (
        <Paper
          variant="outlined"
          sx={{ p: 1.5, borderColor: VEEWASH_BRAND.borderSoft, background: VEEWASH_BRAND.primaryLight }}
        >
          <Typography variant="subtitle2" fontWeight={700} sx={{ color: VEEWASH_BRAND.primaryDark }}>
            {narrative.headline}
          </Typography>
          {narrative.drivers?.length ? (
            <Stack component="ul" sx={{ m: 0, pl: 2.5, mt: 0.5 }}>
              {narrative.drivers.map((d) => (
                <Typography component="li" key={d} variant="body2" color="text.secondary">
                  {d}
                </Typography>
              ))}
            </Stack>
          ) : null}
        </Paper>
      ) : null}

      {/* 1. KPI row */}
      <Box
        sx={{
          display: "grid",
          gap: 1,
          gridTemplateColumns: {
            xs: "1fr 1fr",
            sm: "repeat(3, 1fr)",
            md: "repeat(3, 1fr)",
            lg: "repeat(6, 1fr)",
          },
        }}
      >
        {kpis.map((card) => (
          <KpiCard key={card.key} card={card} />
        ))}
      </Box>

      {/* 2. Compact OT row — three small chips, not a giant panel */}
      {ot ? (
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
          <OtChip
            label="OT Hours"
            value={ot.ot_hours}
            kind="hours"
            previous={ot.previous_ot_hours}
            diff={ot.diff ?? ot.ot_hours_diff}
            diffPct={ot.pct ?? ot.ot_hours_pct}
          />
          <OtChip label="OT % of Hours" value={ot.ot_pct_of_hours} kind="pct" previous={null} />
          <OtChip
            label="OT Premium"
            value={ot.ot_premium}
            kind="money"
            previous={ot.previous_ot_premium}
            diff={ot.ot_premium_diff}
            diffPct={ot.ot_premium_pct}
          />
        </Stack>
      ) : null}

      {drillCategory ? (
        <Box>
          <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
            <Button
              size="small"
              startIcon={<ArrowBackIcon />}
              onClick={handleBack}
              sx={{ color: VEEWASH_BRAND.primaryDark }}
            >
              Back
            </Button>
            <SectionTitle>Employee Summary — {drillCategoryLabel}</SectionTitle>
          </Stack>
          {!canViewDetail ? (
            <Alert severity="warning">You do not have permission to view employee payroll details.</Alert>
          ) : (
            <Paper variant="outlined" sx={{ borderColor: VEEWASH_BRAND.borderSoft }}>
              <TableContainer sx={{ overflowX: "auto" }}>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      {EMPLOYEE_HEADERS.map((h) => (
                        <TableCell key={h} sx={{ whiteSpace: "nowrap", color: VEEWASH_BRAND.primaryDark, fontWeight: 700 }}>
                          {h}
                        </TableCell>
                      ))}
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {drillEmployees.map((emp) => (
                      <TableRow
                        key={emp.user_id ?? emp.employee_name}
                        hover
                        onClick={() => handleEmployeeClick(emp)}
                        sx={{ cursor: typeof onSelectEmployee === "function" ? "pointer" : "default" }}
                      >
                        <TableCell>{emp.employee_name}</TableCell>
                        <TableCell align="right">{hours(emp.regular_hours)}</TableCell>
                        <TableCell align="right">{hours(emp.ot_hours)}</TableCell>
                        <TableCell align="right">{money(emp.base_earnings)}</TableCell>
                        <TableCell align="right">{money(emp.ot_premium)}</TableCell>
                        <TableCell align="right">{money(emp.gross_pay)}</TableCell>
                        <TableCell align="right">{money(emp.total_payroll_cost)}</TableCell>
                      </TableRow>
                    ))}
                    {drillEmployees.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={EMPLOYEE_HEADERS.length} sx={{ color: VEEWASH_BRAND.inkSoft }}>
                          No employees in this category.
                        </TableCell>
                      </TableRow>
                    ) : null}
                  </TableBody>
                </Table>
              </TableContainer>
            </Paper>
          )}
        </Box>
      ) : (
        <>
          {permissionNotice ? (
            <Alert severity="warning" onClose={() => setPermissionNotice(false)}>
              You do not have permission to view employee payroll details.
            </Alert>
          ) : null}

          {/* 3. Workforce Breakdown */}
          <Box>
            <SectionTitle>Workforce Breakdown</SectionTitle>
            <Paper variant="outlined" sx={{ mt: 1, borderColor: VEEWASH_BRAND.borderSoft }}>
              <TableContainer sx={{ overflowX: "auto" }}>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      {WORKFORCE_HEADERS.map((h) => (
                        <TableCell key={h} sx={{ whiteSpace: "nowrap", color: VEEWASH_BRAND.primaryDark, fontWeight: 700 }}>
                          {h}
                        </TableCell>
                      ))}
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {categories.map((c) => (
                      <TableRow
                        key={c.worker_category}
                        hover
                        onClick={() => handleCategoryClick(c.worker_category)}
                        sx={{ cursor: "pointer" }}
                      >
                        <TableCell sx={{ color: VEEWASH_BRAND.primaryDark, fontWeight: 600 }}>
                          {c.label || c.worker_category}
                        </TableCell>
                        <TableCell align="right">{c.head_count ?? c.worker_count ?? 0}</TableCell>
                        <TableCell align="right">
                          {c.pct_of_total_cost == null ? "—" : `${Number(c.pct_of_total_cost).toFixed(1)}%`}
                        </TableCell>
                        <TableCell align="right">{hours(c.regular_hours)}</TableCell>
                        <TableCell align="right">{hours(c.ot_hours)}</TableCell>
                        <TableCell align="right">{money(c.base_earnings)}</TableCell>
                        <TableCell align="right">{money(c.ot_premium)}</TableCell>
                        <TableCell align="right">{money(c.gross_pay)}</TableCell>
                        <TableCell align="right">{money(c.employer_taxes)}</TableCell>
                        <TableCell align="right">{money(c.total_payroll_cost)}</TableCell>
                        <TableCell align="right">{money(c.avg_cost_per_hour)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </Paper>
          </Box>

          {/* 4. Earnings reconciliation — collapsed by default, for auditors */}
          <Accordion
            disableGutters
            variant="outlined"
            sx={{ borderColor: VEEWASH_BRAND.borderSoft, "&:before": { display: "none" } }}
          >
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="subtitle2" fontWeight={700} sx={{ color: VEEWASH_BRAND.primaryDark }}>
                Earnings reconciliation (straight-time + OT premium)
              </Typography>
            </AccordionSummary>
            <AccordionDetails sx={{ pt: 0 }}>
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      {RECON_HEADERS.map((h) => (
                        <TableCell key={h} sx={{ whiteSpace: "nowrap", color: VEEWASH_BRAND.primaryDark, fontWeight: 700 }}>
                          {h}
                        </TableCell>
                      ))}
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {categories.map((c) => (
                      <TableRow key={c.worker_category}>
                        <TableCell>{c.label || c.worker_category}</TableCell>
                        <TableCell align="right">{money(c.base_earnings)}</TableCell>
                        <TableCell align="right">{money(c.ot_premium)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </AccordionDetails>
          </Accordion>

          {/* 5. Trends — four charts only */}
          <Box>
            <SectionTitle>Trends</SectionTitle>
            <Box
              sx={{
                mt: 1,
                display: "grid",
                gap: 1.25,
                gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" },
              }}
            >
              <ChartCard title={chartTitles.cost || (isMonth ? "Monthly Payroll Cost Trend" : "Payroll Cost by Period")}>
                <AreaChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `$${Number(v) / 1000}k`} />
                  <Tooltip formatter={costTooltip} labelFormatter={(_, p) => p?.[0]?.payload?.fullLabel} />
                  <Legend />
                  <Area type="monotone" dataKey="total_payroll_cost" name="Total cost" stroke="#007a91" fill="#0097b233" />
                  <Area type="monotone" dataKey="gross_pay" name="Gross Payroll" stroke="#0097b2" fill="transparent" />
                </AreaChart>
              </ChartCard>
              <ChartCard title={chartTitles.hours || (isMonth ? "Monthly Hours Trend" : "Hours by Period")}>
                <BarChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip
                    formatter={(v, name) => [hours(v), name]}
                    labelFormatter={(_, p) => p?.[0]?.payload?.fullLabel}
                  />
                  <Legend />
                  <Bar dataKey="regular_hours" name="Regular" stackId="h" fill="#0097b2" />
                  <Bar dataKey="ot_hours" name="OT" stackId="h" fill="#c4a052" />
                </BarChart>
              </ChartCard>
              <ChartCard title={chartTitles.mix || (isMonth ? "Monthly Employment Mix" : "Employment Mix by Period")}>
                <BarChart data={mixData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `$${Number(v) / 1000}k`} />
                  <Tooltip formatter={(v) => money(v)} labelFormatter={(_, p) => p?.[0]?.payload?.fullLabel} />
                  <Legend />
                  <Bar dataKey="w2_gross" name="W-2 gross" stackId="m" fill="#007a91" />
                  <Bar dataKey="w2_employer_taxes" name="ER taxes" stackId="m" fill="#64748b" />
                  <Bar dataKey="temp_cost" name="Temp" stackId="m" fill="#c4a052" />
                  <Bar dataKey="contractor_1099_cost" name="1099" stackId="m" fill="#94a3b8" />
                </BarChart>
              </ChartCard>
              <ChartCard title={chartTitles.cost_per_hour || (isMonth ? "Monthly Average Employer Cost/Hour" : "Average Employer Cost/Hour by Period")}>
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => money(v)} />
                  <Tooltip formatter={(v) => money(v)} labelFormatter={(_, p) => p?.[0]?.payload?.fullLabel} />
                  <Legend />
                  <Line
                    type="monotone"
                    dataKey="avg_cost_per_hour"
                    name="Avg Employer Cost"
                    stroke="#007a91"
                    strokeWidth={2}
                    dot
                  />
                </LineChart>
              </ChartCard>
            </Box>
          </Box>

          {/* Comparison table with deltas */}
          <Paper variant="outlined" sx={{ borderColor: VEEWASH_BRAND.borderSoft }}>
            <Box sx={{ px: 1.5, py: 1 }}>
              <Typography variant="subtitle2" fontWeight={700} sx={{ color: VEEWASH_BRAND.primaryDark }}>
                {isMonth ? "Month comparison" : "Period comparison"}
              </Typography>
            </Box>
            <TableContainer sx={{ overflowX: "auto" }}>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell sx={{ whiteSpace: "nowrap", color: VEEWASH_BRAND.primaryDark }}>
                      {isMonth ? "Month / Period" : "Payroll Period"}
                    </TableCell>
                    <TableCell sx={{ whiteSpace: "nowrap", color: VEEWASH_BRAND.primaryDark }}>
                      Pay Date(s)
                    </TableCell>
                    <TableCell align="right" sx={{ color: VEEWASH_BRAND.primaryDark }}>Cost</TableCell>
                    <TableCell align="right" sx={{ color: VEEWASH_BRAND.primaryDark }}>Δ</TableCell>
                    <TableCell align="right" sx={{ color: VEEWASH_BRAND.primaryDark }}>Hours</TableCell>
                    <TableCell align="right" sx={{ color: VEEWASH_BRAND.primaryDark }}>Δ</TableCell>
                    <TableCell align="right" sx={{ color: VEEWASH_BRAND.primaryDark }}>HC</TableCell>
                    <TableCell align="right" sx={{ color: VEEWASH_BRAND.primaryDark }}>OT</TableCell>
                    <TableCell align="right" sx={{ color: VEEWASH_BRAND.primaryDark }}>Gross</TableCell>
                    <TableCell align="right" sx={{ color: VEEWASH_BRAND.primaryDark }}>Avg $/hr</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {trendRows.map((p) => {
                    const costPct = p.pct_from_previous?.total_payroll_cost;
                    const hrsPct = p.pct_from_previous?.total_hours;
                    const nestedPeriods = isMonth ? p.periods || [] : [];
                    const monthKey = p.label || p.payroll_period || p.month;
                    return [
                      <TableRow key={monthKey} hover sx={{ "& td": { fontWeight: isMonth ? 600 : 400 } }}>
                        <TableCell sx={{ whiteSpace: "nowrap" }}>
                          {p.label || p.payroll_period}
                        </TableCell>
                        <TableCell sx={{ whiteSpace: "nowrap", color: VEEWASH_BRAND.inkMuted, fontSize: 12 }}>
                          {p.pay_dates_label || "—"}
                        </TableCell>
                        <TableCell align="right">{money(p.total_payroll_cost)}</TableCell>
                        <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                          {pctDelta(costPct)}
                        </TableCell>
                        <TableCell align="right">{hours(p.total_hours)}</TableCell>
                        <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                          {pctDelta(hrsPct)}
                        </TableCell>
                        <TableCell align="right">{p.worker_count ?? p.head_count ?? 0}</TableCell>
                        <TableCell align="right">{hours(p.ot_hours)}</TableCell>
                        <TableCell align="right">{money(p.gross_pay)}</TableCell>
                        <TableCell align="right">{money(p.avg_cost_per_hour)}</TableCell>
                      </TableRow>,
                      ...nestedPeriods.map((per) => (
                        <TableRow
                          key={`${monthKey}-${per.pay_period_start}-${per.pay_period_end}`}
                          hover
                          sx={{ bgcolor: "rgba(0,122,145,0.03)" }}
                        >
                          <TableCell sx={{ whiteSpace: "nowrap", pl: 3, color: VEEWASH_BRAND.inkMuted }}>
                            {per.label || per.payroll_period}
                          </TableCell>
                          <TableCell sx={{ whiteSpace: "nowrap", color: VEEWASH_BRAND.inkMuted, fontSize: 12 }}>
                            {per.pay_dates_label || "—"}
                          </TableCell>
                          <TableCell align="right">{money(per.total_payroll_cost)}</TableCell>
                          <TableCell align="right">—</TableCell>
                          <TableCell align="right">{hours(per.total_hours)}</TableCell>
                          <TableCell align="right">—</TableCell>
                          <TableCell align="right">{per.worker_count ?? per.head_count ?? 0}</TableCell>
                          <TableCell align="right">{hours(per.ot_hours)}</TableCell>
                          <TableCell align="right">{money(per.gross_pay)}</TableCell>
                          <TableCell align="right">{money(per.avg_cost_per_hour)}</TableCell>
                        </TableRow>
                      )),
                    ];
                  })}
                </TableBody>
              </Table>
            </TableContainer>
          </Paper>
        </>
      )}
    </Stack>
  );
}
