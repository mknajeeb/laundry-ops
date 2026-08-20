import { useState } from "react";
import {
  Box,
  CircularProgress,
  Drawer,
  Stack,
  Tab,
  Tabs,
  Typography,
  useMediaQuery,
} from "@mui/material";
import { useTheme } from "@mui/material/styles";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import PlanningDatePicker from "../../datetime/PlanningDatePicker";
import { VEEWASH_DASHBOARD } from "../../../theme/veewashDashboard";
import { DASH_PERIODS, fmtMoney } from "./revenueFormat";

const CHART_COLORS = [
  VEEWASH_DASHBOARD.primaryBlue,
  VEEWASH_DASHBOARD.teal,
  VEEWASH_DASHBOARD.wfCharcoal,
  VEEWASH_DASHBOARD.pending,
];

function Kpi({ label, value, sub, onClick }) {
  return (
    <Box
      component={onClick ? "button" : "div"}
      type={onClick ? "button" : undefined}
      onClick={onClick}
      sx={{
        display: "block",
        width: "100%",
        textAlign: "left",
        m: 0,
        p: 1.25,
        borderRadius: 1.5,
        border: "1px solid #e5e7eb",
        bgcolor: "#fff",
        cursor: onClick ? "pointer" : "default",
        appearance: "none",
        fontFamily: "inherit",
        boxShadow: VEEWASH_DASHBOARD.cardShadow,
        "&:hover": onClick ? { borderColor: VEEWASH_DASHBOARD.primaryBlue } : undefined,
      }}
    >
      <Typography sx={{ fontSize: 18, fontWeight: 900, color: VEEWASH_DASHBOARD.primaryBlueDark, letterSpacing: -0.3 }}>
        {value}
      </Typography>
      <Typography sx={{ mt: 0.35, fontSize: 10, fontWeight: 700, letterSpacing: 0.5, textTransform: "uppercase", color: "#64748b" }}>
        {label}
      </Typography>
      {sub ? <Typography sx={{ mt: 0.2, fontSize: 11, color: "#94a3b8", fontWeight: 600 }}>{sub}</Typography> : null}
    </Box>
  );
}

function ChartCard({ title, children, height = 220 }) {
  return (
    <Box sx={{ p: 1.5, borderRadius: 2, border: "1px solid #e5e7eb", bgcolor: "#fff", boxShadow: VEEWASH_DASHBOARD.cardShadow }}>
      <Typography sx={{ fontWeight: 800, fontSize: 13, mb: 1 }}>{title}</Typography>
      <Box sx={{ width: "100%", height, minWidth: 0 }}>{children}</Box>
    </Box>
  );
}

export default function RevenueDashboardPanel({
  period,
  onPeriodChange,
  customStart,
  customEnd,
  onCustomStart,
  onCustomEnd,
  loading,
  dashboard,
}) {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("sm"));
  const [drill, setDrill] = useState(null); // dhs | payouts | null

  const d = dashboard || {};
  const compare = d.compare;
  const trend = d.trend || [];
  const byGroup = d.by_group || [];
  const topAccounts = d.top_accounts || [];
  const cashVsCard = [
    { name: "Cash", value: Number(d.cash_vs_card?.cash || 0) },
    { name: "Card", value: Number(d.cash_vs_card?.card || 0) },
  ];
  const dhsList = d.dhs?.account_list || Object.entries(d.dhs?.accounts || {}).map(([name, revenue]) => ({ name, revenue }));

  return (
    <Stack spacing={1.5}>
      <Tabs
        value={period}
        onChange={(_, v) => onPeriodChange?.(v)}
        variant="scrollable"
        scrollButtons="auto"
        sx={{ minHeight: 36, "& .MuiTab-root": { minHeight: 36, fontWeight: 700, fontSize: 13 } }}
      >
        {DASH_PERIODS.map((p) => (
          <Tab key={p.id} value={p.id} label={p.label} />
        ))}
      </Tabs>

      {period === "custom" ? (
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
          <PlanningDatePicker value={customStart} onChange={onCustomStart} label="Start (ET)" />
          <PlanningDatePicker value={customEnd} onChange={onCustomEnd} label="End (ET)" />
        </Stack>
      ) : null}

      {loading ? (
        <Box sx={{ display: "flex", justifyContent: "center", py: 4 }}>
          <CircularProgress />
        </Box>
      ) : (
        <>
          <Typography sx={{ fontSize: 12, color: "#64748b" }}>
            {d.start_date} → {d.end_date}
            {compare ? ` · vs prior ${compare.start_date} → ${compare.end_date}` : ""}
          </Typography>

          <Box
            sx={{
              display: "grid",
              gap: 1,
              gridTemplateColumns: { xs: "repeat(2, minmax(0,1fr))", md: "repeat(3, minmax(0,1fr))", lg: "repeat(5, minmax(0,1fr))" },
            }}
          >
            <Kpi
              label="Total Revenue"
              value={fmtMoney(d.total_revenue, { empty: "$0.00" })}
              sub={compare ? `${fmtMoney(compare.delta_total, { empty: "—" })} vs prior` : undefined}
            />
            <Kpi label="Revenue / day" value={fmtMoney(d.revenue_per_day)} />
            <Kpi label="Rinse" value={fmtMoney(d.rinse?.total)} />
            <Kpi label="Non-Rinse" value={fmtMoney(d.non_rinse?.total)} />
            <Kpi label="DHS" value={fmtMoney(d.dhs?.total)} onClick={() => setDrill("dhs")} sub="Tap for accounts" />
            <Kpi label="Cash Revenue" value={fmtMoney(d.cash_revenue)} />
            <Kpi label="Card Revenue" value={fmtMoney(d.card_revenue)} />
            <Kpi label="Cash Paid Out" value={fmtMoney(d.cash_paid_out)} onClick={() => setDrill("payouts")} sub="Tap for payouts" />
            <Kpi label="Net Cash Movement" value={fmtMoney(d.net_cash_movement)} />
          </Box>

          <Box
            sx={{
              display: "grid",
              gap: 1.25,
              gridTemplateColumns: { xs: "1fr", md: "repeat(2, minmax(0, 1fr))" },
            }}
          >
            <ChartCard title="Revenue Trend">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={trend}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                  <XAxis dataKey="date_et" tick={{ fontSize: 10 }} hide={isMobile && trend.length > 10} />
                  <YAxis tick={{ fontSize: 10 }} width={40} />
                  <Tooltip formatter={(v) => fmtMoney(v)} />
                  <Line type="monotone" dataKey="total" stroke={VEEWASH_DASHBOARD.primaryBlue} strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </ChartCard>

            <ChartCard title="Revenue by Group">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={byGroup}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                  <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 10 }} width={40} />
                  <Tooltip formatter={(v) => fmtMoney(v)} />
                  <Bar dataKey="revenue" radius={[6, 6, 0, 0]}>
                    {byGroup.map((_, i) => (
                      <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>

            <ChartCard title="Top Accounts">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={topAccounts.slice(0, 8)} layout="vertical" margin={{ left: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                  <XAxis type="number" tick={{ fontSize: 10 }} />
                  <YAxis type="category" dataKey="name" width={88} tick={{ fontSize: 10 }} />
                  <Tooltip formatter={(v) => fmtMoney(v)} />
                  <Bar dataKey="revenue" fill={VEEWASH_DASHBOARD.teal} radius={[0, 6, 6, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>

            <ChartCard title="Cash vs Card">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={cashVsCard} dataKey="value" nameKey="name" innerRadius={48} outerRadius={72} paddingAngle={2}>
                    {cashVsCard.map((_, i) => (
                      <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(v) => fmtMoney(v)} />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            </ChartCard>
          </Box>
        </>
      )}

      <Drawer
        anchor={isMobile ? "bottom" : "right"}
        open={Boolean(drill)}
        onClose={() => setDrill(null)}
        PaperProps={{
          sx: {
            width: { xs: "100%", sm: 400 },
            p: 2,
            ...(isMobile ? { maxHeight: "85vh", borderTopLeftRadius: 16, borderTopRightRadius: 16 } : {}),
          },
        }}
      >
        <Typography sx={{ fontWeight: 800, mb: 1.5 }}>
          {drill === "dhs" ? "DHS Accounts" : "Cash Paid Out"}
        </Typography>
        {drill === "dhs" ? (
          <Stack spacing={1}>
            {!dhsList.length ? (
              <Typography sx={{ fontSize: 13, color: "#64748b" }}>No DHS revenue in period.</Typography>
            ) : (
              dhsList.map((row) => (
                <Stack key={row.name} direction="row" justifyContent="space-between">
                  <Typography sx={{ fontWeight: 700 }}>{row.name}</Typography>
                  <Typography sx={{ fontWeight: 800 }}>{fmtMoney(row.revenue)}</Typography>
                </Stack>
              ))
            )}
          </Stack>
        ) : (
          <Stack spacing={1}>
            {!(d.payouts || []).length ? (
              <Typography sx={{ fontSize: 13, color: "#64748b" }}>No payouts in period.</Typography>
            ) : (
              (d.payouts || []).map((p) => (
                <Box key={p.id} sx={{ p: 1.25, borderRadius: 1.5, bgcolor: VEEWASH_DASHBOARD.snapshotBg }}>
                  <Typography sx={{ fontWeight: 700 }}>{p.purpose}</Typography>
                  <Typography sx={{ fontSize: 12, color: "#64748b" }}>
                    {p.payout_business_date || p.date_et} · {fmtMoney(p.amount)}
                  </Typography>
                </Box>
              ))
            )}
          </Stack>
        )}
      </Drawer>
    </Stack>
  );
}
