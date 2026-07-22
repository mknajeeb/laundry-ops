import {
  Box,
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

function formatValue(kind, v) {
  if (kind === "money") return money(v);
  if (kind === "hours") return hours(v);
  if (v == null) return "—";
  return String(v);
}

function TrendIcon({ direction }) {
  if (direction === "up") return <TrendingUpIcon sx={{ fontSize: 16, color: VEEWASH_BRAND.inkMuted }} />;
  if (direction === "down") return <TrendingDownIcon sx={{ fontSize: 16, color: VEEWASH_BRAND.inkMuted }} />;
  return <TrendingFlatIcon sx={{ fontSize: 16, color: VEEWASH_BRAND.inkSoft }} />;
}

function deltaLine(card) {
  if (card?.diff == null) return "vs prior —";
  const sign = card.diff > 0 ? "+" : "";
  const abs = formatValue(card.kind, Math.abs(card.diff));
  const signed = `${sign}${card.kind === "count" ? Math.abs(card.diff) : abs}`;
  if (card.pct == null) return signed;
  return `${signed} (${sign}${Number(card.pct).toFixed(1)}%)`;
}

function ExecKpiCard({ card }) {
  return (
    <Paper
      variant="outlined"
      sx={{
        p: 1.5,
        height: "100%",
        borderColor: VEEWASH_BRAND.borderSoft,
        background: "linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)",
      }}
    >
      <Typography variant="caption" sx={{ color: VEEWASH_BRAND.inkSoft, letterSpacing: 0.3, textTransform: "uppercase" }}>
        {card.label}
      </Typography>
      <Typography variant="h5" fontWeight={800} sx={{ color: VEEWASH_BRAND.ink, mt: 0.25, lineHeight: 1.15 }}>
        {formatValue(card.kind, card.current ?? card.value)}
      </Typography>
      <Typography variant="caption" display="block" sx={{ color: VEEWASH_BRAND.inkMuted, mt: 0.75 }}>
        Previous: {formatValue(card.kind, card.previous)}
      </Typography>
      <Stack direction="row" spacing={0.5} alignItems="center" sx={{ mt: 0.25 }}>
        <TrendIcon direction={card.direction} />
        <Typography variant="caption" fontWeight={600} sx={{ color: VEEWASH_BRAND.inkMuted }}>
          {deltaLine(card)}
        </Typography>
      </Stack>
    </Paper>
  );
}

function OtInsightCard({ ot }) {
  if (!ot) return null;
  return (
    <Paper
      variant="outlined"
      sx={{ p: 1.5, borderColor: VEEWASH_BRAND.borderSoft, background: VEEWASH_BRAND.primaryLight }}
    >
      <Typography variant="caption" sx={{ color: VEEWASH_BRAND.inkSoft, textTransform: "uppercase" }}>
        OT Hours
      </Typography>
      <Typography variant="h5" fontWeight={800} sx={{ color: VEEWASH_BRAND.ink }}>
        {hours(ot.value)}
      </Typography>
      <Typography variant="body2" sx={{ color: VEEWASH_BRAND.inkMuted, mt: 0.5 }}>
        {Number(ot.ot_pct_of_hours || 0).toFixed(2)}% of Total Hours
      </Typography>
      <Typography variant="caption" display="block" sx={{ color: VEEWASH_BRAND.inkMuted, mt: 0.75 }}>
        Previous: {hours(ot.previous)}
      </Typography>
      <Stack direction="row" spacing={0.5} alignItems="center">
        <TrendIcon direction={ot.direction} />
        <Typography variant="caption" fontWeight={600} sx={{ color: VEEWASH_BRAND.inkMuted }}>
          {deltaLine({ ...ot, kind: "hours" })}
        </Typography>
      </Stack>
    </Paper>
  );
}

function ChartCard({ title, children, height = 230 }) {
  return (
    <Paper variant="outlined" sx={{ p: 1.5, height: "100%", borderColor: VEEWASH_BRAND.borderSoft }}>
      <Typography variant="subtitle2" fontWeight={700} sx={{ color: VEEWASH_BRAND.primaryDark, mb: 1 }}>
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

/**
 * Slim management dashboard: Executive Summary → Workforce Breakdown → Trends.
 */
export default function PayrollReportAnalyticsDashboard({
  analytics,
  summary,
  comparisonRange,
  onComparisonRangeChange,
}) {
  const kpis = analytics?.kpis || [];
  const ot = analytics?.ot_summary;
  const categories = analytics?.category_breakdown || [];
  const workforceTotals = analytics?.workforce_totals || {};
  const periods = analytics?.period_comparison || [];
  const mix = analytics?.employment_mix || [];

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

  return (
    <Stack spacing={2.5} sx={{ mb: 1 }}>
      <Stack
        direction={{ xs: "column", sm: "row" }}
        justifyContent="space-between"
        alignItems={{ xs: "stretch", sm: "center" }}
        spacing={1}
      >
        <Box>
          <Typography variant="h6" fontWeight={700} sx={{ color: VEEWASH_BRAND.primaryDark }}>
            Payroll Analytics
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

      {/* 1. Executive Summary */}
      <Box>
        <SectionTitle>Executive Summary</SectionTitle>
        <Box
          sx={{
            mt: 1,
            display: "grid",
            gap: 1.25,
            gridTemplateColumns: {
              xs: "repeat(2, minmax(0, 1fr))",
              md: "repeat(3, minmax(0, 1fr))",
              lg: "repeat(6, minmax(0, 1fr))",
            },
          }}
        >
          {kpis.map((card) => (
            <ExecKpiCard key={card.key} card={card} />
          ))}
        </Box>
        <Box sx={{ mt: 1.25, maxWidth: 360 }}>
          <OtInsightCard ot={ot} />
        </Box>
      </Box>

      {/* 2. Workforce Breakdown */}
      <Box>
        <SectionTitle>Workforce Breakdown</SectionTitle>
        <Paper variant="outlined" sx={{ mt: 1, borderColor: VEEWASH_BRAND.borderSoft }}>
          <TableContainer sx={{ overflowX: "auto" }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  {["Category", "Head Count", "Hours", "OT Hours", "Gross", "Employer Tax", "Total Cost", "Avg Rate"].map(
                    (h) => (
                      <TableCell key={h} sx={{ whiteSpace: "nowrap", color: VEEWASH_BRAND.primaryDark, fontWeight: 700 }}>
                        {h}
                      </TableCell>
                    ),
                  )}
                </TableRow>
              </TableHead>
              <TableBody>
                {categories.map((c) => (
                  <TableRow key={c.worker_category} hover>
                    <TableCell>{c.label || c.worker_category}</TableCell>
                    <TableCell align="right">{c.head_count ?? c.worker_count ?? 0}</TableCell>
                    <TableCell align="right">{hours(c.total_hours)}</TableCell>
                    <TableCell align="right">{hours(c.ot_hours)}</TableCell>
                    <TableCell align="right">{money(c.gross_pay)}</TableCell>
                    <TableCell align="right">{money(c.employer_taxes)}</TableCell>
                    <TableCell align="right">{money(c.total_payroll_cost)}</TableCell>
                    <TableCell align="right">{money(c.avg_rate ?? c.avg_pay_rate)}</TableCell>
                  </TableRow>
                ))}
                <TableRow sx={{ background: "#f8fafc" }}>
                  <TableCell sx={{ fontWeight: 700 }}>Total</TableCell>
                  <TableCell align="right" sx={{ fontWeight: 700 }}>
                    {workforceTotals.head_count ?? workforceTotals.worker_count ?? 0}
                  </TableCell>
                  <TableCell align="right" sx={{ fontWeight: 700 }}>{hours(workforceTotals.total_hours)}</TableCell>
                  <TableCell align="right" sx={{ fontWeight: 700 }}>{hours(workforceTotals.ot_hours)}</TableCell>
                  <TableCell align="right" sx={{ fontWeight: 700 }}>{money(workforceTotals.gross_pay)}</TableCell>
                  <TableCell align="right" sx={{ fontWeight: 700 }}>{money(workforceTotals.employer_taxes)}</TableCell>
                  <TableCell align="right" sx={{ fontWeight: 700 }}>{money(workforceTotals.total_payroll_cost)}</TableCell>
                  <TableCell align="right" sx={{ fontWeight: 700 }}>{money(workforceTotals.avg_rate)}</TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </TableContainer>
        </Paper>
      </Box>

      {/* 3. Trends — four charts */}
      <Box>
        <SectionTitle>Trends</SectionTitle>
        <Box
          sx={{
            mt: 1,
            display: "grid",
            gap: 1.5,
            gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" },
          }}
        >
          <ChartCard title="Payroll cost trend">
            <AreaChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `$${Number(v) / 1000}k`} />
              <Tooltip formatter={(v) => money(v)} labelFormatter={(_, p) => p?.[0]?.payload?.fullLabel} />
              <Legend />
              <Area type="monotone" dataKey="total_payroll_cost" name="Total cost" stroke="#007a91" fill="#0097b233" />
              <Area type="monotone" dataKey="gross_pay" name="Gross" stroke="#0097b2" fill="transparent" />
            </AreaChart>
          </ChartCard>
          <ChartCard title="Hours trend">
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
          <ChartCard title="Payroll cost per hour">
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => money(v)} />
              <Tooltip formatter={(v) => money(v)} labelFormatter={(_, p) => p?.[0]?.payload?.fullLabel} />
              <Legend />
              <Line type="monotone" dataKey="avg_cost_per_hour" name="Cost / hour" stroke="#007a91" strokeWidth={2} dot />
            </LineChart>
          </ChartCard>
        </Box>
      </Box>

      {/* Compact period comparison (kept for reconciliation) */}
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
                {["Payroll Period", "Workers", "Hours", "OT", "Gross", "ER taxes", "Total cost", "$/hr", "Δ cost"].map(
                  (h) => (
                    <TableCell key={h} sx={{ whiteSpace: "nowrap", color: VEEWASH_BRAND.primaryDark }}>
                      {h}
                    </TableCell>
                  ),
                )}
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
                    <TableCell align="right">{money(p.employer_taxes)}</TableCell>
                    <TableCell align="right">{money(p.total_payroll_cost)}</TableCell>
                    <TableCell align="right">{money(p.avg_cost_per_hour)}</TableCell>
                    <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                      {dCost == null
                        ? "—"
                        : `${dCost > 0 ? "+" : ""}${money(dCost)}${
                            pCost == null ? "" : ` (${pCost > 0 ? "+" : ""}${Number(pCost).toFixed(1)}%)`
                          }`}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>
    </Stack>
  );
}
