import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  CircularProgress,
  Collapse,
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
  Bar,
  BarChart,
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
import { VEEWASH_BRAND } from "../theme/veewashBrand";

const METRICS = [
  { key: "lbs_hr", label: "Folding Speed", unit: "lb/hr" },
  { key: "bags_hr", label: "Bags/hr", unit: "bags/hr" },
  { key: "pounds", label: "Pounds", unit: "lb" },
  { key: "bags", label: "Bags / Orders", unit: "bags" },
  { key: "hours", label: "Hours", unit: "hr" },
];

function mondayOfWeek(d = new Date()) {
  // Prefer America/New_York business week when available via Intl.
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    weekday: "short",
  }).formatToParts(d);
  const get = (t) => parts.find((p) => p.type === t)?.value;
  const y = Number(get("year"));
  const m = Number(get("month"));
  const day = Number(get("day"));
  const wd = get("weekday"); // Mon..Sun
  const etNoon = new Date(Date.UTC(y, m - 1, day, 16, 0, 0));
  const map = { Mon: 0, Tue: 1, Wed: 2, Thu: 3, Fri: 4, Sat: 5, Sun: 6 };
  const offset = map[wd] ?? 0;
  etNoon.setUTCDate(etNoon.getUTCDate() - offset);
  const yy = etNoon.getUTCFullYear();
  const mm = String(etNoon.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(etNoon.getUTCDate()).padStart(2, "0");
  return `${yy}-${mm}-${dd}`;
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

function statusLabel(status) {
  const s = String(status || "").toUpperCase();
  if (s === "APPROVED") return "Approved";
  if (s === "PARTIALLY_APPROVED") return "Partially Approved";
  if (s === "NEEDS_APPROVAL") return "Needs Approval";
  if (s === "EXCLUDED") return "Excluded";
  return s || "—";
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
  return "#a16207";
}

function metricDigits(metricKey) {
  if (metricKey === "bags" || metricKey === "pounds") return 0;
  if (metricKey === "hours") return 1;
  return 1;
}

export default function RinsePerformancePage() {
  const [view, setView] = useState("role");
  const [weekStart] = useState(() => mondayOfWeek());
  const [metricKey, setMetricKey] = useState("lbs_hr");
  const [roleKey] = useState("FOLDER");
  const [roleData, setRoleData] = useState(null);
  const [employees, setEmployees] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedEmployeeId, setSelectedEmployeeId] = useState(null);
  const [employeeHistory, setEmployeeHistory] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [expandedDay, setExpandedDay] = useState(null);

  const metricMeta = useMemo(
    () => METRICS.find((m) => m.key === metricKey) || METRICS[0],
    [metricKey]
  );
  const unit = roleData?.unit || metricMeta.unit;

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      if (view === "role") {
        const res = await getRinseDashboardRole(roleKey, {
          week_start: weekStart,
          metric: metricKey,
        });
        setRoleData(res.data || null);
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
  }, [view, weekStart, metricKey, roleKey]);

  useEffect(() => {
    load();
  }, [load]);

  const openEmployee = async (employeeId) => {
    setSelectedEmployeeId(employeeId);
    setExpandedDay(null);
    setDetailLoading(true);
    setEmployeeHistory(null);
    try {
      const hist = await getRinseDashboardEmployeeRole(employeeId, roleKey, {
        week_start: weekStart,
        metric: metricKey,
        last_n: 7,
      });
      setEmployeeHistory(hist.data);
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Unable to load employee days");
    } finally {
      setDetailLoading(false);
    }
  };

  useEffect(() => {
    if (!selectedEmployeeId || view !== "employee") return;
    let cancelled = false;
    (async () => {
      setDetailLoading(true);
      try {
        const hist = await getRinseDashboardEmployeeRole(selectedEmployeeId, roleKey, {
          week_start: weekStart,
          metric: metricKey,
          last_n: 7,
        });
        if (!cancelled) setEmployeeHistory(hist.data);
      } catch {
        /* keep prior */
      } finally {
        if (!cancelled) setDetailLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedEmployeeId, metricKey, weekStart, roleKey, view]);

  const chartData = useMemo(() => {
    if (view === "role") {
      return (roleData?.leaderboard || []).map((r) => ({
        name: String(r.name || "").replace(/\s*\(.*?\)\s*/g, "").trim() || r.name,
        full: r.name,
        value: Number(r.metric_value ?? r.weekly_avg) || 0,
      }));
    }
    return (employeeHistory?.employee_days || []).map((d) => ({
      name: String(d.date || "").slice(5),
      full: d.date,
      value: Number(d.metric_value) || 0,
      status: d.status,
    }));
  }, [view, roleData, employeeHistory]);

  const showTargetLine = metricKey === "lbs_hr" && roleData?.benchmark != null;

  return (
    <Box sx={{ p: { xs: 1, md: 1.5 }, bgcolor: VEEWASH_BRAND.pageBg, minHeight: "100%" }}>
      <Stack spacing={1.5}>
        <Box>
          <Typography sx={{ fontSize: 20, fontWeight: 800, color: VEEWASH_BRAND.primaryDark }}>
            Rinse Performance
          </Typography>
          <Typography variant="body2" sx={{ color: VEEWASH_BRAND.inkMuted }}>
            Published employee-days · Folder · Week of {weekStart}
          </Typography>
        </Box>

        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
          <ToggleButtonGroup
            exclusive
            size="small"
            value={view}
            onChange={(_, v) => {
              if (!v) return;
              setView(v);
              setSelectedEmployeeId(null);
              setEmployeeHistory(null);
            }}
            sx={{ alignSelf: "flex-start" }}
          >
            <ToggleButton value="role">By Role</ToggleButton>
            <ToggleButton value="employee">By Employee</ToggleButton>
          </ToggleButtonGroup>

          <FormControl size="small" sx={{ minWidth: 180 }}>
            <InputLabel id="rinse-metric">Metric</InputLabel>
            <Select
              labelId="rinse-metric"
              label="Metric"
              value={metricKey}
              onChange={(e) => setMetricKey(e.target.value)}
            >
              {METRICS.map((m) => (
                <MenuItem key={m.key} value={m.key}>
                  {m.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <FormControl size="small" sx={{ minWidth: 140 }}>
            <InputLabel id="rinse-role">Role</InputLabel>
            <Select labelId="rinse-role" label="Role" value={roleKey} disabled>
              <MenuItem value="FOLDER">Folder</MenuItem>
            </Select>
          </FormControl>
        </Stack>

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
                gridTemplateColumns: { xs: "1fr 1fr", sm: "repeat(3, 1fr)", md: "repeat(6, 1fr)" },
              }}
            >
              <KpiCard
                label="Team Average"
                value={`${fmtRate(roleData.team_metric_value ?? roleData.team_weekly_avg, metricDigits(metricKey))} ${unit}`}
                hint="Approved employee-days · weighted"
              />
              <KpiCard
                label="Target"
                value={
                  metricKey === "lbs_hr"
                    ? `${fmtRate(roleData.benchmark, 0)} ${unit}`
                    : "—"
                }
              />
              <KpiCard
                label="Approved Employee-Days"
                value={String(
                  roleData.approved_employee_day_count ?? roleData.approved_session_count ?? 0
                )}
              />
              <KpiCard label="Included Hours" value={fmtRate(roleData.included_hours, 1)} />
              <KpiCard label="Included Pounds" value={fmtRate(roleData.included_pounds, 0)} />
              <KpiCard label="Included Bags" value={String(roleData.included_bags ?? 0)} />
            </Box>

            {chartData.length ? (
              <Paper
                variant="outlined"
                sx={{
                  borderColor: VEEWASH_BRAND.borderSoft,
                  borderRadius: VEEWASH_BRAND.radius,
                  p: 1.25,
                  height: Math.max(220, Math.min(420, 28 * chartData.length + 60)),
                }}
              >
                <Typography
                  variant="subtitle2"
                  fontWeight={800}
                  sx={{ mb: 0.75, color: VEEWASH_BRAND.primaryDark }}
                >
                  {metricMeta.label} · approved employee-days
                </Typography>
                <ResponsiveContainer width="100%" height="85%">
                  <BarChart
                    data={chartData}
                    layout="vertical"
                    margin={{ top: 4, right: 16, left: 8, bottom: 4 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis type="number" tick={{ fontSize: 11 }} />
                    <YAxis
                      type="category"
                      dataKey="name"
                      width={88}
                      tick={{ fontSize: 11 }}
                      interval={0}
                    />
                    <Tooltip
                      formatter={(v) => [fmtRate(v, metricDigits(metricKey)), unit]}
                      labelFormatter={(_, p) => p?.[0]?.payload?.full || ""}
                    />
                    {showTargetLine ? (
                      <ReferenceLine
                        x={Number(roleData.benchmark)}
                        stroke={VEEWASH_BRAND.primaryDark}
                        strokeDasharray="4 4"
                      />
                    ) : null}
                    <Bar dataKey="value" fill={VEEWASH_BRAND.primary} radius={[0, 3, 3, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </Paper>
            ) : null}

            <Paper
              variant="outlined"
              sx={{ borderColor: VEEWASH_BRAND.borderSoft, borderRadius: VEEWASH_BRAND.radius }}
            >
              <Typography
                variant="subtitle2"
                fontWeight={800}
                sx={{ px: 1.5, pt: 1.25, color: VEEWASH_BRAND.primaryDark }}
              >
                Folder Leaderboard
              </Typography>
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell sx={{ color: VEEWASH_BRAND.primaryDark, fontWeight: 700 }}>
                        #
                      </TableCell>
                      <TableCell sx={{ color: VEEWASH_BRAND.primaryDark, fontWeight: 700 }}>
                        Employee
                      </TableCell>
                      <TableCell
                        align="right"
                        sx={{ color: VEEWASH_BRAND.primaryDark, fontWeight: 700 }}
                      >
                        {metricMeta.label}
                      </TableCell>
                      <TableCell
                        align="right"
                        sx={{ color: VEEWASH_BRAND.primaryDark, fontWeight: 700 }}
                      >
                        vs Target
                      </TableCell>
                      <TableCell
                        align="right"
                        sx={{ color: VEEWASH_BRAND.primaryDark, fontWeight: 700 }}
                      >
                        Days
                      </TableCell>
                      <TableCell
                        align="right"
                        sx={{ color: VEEWASH_BRAND.primaryDark, fontWeight: 700 }}
                      >
                        Hours
                      </TableCell>
                      <TableCell
                        align="right"
                        sx={{ color: VEEWASH_BRAND.primaryDark, fontWeight: 700 }}
                      >
                        Pounds
                      </TableCell>
                      <TableCell
                        align="right"
                        sx={{ color: VEEWASH_BRAND.primaryDark, fontWeight: 700 }}
                      >
                        Bags
                      </TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {(roleData.leaderboard || []).map((row) => (
                      <TableRow
                        key={row.employee_id}
                        hover
                        sx={{ cursor: "pointer" }}
                        onClick={() => {
                          setView("employee");
                          openEmployee(row.employee_id);
                        }}
                      >
                        <TableCell>{row.rank}</TableCell>
                        <TableCell>{row.name}</TableCell>
                        <TableCell align="right">
                          {fmtRate(row.metric_value ?? row.weekly_avg, metricDigits(metricKey))}{" "}
                          {unit}
                        </TableCell>
                        <TableCell
                          align="right"
                          sx={{
                            color: vsTone(row.vs_target ?? row.vs_benchmark),
                            fontWeight: 600,
                          }}
                        >
                          {metricKey === "lbs_hr"
                            ? fmtDelta(row.vs_target ?? row.vs_benchmark)
                            : "—"}
                        </TableCell>
                        <TableCell align="right">
                          {row.days ?? row.employee_days ?? "—"}
                        </TableCell>
                        <TableCell align="right">
                          {fmtRate(row.hours ?? row.performance_hours, 1)}
                        </TableCell>
                        <TableCell align="right">
                          {fmtRate(row.pounds ?? row.total_pre_lbs, 0)}
                        </TableCell>
                        <TableCell align="right">
                          {row.bags ?? row.orders_completed ?? "—"}
                        </TableCell>
                      </TableRow>
                    ))}
                    {!roleData.leaderboard?.length ? (
                      <TableRow>
                        <TableCell colSpan={8}>
                          <Typography
                            variant="body2"
                            sx={{ color: VEEWASH_BRAND.inkMuted, py: 1 }}
                          >
                            No approved Folder employee-days this week.
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
          <Stack spacing={1.5}>
            <Paper
              variant="outlined"
              sx={{ borderColor: VEEWASH_BRAND.borderSoft, borderRadius: VEEWASH_BRAND.radius }}
            >
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
                      <TableCell sx={{ fontWeight: 700, color: VEEWASH_BRAND.primaryDark }}>
                        Employee
                      </TableCell>
                      <TableCell sx={{ fontWeight: 700, color: VEEWASH_BRAND.primaryDark }}>
                        Role
                      </TableCell>
                      <TableCell
                        align="right"
                        sx={{ fontWeight: 700, color: VEEWASH_BRAND.primaryDark }}
                      >
                        Weekly {METRICS[0].label}
                      </TableCell>
                      <TableCell
                        align="right"
                        sx={{ fontWeight: 700, color: VEEWASH_BRAND.primaryDark }}
                      >
                        Days
                      </TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {employees.map((emp) => {
                      const role = (emp.roles_summary || [])[0] || {};
                      return (
                        <TableRow
                          key={emp.employee_id}
                          hover
                          selected={selectedEmployeeId === emp.employee_id}
                          sx={{ cursor: "pointer" }}
                          onClick={() => openEmployee(emp.employee_id)}
                        >
                          <TableCell>{emp.name}</TableCell>
                          <TableCell>{role.display_name || "Folder"}</TableCell>
                          <TableCell align="right">
                            {fmtRate(role.weekly_avg)} {role.unit || "lb/hr"}
                          </TableCell>
                          <TableCell align="right">
                            {role.days ?? role.employee_days ?? "—"}
                          </TableCell>
                        </TableRow>
                      );
                    })}
                    {!employees.length ? (
                      <TableRow>
                        <TableCell colSpan={4}>
                          <Typography
                            variant="body2"
                            sx={{ color: VEEWASH_BRAND.inkMuted, py: 1 }}
                          >
                            No published employee-days this week.
                          </Typography>
                        </TableCell>
                      </TableRow>
                    ) : null}
                  </TableBody>
                </Table>
              </TableContainer>
            </Paper>

            {detailLoading ? (
              <Box sx={{ py: 2, textAlign: "center" }}>
                <CircularProgress size={24} />
              </Box>
            ) : null}

            {employeeHistory ? (
              <>
                <Typography sx={{ fontWeight: 800, color: VEEWASH_BRAND.primaryDark }}>
                  {employeeHistory.name} · employee-days
                </Typography>
                {chartData.length ? (
                  <Paper
                    variant="outlined"
                    sx={{
                      borderColor: VEEWASH_BRAND.borderSoft,
                      borderRadius: VEEWASH_BRAND.radius,
                      p: 1.25,
                      height: 240,
                    }}
                  >
                    <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 0.5 }}>
                      Daily trend · {metricMeta.label}
                    </Typography>
                    <ResponsiveContainer width="100%" height="85%">
                      <LineChart data={chartData} margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                        <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                        <YAxis tick={{ fontSize: 11 }} />
                        <Tooltip
                          formatter={(v) => [fmtRate(v, metricDigits(metricKey)), unit]}
                          labelFormatter={(_, p) => p?.[0]?.payload?.full || ""}
                        />
                        <Line
                          type="monotone"
                          dataKey="value"
                          stroke={VEEWASH_BRAND.primary}
                          strokeWidth={2}
                          dot={{ r: 3 }}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </Paper>
                ) : null}

                <Paper
                  variant="outlined"
                  sx={{
                    borderColor: VEEWASH_BRAND.borderSoft,
                    borderRadius: VEEWASH_BRAND.radius,
                  }}
                >
                  <TableContainer>
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          <TableCell sx={{ fontWeight: 700 }}>Date</TableCell>
                          <TableCell align="right" sx={{ fontWeight: 700 }}>
                            {metricMeta.label}
                          </TableCell>
                          <TableCell align="right" sx={{ fontWeight: 700 }}>
                            Pounds
                          </TableCell>
                          <TableCell align="right" sx={{ fontWeight: 700 }}>
                            Bags
                          </TableCell>
                          <TableCell align="right" sx={{ fontWeight: 700 }}>
                            Hours
                          </TableCell>
                          <TableCell sx={{ fontWeight: 700 }}>Status</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {(employeeHistory.employee_days || []).map((day) => {
                          const open = expandedDay === day.date;
                          return (
                            <Fragment key={day.date}>
                              <TableRow
                                hover
                                sx={{ cursor: "pointer" }}
                                onClick={() =>
                                  setExpandedDay((prev) => (prev === day.date ? null : day.date))
                                }
                              >
                                <TableCell>{day.date}</TableCell>
                                <TableCell align="right">
                                  {fmtRate(day.metric_value, metricDigits(metricKey))}
                                </TableCell>
                                <TableCell align="right">{fmtRate(day.pounds, 0)}</TableCell>
                                <TableCell align="right">{day.bags ?? "—"}</TableCell>
                                <TableCell align="right">{fmtRate(day.hours, 1)}</TableCell>
                                <TableCell>{statusLabel(day.status)}</TableCell>
                              </TableRow>
                              <TableRow>
                                <TableCell colSpan={6} sx={{ py: 0, border: 0 }}>
                                  <Collapse in={open} timeout="auto" unmountOnExit>
                                    <Box sx={{ px: 1, py: 1, bgcolor: "#f8fafc" }}>
                                      <Typography
                                        variant="caption"
                                        sx={{ fontWeight: 700, color: VEEWASH_BRAND.inkMuted }}
                                      >
                                        Sessions
                                      </Typography>
                                      <Table size="small">
                                        <TableHead>
                                          <TableRow>
                                            <TableCell>Code</TableCell>
                                            <TableCell>Status</TableCell>
                                            <TableCell align="right">Bags</TableCell>
                                            <TableCell align="right">Pounds</TableCell>
                                            <TableCell align="right">Hours</TableCell>
                                            <TableCell align="right">lb/hr</TableCell>
                                          </TableRow>
                                        </TableHead>
                                        <TableBody>
                                          {(day.sessions || []).map((s) => (
                                            <TableRow key={s.session_id || s.session_code}>
                                              <TableCell>
                                                {s.session_code || s.session_id}
                                              </TableCell>
                                              <TableCell>
                                                {statusLabel(s.publication_status)}
                                              </TableCell>
                                              <TableCell align="right">
                                                {s.orders_completed ?? "—"}
                                              </TableCell>
                                              <TableCell align="right">
                                                {fmtRate(s.total_pre_lbs, 1)}
                                              </TableCell>
                                              <TableCell align="right">
                                                {fmtRate(s.performance_hours, 1)}
                                              </TableCell>
                                              <TableCell align="right">
                                                {fmtRate(s.lbs_per_hour, 1)}
                                              </TableCell>
                                            </TableRow>
                                          ))}
                                          {!(day.sessions || []).length ? (
                                            <TableRow>
                                              <TableCell colSpan={6}>
                                                <Typography
                                                  variant="body2"
                                                  sx={{ color: VEEWASH_BRAND.inkMuted }}
                                                >
                                                  No session snapshot stored for this day.
                                                </Typography>
                                              </TableCell>
                                            </TableRow>
                                          ) : null}
                                        </TableBody>
                                      </Table>
                                    </Box>
                                  </Collapse>
                                </TableCell>
                              </TableRow>
                            </Fragment>
                          );
                        })}
                        {!(employeeHistory.employee_days || []).length ? (
                          <TableRow>
                            <TableCell colSpan={6}>
                              <Typography
                                variant="body2"
                                sx={{ color: VEEWASH_BRAND.inkMuted, py: 1 }}
                              >
                                No employee-days for this week yet.
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
          </Stack>
        ) : null}
      </Stack>
    </Box>
  );
}
