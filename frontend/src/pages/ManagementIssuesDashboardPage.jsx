import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  CircularProgress,
  MenuItem,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import { Link as RouterLink } from "react-router-dom";
import {
  getIssuesRegister,
  getManagementIssuesDashboardByEmployee,
  getManagementIssuesDashboardByIssue,
  getManagementIssuesEmployeeDrill,
} from "../api";
import ManagementHubNav from "../components/management/ManagementHubNav";
import { IssuesPageShell } from "../components/management/issues/ManagementIssuesSubNav";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";
import { businessTodayYmd } from "../utils/businessTime";

function shiftDay(ymd, days) {
  const [year, month, day] = String(ymd).split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function periodRange(period, today) {
  if (period === "today") return [today, today];
  if (period === "7d") return [shiftDay(today, -6), today];
  if (period === "this_month") return [`${today.slice(0, 8)}01`, today];
  if (period === "last_month") {
    const [year, month] = today.split("-").map(Number);
    const start = new Date(Date.UTC(year, month - 2, 1));
    const end = new Date(Date.UTC(year, month - 1, 0));
    return [start.toISOString().slice(0, 10), end.toISOString().slice(0, 10)];
  }
  return [shiftDay(today, -29), today];
}

const PERIODS = [
  { value: "today", label: "Today" },
  { value: "7d", label: "7 Days" },
  { value: "30d", label: "30 Days" },
  { value: "this_month", label: "This Month" },
  { value: "last_month", label: "Last Month" },
];

function Kpi({ label, value }) {
  return (
    <Box
      sx={{
        flex: "1 1 30%",
        minWidth: 100,
        bgcolor: "#fff",
        border: "1px solid #e5e7eb",
        borderRadius: 2,
        p: 1.25,
      }}
    >
      <Typography sx={{ fontSize: 11, color: "#94a3b8", fontWeight: 700 }}>
        {label}
      </Typography>
      <Typography sx={{ fontWeight: 900, fontSize: 20 }}>{value}</Typography>
    </Box>
  );
}

export default function ManagementIssuesDashboardPage() {
  const [mode, setMode] = useState(0);
  const [period, setPeriod] = useState("30d");
  const [dateBasis, setDateBasis] = useState("production");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [byIssue, setByIssue] = useState(null);
  const [byEmployee, setByEmployee] = useState(null);
  const [drill, setDrill] = useState(null);
  const [register, setRegister] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = { period, date_basis: dateBasis };
      const today = businessTodayYmd();
      const [dateFrom, dateTo] = periodRange(period, today);
      const registerRes = await getIssuesRegister({
        date_from: dateFrom,
        date_to: dateTo,
        page_size: 8,
      });
      setRegister(registerRes?.data || null);
      if (mode === 0) {
        const { data } = await getManagementIssuesDashboardByIssue(params);
        setByIssue(data);
      } else {
        const { data } = await getManagementIssuesDashboardByEmployee(params);
        setByEmployee(data);
      }
    } catch (e) {
      setError(e?.response?.data?.error || e.message);
    } finally {
      setLoading(false);
    }
  }, [mode, period, dateBasis]);

  useEffect(() => {
    load();
  }, [load]);

  const openDrill = async (emp) => {
    try {
      const { data } = await getManagementIssuesEmployeeDrill({
        employee_name: emp.employee_name,
        role_key: emp.role_key,
        period,
        date_basis: dateBasis,
      });
      setDrill(data);
    } catch (e) {
      setError(e?.response?.data?.error || e.message);
    }
  };

  return (
    <>
      <ManagementHubNav activeId="issues" />
      <IssuesPageShell title="Issues Dashboard" maxWidth={1180}>
        <Stack direction="row" flexWrap="wrap" useFlexGap spacing={1} sx={{ mb: 1.5 }}>
          <Kpi label="Total issues" value={register?.summary?.total ?? 0} />
          <Kpi label="Open / new" value={register?.summary?.open ?? 0} />
          <Kpi label="Under review" value={register?.summary?.review ?? 0} />
          <Kpi label="Resolved / closed" value={register?.summary?.resolved ?? 0} />
          <Kpi label="Customer issues" value={register?.summary?.by_source?.rinse ?? 0} />
          <Kpi label="Employee reports" value={register?.summary?.by_source?.employee ?? 0} />
        </Stack>
        <Stack direction="row" flexWrap="wrap" useFlexGap spacing={0.75} sx={{ mb: 2 }}>
          {(register?.summary?.by_category || []).map((entry) => (
            <Box key={entry.label} component={RouterLink} to="/management/issues" sx={{ textDecoration: "none", px: 1.25, py: 0.75, borderRadius: 2, bgcolor: "#fff", border: "1px solid #e5e7eb", color: "inherit" }}>
              <Typography sx={{ fontSize: 12, fontWeight: 800 }}>{entry.label}</Typography>
              <Typography sx={{ fontWeight: 900 }}>{entry.count}</Typography>
            </Box>
          ))}
        </Stack>
        <Typography sx={{ fontWeight: 800, mb: 0.75 }}>Needs attention</Typography>
        <Stack spacing={0.5} sx={{ mb: 2 }}>
          {(register?.summary?.recent || []).length === 0 ? (
            <Typography variant="body2" color="text.secondary">Nothing waiting in this period.</Typography>
          ) : (register.summary.recent || []).map((row) => (
            <Typography key={row.key} component={RouterLink} to={row.source === "rinse" ? `/management/issues/${row.source_id}` : "/management/issues?source=employee"} sx={{ display: "block", textDecoration: "none", color: "inherit", bgcolor: "#fff", border: "1px solid #e5e7eb", borderRadius: 1.5, px: 1.25, py: 0.75, fontSize: 14 }}>
              {row.reported_at || row.business_date} · {row.category_label} · {row.employee_name || row.customer_name || "—"} · {row.status}
            </Typography>
          ))}
        </Stack>
        <Typography sx={{ fontWeight: 800, mb: 1 }}>Customer order issues</Typography>
        <Tabs
          value={mode}
          onChange={(_, v) => {
            setDrill(null);
            setMode(v);
          }}
          sx={{ mb: 1.5 }}
        >
          <Tab label="By Issue" sx={{ textTransform: "none", fontWeight: 800 }} />
          <Tab
            label="By Employee"
            sx={{ textTransform: "none", fontWeight: 800 }}
          />
        </Tabs>

        <Stack direction="row" spacing={1} sx={{ mb: 1.5, flexWrap: "wrap" }}>
          <TextField
            select
            size="small"
            label="Period"
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            sx={{ minWidth: 140, bgcolor: "#fff" }}
          >
            {PERIODS.map((p) => (
              <MenuItem key={p.value} value={p.value}>
                {p.label}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            size="small"
            label="Date basis"
            value={dateBasis}
            onChange={(e) => setDateBasis(e.target.value)}
            sx={{ minWidth: 160, bgcolor: "#fff" }}
          >
            <MenuItem value="production">Production Date</MenuItem>
            <MenuItem value="reported">Reported Date</MenuItem>
          </TextField>
        </Stack>

        {error ? <Alert severity="error">{error}</Alert> : null}
        {loading ? (
          <Box sx={{ py: 4, textAlign: "center" }}>
            <CircularProgress size={28} />
          </Box>
        ) : mode === 0 && byIssue ? (
          <>
            <Stack
              direction="row"
              flexWrap="wrap"
              useFlexGap
              spacing={1}
              sx={{ mb: 2 }}
            >
              <Kpi label="Total Issues" value={byIssue.kpis?.total_issues ?? 0} />
              <Kpi
                label="Issue Rate /100"
                value={
                  byIssue.kpis?.issue_rate_per_100 != null
                    ? byIssue.kpis.issue_rate_per_100
                    : "—"
                }
              />
              <Kpi label="Open" value={byIssue.kpis?.open ?? 0} />
              <Kpi label="Resolved" value={byIssue.kpis?.resolved ?? 0} />
              <Kpi
                label="Claim $"
                value={`$${Number(byIssue.kpis?.claim_amount || 0).toFixed(0)}`}
              />
              <Kpi
                label="Final Vendor $"
                value={`$${Number(byIssue.kpis?.final_vendor_claim || 0).toFixed(0)}`}
              />
            </Stack>

            {(byIssue.patterns || []).length > 0 ? (
              <Stack direction="row" flexWrap="wrap" useFlexGap spacing={1} sx={{ mb: 2 }}>
                {byIssue.patterns.map((p, i) => (
                  <Box
                    key={i}
                    sx={{
                      px: 1.25,
                      py: 0.75,
                      borderRadius: 999,
                      bgcolor: VEEWASH_DASHBOARD.pendingLight,
                      border: `1px solid ${VEEWASH_DASHBOARD.pendingBorder}`,
                      fontSize: 12,
                      fontWeight: 700,
                    }}
                  >
                    {p.label}
                  </Box>
                ))}
              </Stack>
            ) : null}

            <Stack spacing={1}>
              {(byIssue.categories || []).map((c) => (
                <Box
                  key={c.issue_category}
                  component={RouterLink}
                  to={`/management/issues?category=${encodeURIComponent(c.issue_category)}`}
                  sx={{
                    textDecoration: "none",
                    color: "inherit",
                    bgcolor: "#fff",
                    border: "1px solid #e5e7eb",
                    borderRadius: 2,
                    p: 1.5,
                  }}
                >
                  <Typography sx={{ fontWeight: 900 }}>
                    {c.issue_category}
                  </Typography>
                  <Typography sx={{ fontSize: 14 }}>
                    {c.count} issues
                    {c.rate_per_100 != null
                      ? ` · ${c.rate_per_100} / 100 bags`
                      : " · Rate unavailable"}
                  </Typography>
                  <Typography sx={{ fontSize: 12, color: "#64748b" }}>
                    {c.pct_of_issues}% of issues
                    {c.change_pct_vs_prior != null
                      ? ` · ${c.change_pct_vs_prior > 0 ? "+" : ""}${c.change_pct_vs_prior}% vs prior`
                      : ""}
                  </Typography>
                </Box>
              ))}
            </Stack>
          </>
        ) : mode === 1 && byEmployee ? (
          <>
            {(byEmployee.patterns || []).length > 0 ? (
              <Stack direction="row" flexWrap="wrap" useFlexGap spacing={1} sx={{ mb: 2 }}>
                {byEmployee.patterns.map((p, i) => (
                  <Box
                    key={i}
                    sx={{
                      px: 1.25,
                      py: 0.75,
                      borderRadius: 999,
                      bgcolor: VEEWASH_DASHBOARD.primaryBlueLight,
                      fontSize: 12,
                      fontWeight: 700,
                    }}
                  >
                    {p.label}
                  </Box>
                ))}
              </Stack>
            ) : null}
            <Stack spacing={1}>
              {(byEmployee.employees || []).map((e) => (
                <Box
                  key={`${e.employee_name}-${e.role_key}`}
                  onClick={() => openDrill(e)}
                  sx={{
                    bgcolor: "#fff",
                    border: "1px solid #e5e7eb",
                    borderRadius: 2,
                    p: 1.5,
                    cursor: "pointer",
                    minHeight: 64,
                  }}
                >
                  <Typography sx={{ fontWeight: 900 }}>
                    {e.employee_name}
                  </Typography>
                  <Typography sx={{ fontSize: 13, color: "#64748b" }}>
                    {e.role_key} · Vol {e.volume ?? "—"} · Issues {e.issues}
                    {e.rate_available
                      ? ` · ${e.issue_rate_per_100 ?? "—"} /100`
                      : " · Rate unavailable"}
                  </Typography>
                  <Typography sx={{ fontSize: 12 }}>
                    Claim ${Number(e.claim_exposure || 0).toFixed(0)}
                    {e.trend_pct != null
                      ? ` · trend ${e.trend_pct > 0 ? "+" : ""}${e.trend_pct}%`
                      : ""}
                  </Typography>
                </Box>
              ))}
              {(byEmployee.employees || []).length === 0 ? (
                <Typography color="text.secondary">
                  No primary attributions in range.
                </Typography>
              ) : null}
            </Stack>

            {drill ? (
              <Box
                sx={{
                  mt: 2,
                  bgcolor: "#fff",
                  border: `1px solid ${VEEWASH_DASHBOARD.primaryBlueBorder}`,
                  borderRadius: 2,
                  p: 1.5,
                }}
              >
                <Typography sx={{ fontWeight: 900, mb: 1 }}>
                  {drill.employee?.employee_name} drilldown
                </Typography>
                <Typography sx={{ fontSize: 13, mb: 1 }}>
                  Issues {drill.employee?.issues ?? 0}
                  {drill.employee?.rate_available
                    ? ` · Rate ${drill.employee?.issue_rate_per_100}/100`
                    : " · Rate unavailable"}
                </Typography>
                <Typography sx={{ fontWeight: 700, fontSize: 13 }}>
                  Issue mix
                </Typography>
                {Object.entries(drill.employee?.issue_mix || {}).map(
                  ([k, v]) => (
                    <Typography key={k} sx={{ fontSize: 13 }}>
                      {k}: {v}
                    </Typography>
                  )
                )}
                <Typography sx={{ fontWeight: 700, fontSize: 13, mt: 1 }}>
                  Recent
                </Typography>
                {(drill.recent_issues || []).map((r) => (
                  <Typography
                    key={r.id}
                    component={RouterLink}
                    to={`/management/issues/${r.id}`}
                    sx={{
                      display: "block",
                      fontSize: 13,
                      color: VEEWASH_DASHBOARD.primaryBlueDark,
                    }}
                  >
                    #{r.id} {r.order_display_id || r.bag_id} {r.issue_category}
                  </Typography>
                ))}
              </Box>
            ) : null}
          </>
        ) : null}
      </IssuesPageShell>
    </>
  );
}
