import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  CircularProgress,
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
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  getRinseDashboardEmployeeRole,
  getRinseDashboardEmployees,
  getRinseDashboardRole,
} from "../api";
import PerformanceDetailDrawer from "../components/management/performance/PerformanceDetailDrawer";
import { VEEWASH_BRAND } from "../theme/veewashBrand";

function mondayOfWeek(d = new Date()) {
  const x = new Date(d);
  const day = (x.getDay() + 6) % 7; // Mon=0
  x.setDate(x.getDate() - day);
  return x.toISOString().slice(0, 10);
}

function fmtRate(v, digits = 1) {
  if (v == null || !Number.isFinite(Number(v))) return "—";
  return Number(v).toFixed(digits);
}

function fmtDelta(v) {
  if (v == null || !Number.isFinite(Number(v))) return "—";
  const n = Number(v);
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(1)}`;
}

function KpiCard({ label, value, hint }) {
  return (
    <Paper
      variant="outlined"
      sx={{
        p: 1.25,
        height: "100%",
        borderColor: VEEWASH_BRAND.borderSoft,
        borderRadius: VEEWASH_BRAND.radius,
        background: "linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)",
      }}
    >
      <Typography
        variant="caption"
        sx={{ color: VEEWASH_BRAND.inkSoft, letterSpacing: 0.3, textTransform: "uppercase" }}
      >
        {label}
      </Typography>
      <Typography variant="h6" fontWeight={800} sx={{ color: VEEWASH_BRAND.ink, mt: 0.25, lineHeight: 1.15 }}>
        {value}
      </Typography>
      {hint ? (
        <Typography variant="caption" sx={{ color: VEEWASH_BRAND.inkMuted }}>
          {hint}
        </Typography>
      ) : null}
    </Paper>
  );
}

function vsTone(vs) {
  if (vs == null || !Number.isFinite(Number(vs))) return VEEWASH_BRAND.inkMuted;
  if (Number(vs) >= 0) return VEEWASH_BRAND.primaryDark;
  return "#a16207"; // subtle amber warning, not traffic-light red
}

export default function RinsePerformancePage() {
  const [view, setView] = useState("role");
  const [weekStart] = useState(() => mondayOfWeek());
  const [meta, setMeta] = useState(null);
  const [roleData, setRoleData] = useState(null);
  const [employees, setEmployees] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState(null);
  const [detailHistory, setDetailHistory] = useState(null);
  const [lastN, setLastN] = useState(5);
  const [detailLoading, setDetailLoading] = useState(false);

  const liveRole = useMemo(() => {
    const roles = meta?.performance_roles || [];
    return roles.find((r) => r.enabled && r.rinse_visible) || roles[0] || { role_key: "FOLDER", display_name: "Folder", unit: "lb/hr" };
  }, [meta]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      // Single primary request — role endpoint includes metadata + benchmark + KPIs.
      if (view === "role") {
        const res = await getRinseDashboardRole("FOLDER", { week_start: weekStart });
        const data = res.data || null;
        setRoleData(data);
        setMeta({
          performance_roles: data
            ? [
                {
                  role_key: data.role_key,
                  display_name: data.display_name,
                  unit: data.unit,
                  metric_key: data.metric_key,
                  benchmark: data.benchmark,
                  enabled: true,
                  rinse_visible: true,
                },
              ]
            : [],
        });
        setEmployees([]);
      } else {
        const res = await getRinseDashboardEmployees({ week_start: weekStart });
        setEmployees(res.data?.employees || []);
        setRoleData(null);
      }
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Unable to load performance");
      setRoleData(null);
      setEmployees([]);
    } finally {
      setLoading(false);
    }
  }, [view, weekStart]);

  useEffect(() => {
    load();
  }, [load]);

  const openEmployeeRole = async (employeeId, roleKey = liveRole.role_key) => {
    setDetail({ employeeId, roleKey });
    setDetailLoading(true);
    setDetailHistory(null);
    try {
      // One detail request — weekly avg + last N sessions (lazy, on open only).
      const hist = await getRinseDashboardEmployeeRole(employeeId, roleKey, {
        week_start: weekStart,
        last_n: lastN,
      });
      setDetail({
        employeeId,
        roleKey,
        history: hist.data,
      });
      setDetailHistory(hist.data);
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Unable to load detail");
    } finally {
      setDetailLoading(false);
    }
  };

  useEffect(() => {
    if (!detail?.employeeId || !detail?.roleKey) return;
    let cancelled = false;
    (async () => {
      setDetailLoading(true);
      try {
        const hist = await getRinseDashboardEmployeeRole(detail.employeeId, detail.roleKey, {
          week_start: weekStart,
          last_n: lastN,
        });
        if (!cancelled) {
          setDetailHistory(hist.data);
          setDetail((prev) => (prev ? { ...prev, history: hist.data } : prev));
        }
      } catch {
        /* keep prior */
      } finally {
        if (!cancelled) setDetailLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [lastN, detail?.employeeId, detail?.roleKey, weekStart]);

  const unit = liveRole.unit || "lb/hr";
  const chartRows = (detailHistory?.sessions || []).map((s, i) => ({
    label: s.date ? String(s.date).slice(5) : `S${i + 1}`,
    metric: s.metric_value,
    quantity: s.quantity,
    duration: s.duration_hours,
    date: s.date,
  }));

  return (
    <Box sx={{ p: { xs: 1, md: 1.5 }, bgcolor: VEEWASH_BRAND.pageBg, minHeight: "100%" }}>
      <Stack spacing={1.5}>
        <Box>
          <Typography sx={{ fontSize: 20, fontWeight: 800, color: VEEWASH_BRAND.primaryDark }}>
            Rinse Performance
          </Typography>
          <Typography variant="body2" sx={{ color: VEEWASH_BRAND.inkMuted }}>
            {liveRole.display_name || "Folders"} · Week of {weekStart}
          </Typography>
        </Box>

        <ToggleButtonGroup
          exclusive
          size="small"
          value={view}
          onChange={(_, v) => v && setView(v)}
          sx={{ alignSelf: "flex-start" }}
        >
          <ToggleButton value="role">By Role</ToggleButton>
          <ToggleButton value="employee">By Employee</ToggleButton>
        </ToggleButtonGroup>

        {error ? <Alert severity="error">{error}</Alert> : null}
        {loading ? (
          <Box sx={{ py: 4, textAlign: "center" }}>
            <CircularProgress size={28} />
          </Box>
        ) : null}

        {!loading && view === "role" && roleData ? (
          <>
            <Box
              sx={{
                display: "grid",
                gap: 1,
                gridTemplateColumns: { xs: "1fr 1fr", md: "repeat(3, 1fr)" },
              }}
            >
              <KpiCard
                label="Weekly Team Avg"
                value={`${fmtRate(roleData.team_weekly_avg)} ${unit}`}
              />
              <KpiCard label="Benchmark" value={`${fmtRate(roleData.benchmark, 0)} ${unit}`} />
              <KpiCard label="Approved Sessions" value={String(roleData.approved_session_count ?? 0)} />
            </Box>

            <Paper variant="outlined" sx={{ borderColor: VEEWASH_BRAND.borderSoft, borderRadius: VEEWASH_BRAND.radius }}>
              <Typography
                variant="subtitle2"
                fontWeight={800}
                sx={{ px: 1.5, pt: 1.25, color: VEEWASH_BRAND.primaryDark }}
              >
                {liveRole.display_name} Leaderboard
              </Typography>
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell sx={{ color: VEEWASH_BRAND.primaryDark, fontWeight: 700 }}>#</TableCell>
                      <TableCell sx={{ color: VEEWASH_BRAND.primaryDark, fontWeight: 700 }}>Employee</TableCell>
                      <TableCell align="right" sx={{ color: VEEWASH_BRAND.primaryDark, fontWeight: 700 }}>
                        Weekly Avg
                      </TableCell>
                      <TableCell align="right" sx={{ color: VEEWASH_BRAND.primaryDark, fontWeight: 700 }}>
                        vs Benchmark
                      </TableCell>
                      <TableCell align="right" sx={{ color: VEEWASH_BRAND.primaryDark, fontWeight: 700 }}>
                        Sessions
                      </TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {(roleData.leaderboard || []).map((row) => (
                      <TableRow
                        key={row.employee_id}
                        hover
                        sx={{ cursor: "pointer" }}
                        onClick={() => openEmployeeRole(row.employee_id, liveRole.role_key)}
                      >
                        <TableCell>{row.rank}</TableCell>
                        <TableCell>{row.name}</TableCell>
                        <TableCell align="right">
                          {fmtRate(row.weekly_avg)} {unit}
                        </TableCell>
                        <TableCell align="right" sx={{ color: vsTone(row.vs_benchmark), fontWeight: 600 }}>
                          {fmtDelta(row.vs_benchmark)}
                        </TableCell>
                        <TableCell align="right">{row.sessions}</TableCell>
                      </TableRow>
                    ))}
                    {!roleData.leaderboard?.length ? (
                      <TableRow>
                        <TableCell colSpan={5}>
                          <Typography variant="body2" sx={{ color: VEEWASH_BRAND.inkMuted, py: 1 }}>
                            No approved Folder sessions this week.
                          </Typography>
                        </TableCell>
                      </TableRow>
                    ) : null}
                  </TableBody>
                </Table>
              </TableContainer>
            </Paper>
          </>
        ) : null}

        {!loading && view === "employee" ? (
          <Paper variant="outlined" sx={{ borderColor: VEEWASH_BRAND.borderSoft, borderRadius: VEEWASH_BRAND.radius }}>
            <Typography
              variant="subtitle2"
              fontWeight={800}
              sx={{ px: 1.5, pt: 1.25, color: VEEWASH_BRAND.primaryDark }}
            >
              Employees
            </Typography>
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell sx={{ color: VEEWASH_BRAND.primaryDark, fontWeight: 700 }}>Employee</TableCell>
                    <TableCell sx={{ color: VEEWASH_BRAND.primaryDark, fontWeight: 700 }}>Role</TableCell>
                    <TableCell align="right" sx={{ color: VEEWASH_BRAND.primaryDark, fontWeight: 700 }}>
                      Performance
                    </TableCell>
                    <TableCell align="right" sx={{ color: VEEWASH_BRAND.primaryDark, fontWeight: 700 }}>
                      Benchmark
                    </TableCell>
                    <TableCell align="right" sx={{ color: VEEWASH_BRAND.primaryDark, fontWeight: 700 }}>
                      Sessions
                    </TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {employees.flatMap((emp) =>
                    (emp.roles_summary || []).map((role) => (
                      <TableRow
                        key={`${emp.employee_id}-${role.role_key}`}
                        hover
                        sx={{ cursor: "pointer" }}
                        onClick={() => openEmployeeRole(emp.employee_id, role.role_key)}
                      >
                        <TableCell>{emp.name}</TableCell>
                        <TableCell>{role.display_name}</TableCell>
                        <TableCell align="right">
                          {fmtRate(role.weekly_avg)} {role.unit}
                        </TableCell>
                        <TableCell align="right">
                          {fmtRate(role.benchmark, 0)} {role.unit}
                        </TableCell>
                        <TableCell align="right">{role.sessions}</TableCell>
                      </TableRow>
                    ))
                  )}
                  {!employees.length ? (
                    <TableRow>
                      <TableCell colSpan={5}>
                        <Typography variant="body2" sx={{ color: VEEWASH_BRAND.inkMuted, py: 1 }}>
                          No employees with approved performance this week.
                        </Typography>
                      </TableCell>
                    </TableRow>
                  ) : null}
                </TableBody>
              </Table>
            </TableContainer>
          </Paper>
        ) : null}
      </Stack>

      <PerformanceDetailDrawer
        open={Boolean(detail)}
        onClose={() => setDetail(null)}
        title={detailHistory?.name || detail?.employee?.name || "Employee"}
        subtitle={`${detailHistory?.display_name || liveRole.display_name || "Folder"} performance`}
        maxWidth={480}
      >
        {detailLoading && !detailHistory ? (
          <Box sx={{ py: 3, textAlign: "center" }}>
            <CircularProgress size={24} />
          </Box>
        ) : (
          <Stack spacing={1.5} sx={{ p: 1.5 }}>
            <Box
              sx={{
                display: "grid",
                gap: 1,
                gridTemplateColumns: "1fr 1fr",
              }}
            >
              <KpiCard
                label="Weekly Avg"
                value={`${fmtRate(detailHistory?.weekly_avg)} ${detailHistory?.unit || unit}`}
              />
              <KpiCard
                label="Benchmark"
                value={`${fmtRate(detailHistory?.benchmark, 0)} ${detailHistory?.unit || unit}`}
              />
            </Box>

            <FormControl size="small" sx={{ maxWidth: 160 }}>
              <InputLabel id="last-n-label">Last</InputLabel>
              <Select
                labelId="last-n-label"
                label="Last"
                value={lastN}
                onChange={(e) => setLastN(Number(e.target.value))}
              >
                <MenuItem value={5}>Last 5</MenuItem>
                <MenuItem value={10}>Last 10</MenuItem>
                <MenuItem value={20}>Last 20</MenuItem>
              </Select>
            </FormControl>

            <Paper variant="outlined" sx={{ p: 1.25, borderColor: VEEWASH_BRAND.borderSoft }}>
              <Typography variant="subtitle2" fontWeight={700} sx={{ color: VEEWASH_BRAND.primaryDark, mb: 0.75 }}>
                Performance
              </Typography>
              <Box sx={{ width: "100%", height: 220 }}>
                <ResponsiveContainer>
                  <LineChart data={chartRows} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} width={40} />
                    {detailHistory?.benchmark != null ? (
                      <ReferenceLine
                        y={Number(detailHistory.benchmark)}
                        stroke={VEEWASH_BRAND.inkSoft}
                        strokeDasharray="4 4"
                        label={{ value: "Benchmark", fill: VEEWASH_BRAND.inkSoft, fontSize: 10 }}
                      />
                    ) : null}
                    <Tooltip
                      contentStyle={{ fontSize: 12 }}
                      formatter={(value, name) => {
                        if (name === "metric") return [`${fmtRate(value)} ${detailHistory?.unit || unit}`, "Performance"];
                        return [value, name];
                      }}
                      labelFormatter={(_, payload) => {
                        const row = payload?.[0]?.payload;
                        if (!row) return "";
                        return `${row.date || ""} · ${fmtRate(row.quantity)} lb · ${fmtRate(row.duration, 2)} h`;
                      }}
                    />
                    <Line type="monotone" dataKey="metric" stroke={VEEWASH_BRAND.primary} strokeWidth={2} dot={{ r: 3 }} />
                  </LineChart>
                </ResponsiveContainer>
              </Box>
            </Paper>
          </Stack>
        )}
      </PerformanceDetailDrawer>
    </Box>
  );
}
