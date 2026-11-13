import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { Link as RouterLink } from "react-router-dom";
import { getIssuesRegister } from "../api";
import ManagementHubNav from "../components/management/ManagementHubNav";
import { IssuesPageShell } from "../components/management/issues/ManagementIssuesSubNav";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";
import { businessTodayYmd } from "../utils/businessTime";
import { formatIsoEtWall } from "../utils/rinseTimeFormat";

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
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
  { value: "this_month", label: "This month" },
  { value: "last_month", label: "Last month" },
];

const SOURCES = [
  { value: "all", label: "All sources" },
  { value: "rinse", label: "Customer / order" },
  { value: "employee", label: "Employee report" },
];

const EMPLOYEE_TYPES = [
  { source: "employee", category: "orphan", label: "Found Item" },
  { source: "employee", category: "redry", label: "Re-Dry Issue" },
  { source: "employee", category: "equipment", label: "Equipment Not Working" },
];

function categoryCards(summary, source) {
  const fromApi = summary?.by_category || [];
  if (source === "rinse") return fromApi;
  const seen = new Set(fromApi.map((entry) => `${entry.source}:${entry.category}`));
  const missing = EMPLOYEE_TYPES
    .filter((entry) => !seen.has(`${entry.source}:${entry.category}`))
    .map((entry) => ({ ...entry, count: 0 }));
  return [...fromApi, ...missing];
}

const STATUSES = [
  { value: "", label: "All statuses" },
  { value: "open", label: "Open / new" },
  { value: "review", label: "Under review" },
  { value: "resolved", label: "Resolved / closed" },
];

function registerPath({ dateFrom, dateTo, source, statusGroup, category }) {
  const params = new URLSearchParams();
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  if (source && source !== "all") params.set("source", source);
  if (statusGroup) params.set("status_group", statusGroup);
  if (category) params.set("category", category);
  const query = params.toString();
  return query ? `/management/issues?${query}` : "/management/issues";
}

function CountCard({ label, value, selected, to }) {
  return (
    <Box
      component={RouterLink}
      to={to}
      sx={{
        flex: "1 1 140px",
        minHeight: 72,
        textDecoration: "none",
        color: "inherit",
        bgcolor: "#fff",
        border: "1px solid",
        borderColor: selected ? VEEWASH_DASHBOARD.primaryBlue : "#e5e7eb",
        borderRadius: 2,
        px: 1.5,
        py: 1,
      }}
    >
      <Typography sx={{ fontSize: 12, color: "#64748b", fontWeight: 700 }}>{label}</Typography>
      <Typography sx={{ fontWeight: 900, fontSize: 22, color: VEEWASH_DASHBOARD.wfCharcoal }}>{value}</Typography>
    </Box>
  );
}

export default function ManagementIssuesDashboardPage() {
  const today = businessTodayYmd();
  const [period, setPeriod] = useState("30d");
  const [source, setSource] = useState("all");
  const [statusGroup, setStatusGroup] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [register, setRegister] = useState(null);

  const [dateFrom, dateTo] = periodRange(period, today);
  const shared = { dateFrom, dateTo, source, statusGroup };

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const { data } = await getIssuesRegister({
        date_from: dateFrom,
        date_to: dateTo,
        source,
        page_size: 8,
      });
      if (data?.error && !data?.ok) throw new Error(data.error);
      setRegister(data || null);
    } catch (err) {
      setError(err?.response?.data?.error || err.message || "Could not load the dashboard");
    } finally {
      setLoading(false);
    }
  }, [dateFrom, dateTo, source]);

  useEffect(() => {
    load();
  }, [load]);

  const summary = register?.summary || {};
  const recent = (summary.recent || []).filter((row) => !statusGroup || row.status_group === statusGroup);

  return (
    <>
      <ManagementHubNav activeId="issues" />
      <IssuesPageShell title="Issues Dashboard" maxWidth={1180}>
        <Stack direction="row" flexWrap="wrap" useFlexGap spacing={1} sx={{ mb: 1.5 }}>
          <TextField select size="small" label="Period" value={period} onChange={(e) => setPeriod(e.target.value)} sx={{ minWidth: 140, bgcolor: "#fff" }}>
            {PERIODS.map((item) => <MenuItem key={item.value} value={item.value}>{item.label}</MenuItem>)}
          </TextField>
          <TextField select size="small" label="Source" value={source} onChange={(e) => setSource(e.target.value)} sx={{ minWidth: 170, bgcolor: "#fff" }}>
            {SOURCES.map((item) => <MenuItem key={item.value} value={item.value}>{item.label}</MenuItem>)}
          </TextField>
          <TextField select size="small" label="Status" value={statusGroup} onChange={(e) => setStatusGroup(e.target.value)} sx={{ minWidth: 170, bgcolor: "#fff" }}>
            {STATUSES.map((item) => <MenuItem key={item.value || "all"} value={item.value}>{item.label}</MenuItem>)}
          </TextField>
          <Button component={RouterLink} to={registerPath(shared)} sx={{ textTransform: "none", fontWeight: 800 }}>
            Open register
          </Button>
        </Stack>
        <Typography variant="body2" sx={{ color: "#64748b", mb: 1.5 }}>
          {dateFrom} to {dateTo} ET. Counts are the same records as the Issues register for this period, source, and status.
        </Typography>

        {error ? <Alert severity="error" sx={{ mb: 1.5 }}>{error}</Alert> : null}
        {loading ? (
          <Box sx={{ py: 4, textAlign: "center" }}><CircularProgress size={28} /></Box>
        ) : (
          <>
            <Stack direction="row" flexWrap="wrap" useFlexGap spacing={1} sx={{ mb: 2 }}>
              <CountCard label="Total issues" value={summary.total ?? 0} selected={!statusGroup} to={registerPath({ ...shared, statusGroup: "" })} />
              <CountCard label="Open / new" value={summary.open ?? 0} selected={statusGroup === "open"} to={registerPath({ ...shared, statusGroup: "open" })} />
              <CountCard label="Under review" value={summary.review ?? 0} selected={statusGroup === "review"} to={registerPath({ ...shared, statusGroup: "review" })} />
              <CountCard label="Resolved / closed" value={summary.resolved ?? 0} selected={statusGroup === "resolved"} to={registerPath({ ...shared, statusGroup: "resolved" })} />
              <CountCard label="Customer / order" value={summary.by_source?.rinse ?? 0} selected={source === "rinse"} to={registerPath({ ...shared, source: "rinse" })} />
              <CountCard label="Employee reports" value={summary.by_source?.employee ?? 0} selected={source === "employee"} to={registerPath({ ...shared, source: "employee" })} />
            </Stack>

            <Typography sx={{ fontWeight: 800, mb: 0.75 }}>By source and type</Typography>
            <Stack direction="row" flexWrap="wrap" useFlexGap spacing={1} sx={{ mb: 2 }}>
              {categoryCards(summary, source).length === 0 ? (
                <Typography variant="body2" color="text.secondary">No issues in this period.</Typography>
              ) : categoryCards(summary, source).map((entry) => (
                <Box
                  key={`${entry.source}-${entry.category}`}
                  component={RouterLink}
                  to={registerPath({ ...shared, source: entry.source, category: entry.category })}
                  sx={{ textDecoration: "none", color: "inherit", minWidth: 160, px: 1.25, py: 1, borderRadius: 2, bgcolor: "#fff", border: "1px solid #e5e7eb" }}
                >
                  <Typography sx={{ fontSize: 11, fontWeight: 700, color: "#64748b" }}>
                    {entry.source === "employee" ? "Employee" : "Customer"}
                  </Typography>
                  <Typography sx={{ fontSize: 14, fontWeight: 800 }}>{entry.label}</Typography>
                  <Typography sx={{ fontWeight: 900, fontSize: 20 }}>{entry.count}</Typography>
                </Box>
              ))}
            </Stack>

            <Typography sx={{ fontWeight: 800, mb: 0.75 }}>Needs attention</Typography>
            <Box sx={{ bgcolor: "#fff", border: "1px solid #e5e7eb", borderRadius: 2, overflow: "hidden" }}>
              {recent.length === 0 ? (
                <Typography variant="body2" color="text.secondary" sx={{ p: 1.5 }}>Nothing open or under review in this period.</Typography>
              ) : recent.map((row) => (
                <Typography
                  key={row.key}
                  component={RouterLink}
                  to={row.source === "rinse" ? `/management/issues/${row.source_id}` : registerPath({ ...shared, source: "employee", category: row.category })}
                  sx={{ display: "block", textDecoration: "none", color: "inherit", px: 1.25, py: 0.9, fontSize: 14, borderTop: "1px solid #f1f5f9" }}
                >
                  {formatIsoEtWall(row.reported_at || row.business_date)} · {row.category_label} · {row.employee_name || row.customer_name || "—"} · {row.status}
                </Typography>
              ))}
            </Box>
          </>
        )}
      </IssuesPageShell>
    </>
  );
}
