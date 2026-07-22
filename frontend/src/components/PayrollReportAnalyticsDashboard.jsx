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
  "Regular Hrs",
  "OT Hrs",
  "Regular Earnings",
  "OT Earnings",
  "Gross",
  "Employer Tax",
  "Total Cost",
  "Avg Pay Rate",
  "Avg Employer Cost",
];

const RECON_HEADERS = ["Category", "Base Earnings", "OT Premium"];

const EMPLOYEE_HEADERS = ["Employee", "Reg Hrs", "OT Hrs", "Regular Earnings", "OT Earnings", "Gross", "Total Cost"];

const PERIOD_HEADERS = ["Payroll Period", "Workers", "Hours", "OT", "Gross", "Total cost", "Avg Pay", "Avg Employer Cost", "Δ cost"];

/**
 * Payroll Dashboard v3 — compact executive management dashboard.
 * KPI row → OT chips → Workforce Breakdown (drill-down) → reconciliation
 * accordion → four trend charts → compact period comparison.
 */
export default function PayrollReportAnalyticsDashboard({
  analytics,
  summary,
  comparisonRange,
  onComparisonRangeChange,
  onSelectEmployee,
}) {
  const [drillCategory, setDrillCategory] = useState(null);
  const [permissionNotice, setPermissionNotice] = useState(false);

  const kpis = analytics?.kpis || [];
  const ot = analytics?.ot_summary;
  const categories = analytics?.category_breakdown || [];
  const periods = analytics?.period_comparison || [];
  const mix = analytics?.employment_mix || [];
  const employeeSummariesByCategory = analytics?.employee_summaries_by_category || {};
  const canViewDetail = analytics?.access?.can_view_employee_detail !== false;

  const chartData = periods.map((p) => ({
    ...p,
    label: String(p.pay_period_end || p.payroll_period || "").slice(5),
    fullLabel: p.payroll_period,
  }));
  const mixData = mix.map((p) => ({
    ...p,
    label: String(p.pay_period_end || p.payroll_period || "").slice(5),
    fullLabel: p.payroll_period,
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
            Focus: {summary?.focus_period || "selected report"}
            {summary?.previous_period ? ` · vs ${summary.previous_period}` : ""}
          </Typography>
        </Box>
        <FormControl size="small" sx={{ minWidth: 180 }}>
          <InputLabel>Comparison range</InputLabel>
          <Select
            label="Comparison range"
            value={comparisonRange || analytics?.comparison_range || 4}
            onChange={(e) => onComparisonRangeChange?.(Number(e.target.value))}
          >
            <MenuItem value={4}>Last 4 periods</MenuItem>
            <MenuItem value={8}>Last 8 periods</MenuItem>
            <MenuItem value={12}>Last 12 periods</MenuItem>
          </Select>
        </FormControl>
      </Stack>

      {/* 1. KPI row — six cards only */}
      <Box
        sx={{
          display: "grid",
          gap: 1,
          gridTemplateColumns: { xs: "1fr 1fr", sm: "repeat(3, 1fr)", md: "repeat(6, 1fr)" },
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
            label="OT Earnings"
            value={ot.ot_earnings}
            kind="money"
            previous={ot.previous_ot_earnings}
            diff={ot.ot_earnings_diff}
            diffPct={ot.ot_earnings_pct}
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
                        <TableCell align="right">{money(emp.regular_earnings)}</TableCell>
                        <TableCell align="right">{money(emp.ot_earnings)}</TableCell>
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
                        <TableCell align="right">{hours(c.regular_hours)}</TableCell>
                        <TableCell align="right">{hours(c.ot_hours)}</TableCell>
                        <TableCell align="right">{money(c.regular_earnings)}</TableCell>
                        <TableCell align="right">{money(c.ot_earnings)}</TableCell>
                        <TableCell align="right">{money(c.gross_pay)}</TableCell>
                        <TableCell align="right">{money(c.employer_taxes)}</TableCell>
                        <TableCell align="right">{money(c.total_payroll_cost)}</TableCell>
                        <TableCell align="right">{money(c.avg_pay_rate ?? c.avg_rate)}</TableCell>
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
              <ChartCard title="Payroll cost trend">
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
              <ChartCard title="Workforce hours">
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
              <ChartCard title="Employment mix">
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
              <ChartCard title="Average cost / hour trend">
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => money(v)} />
                  <Tooltip formatter={(v) => money(v)} labelFormatter={(_, p) => p?.[0]?.payload?.fullLabel} />
                  <Legend />
                  <Line type="monotone" dataKey="avg_pay_rate" name="Avg Pay Rate" stroke="#0097b2" strokeWidth={2} dot />
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

          {/* 6. Compact period comparison */}
          <Paper variant="outlined" sx={{ borderColor: VEEWASH_BRAND.borderSoft }}>
            <Box sx={{ px: 1.5, py: 1 }}>
              <Typography variant="subtitle2" fontWeight={700} sx={{ color: VEEWASH_BRAND.primaryDark }}>
                Period comparison
              </Typography>
            </Box>
            <TableContainer sx={{ overflowX: "auto" }}>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    {PERIOD_HEADERS.map((h) => (
                      <TableCell key={h} sx={{ whiteSpace: "nowrap", color: VEEWASH_BRAND.primaryDark }}>
                        {h}
                      </TableCell>
                    ))}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {periods.map((p) => {
                    const dCost = p.delta_from_previous?.total_payroll_cost;
                    const pCost = p.pct_from_previous?.total_payroll_cost;
                    return (
                      <TableRow key={p.payroll_period} hover>
                        <TableCell sx={{ whiteSpace: "nowrap" }}>{p.payroll_period}</TableCell>
                        <TableCell align="right">{p.worker_count}</TableCell>
                        <TableCell align="right">{hours(p.total_hours)}</TableCell>
                        <TableCell align="right">{hours(p.ot_hours)}</TableCell>
                        <TableCell align="right">{money(p.gross_pay)}</TableCell>
                        <TableCell align="right">{money(p.total_payroll_cost)}</TableCell>
                        <TableCell align="right">{money(p.avg_pay_rate)}</TableCell>
                        <TableCell align="right">{money(p.avg_cost_per_hour)}</TableCell>
                        <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                          {dCost == null
                            ? "—"
                            : `${dCost >= 0 ? "+" : ""}${money(dCost)}${pCost == null ? "" : ` (${pCost >= 0 ? "+" : ""}${Number(pCost).toFixed(1)}%)`}`}
                        </TableCell>
                      </TableRow>
                    );
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
