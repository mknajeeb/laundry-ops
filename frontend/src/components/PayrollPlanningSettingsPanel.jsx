import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControl,
  FormControlLabel,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Switch,
  Tab,
  Tabs,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import SaveIcon from "@mui/icons-material/Save";
import { useAuth } from "../context/AuthContext";
import PlanningTimePicker from "./datetime/PlanningTimePicker";
import BagVolumeForecastSettingsTab from "./PayrollPlanningSettings/BagVolumeForecastSettingsTab";
import {
  getPayrollCalendarSettings,
  getPayrollPlanningMaintenance,
  getPayrollScheduleCoverageTargets,
  getPayrollScheduleSettings,
  postPayrollScheduleCoverageTargets,
  postPayrollScheduleSettings,
  putPayrollCalendarSettings,
  putPayrollPlanningMaintenance,
} from "../api";

const DAY_OPTIONS = [
  { value: "", label: "All days" },
  { value: 0, label: "Monday" },
  { value: 1, label: "Tuesday" },
  { value: 2, label: "Wednesday" },
  { value: 3, label: "Thursday" },
  { value: 4, label: "Friday" },
  { value: 5, label: "Saturday" },
  { value: 6, label: "Sunday" },
];

const DOW_OPTIONS = [
  { value: 0, label: "Monday" },
  { value: 1, label: "Tuesday" },
  { value: 2, label: "Wednesday" },
  { value: 3, label: "Thursday" },
  { value: 4, label: "Friday" },
  { value: 5, label: "Saturday" },
  { value: 6, label: "Sunday" },
];

const PAY_FREQ = [
  { value: "weekly", label: "Weekly" },
  { value: "biweekly", label: "Biweekly" },
  { value: "semi_monthly", label: "Semi-monthly" },
  { value: "monthly", label: "Monthly" },
];

const CALENDAR_CATS = [
  { key: "w2", label: "W-2" },
  { key: "contractor_1099", label: "1099" },
  { key: "temp", label: "Temp" },
];

function timeInput(val) {
  if (!val) return "";
  return String(val).slice(0, 5);
}

function emptyShift() {
  return { name: "", start_time_default: "07:00", end_time_default: "15:00", sort_order: 0, active: true, notes: "" };
}

function emptyStream() {
  return { name: "", sort_order: 0, active: true, notes: "" };
}

function emptyRole() {
  return { name: "", sort_order: 0, active: true, role_group: "" };
}

function emptyCoverage(settings) {
  const sh = (settings?.shifts || []).find((s) => s.active);
  const ws = (settings?.work_streams || []).find((s) => s.active);
  const r = (settings?.roles || []).find((s) => s.active);
  return {
    day_of_week: 0,
    shift_id: sh?.id || "",
    work_stream_id: ws?.id || "",
    role_id: r?.id || "",
    required_count: 1,
    active: true,
    notes: "",
  };
}

export default function PayrollPlanningSettingsPanel({ onBack, onSaved }) {
  const { hasPerm, user } = useAuth();
  const isAdmin =
    hasPerm("ta.settings") ||
    (user?.roles || []).some((r) => String(r).toUpperCase() === "ADMIN");

  const [tab, setTab] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const [settings, setSettings] = useState(null);
  const [coverage, setCoverage] = useState([]);
  const [calendar, setCalendar] = useState(null);
  const [extras, setExtras] = useState(null);

  const [editShift, setEditShift] = useState(null);
  const [editStream, setEditStream] = useState(null);
  const [editRole, setEditRole] = useState(null);
  const [editCoverage, setEditCoverage] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [sRes, cRes, calRes, exRes] = await Promise.all([
        getPayrollScheduleSettings(),
        getPayrollScheduleCoverageTargets(),
        getPayrollCalendarSettings(),
        getPayrollPlanningMaintenance(),
      ]);
      setSettings(sRes.data || {});
      setCoverage(cRes.data?.items || []);
      setCalendar(calRes.data || {});
      setExtras(exRes.data || {});
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Could not load settings");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const showMsg = (msg) => {
    setSuccess(msg);
    setTimeout(() => setSuccess(""), 4000);
    onSaved?.();
  };

  const saveSettings = async (patch) => {
    setSaving(true);
    setError("");
    try {
      const res = await postPayrollScheduleSettings({
        ...settings,
        ...patch,
        shifts: patch.shifts ?? settings?.shifts,
        work_streams: patch.work_streams ?? settings?.work_streams,
        roles: patch.roles ?? settings?.roles,
      });
      setSettings(res.data);
      showMsg("Schedule settings saved.");
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const saveCoverageAll = async (items) => {
    setSaving(true);
    setError("");
    try {
      const res = await postPayrollScheduleCoverageTargets({ items });
      setCoverage(res.data?.items || []);
      showMsg("Coverage targets saved.");
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const saveCalendar = async () => {
    setSaving(true);
    setError("");
    try {
      const cats = CALENDAR_CATS.map(({ key }) => calendar.categories?.[key]).filter(Boolean);
      const res = await putPayrollCalendarSettings({ categories: cats });
      setCalendar(res.data);
      showMsg("Payroll calendar settings saved.");
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const saveExtras = async () => {
    setSaving(true);
    setError("");
    try {
      const res = await putPayrollPlanningMaintenance(extras);
      setExtras(res.data);
      showMsg("Planning maintenance saved.");
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const [showInactiveShifts, setShowInactiveShifts] = useState(false);
  const [showInactiveStreams, setShowInactiveStreams] = useState(false);
  const [showInactiveRoles, setShowInactiveRoles] = useState(false);

  const shiftRows = settings?.shifts || [];
  const streamRows = settings?.work_streams || [];
  const roleRows = settings?.roles || [];

  const deactivateLookupRow = async (key, row) => {
    if (!row?.id) return;
    const listKey = key === "shifts" ? "shifts" : key === "streams" ? "work_streams" : "roles";
    const rows = key === "shifts" ? shiftRows : key === "streams" ? streamRows : roleRows;
    const list = rows.map((r) => (r.id === row.id ? { ...r, active: false } : r));
    await saveSettings({ [listKey]: list });
  };

  const updateCalendarCat = (key, field, value) => {
    setCalendar((prev) => ({
      ...prev,
      categories: {
        ...prev.categories,
        [key]: { ...prev.categories[key], worker_category: key, [field]: value },
      },
    }));
  };

  if (!isAdmin) {
    return (
      <Alert severity="warning" sx={{ m: 2 }}>
        Payroll planning maintenance requires admin settings access (ta.settings).
      </Alert>
    );
  }

  return (
    <Box sx={{ pb: 4 }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
        {onBack ? (
          <IconButton onClick={onBack} aria-label="Back to planner">
            <ArrowBackIcon />
          </IconButton>
        ) : null}
        <Box>
          <Typography variant="h5" fontWeight={800}>
            Payroll planning settings
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Shifts, streams, roles, coverage, calendar, and rules — admin only. Not visible on partner roster.
          </Typography>
        </Box>
      </Stack>

      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}
      {success ? (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSuccess("")}>
          {success}
        </Alert>
      ) : null}

      <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" scrollButtons="auto" sx={{ mb: 2 }}>
        {["Shifts", "Work streams", "Roles", "Coverage", "Payroll calendar", "Scheduling rules", "Bag volume forecast", "Machines"].map(
          (label, i) => (
            <Tab key={label} label={label} value={i} />
          ),
        )}
      </Tabs>

      {loading ? (
        <Typography color="text.secondary">Loading…</Typography>
      ) : (
        <>
          {tab === 0 ? (
            <Card variant="outlined">
              <CardContent>
                <Stack direction="row" justifyContent="space-between" alignItems="flex-start" sx={{ mb: 1 }}>
                  <Box>
                    <Typography fontWeight={700}>Shifts</Typography>
                    <Typography variant="caption" color="text.secondary" display="block" sx={{ maxWidth: 520, mt: 0.5 }}>
                      First visit may add starter shifts (Morning, Afternoon, etc.). There is no hard delete — use Deactivate to hide a shift from scheduling. Edit → Active off does the same.
                    </Typography>
                  </Box>
                  <Button size="small" startIcon={<AddIcon />} onClick={() => setEditShift(emptyShift())}>
                    Add shift
                  </Button>
                </Stack>
                <FormControlLabel
                  sx={{ mb: 1 }}
                  control={
                    <Switch size="small" checked={showInactiveShifts} onChange={(e) => setShowInactiveShifts(e.target.checked)} />
                  }
                  label="Show inactive shifts"
                />
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Name</TableCell>
                      <TableCell>Start</TableCell>
                      <TableCell>End</TableCell>
                      <TableCell>Order</TableCell>
                      <TableCell>Active</TableCell>
                      <TableCell align="right">Actions</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {shiftRows
                      .filter((row) => showInactiveShifts || row.active !== false && row.active !== 0)
                      .map((row) => (
                      <TableRow key={row.id || row.name} sx={{ opacity: row.active === false || row.active === 0 ? 0.55 : 1 }}>
                        <TableCell>{row.name}</TableCell>
                        <TableCell>{timeInput(row.start_time_default)}</TableCell>
                        <TableCell>{timeInput(row.end_time_default)}</TableCell>
                        <TableCell>{row.sort_order}</TableCell>
                        <TableCell>{row.active !== false && row.active !== 0 ? "Yes" : "No"}</TableCell>
                        <TableCell align="right">
                          <IconButton size="small" aria-label="Edit shift" onClick={() => setEditShift({ ...row })}>
                            <EditOutlinedIcon fontSize="small" />
                          </IconButton>
                          {row.active !== false && row.active !== 0 ? (
                            <IconButton
                              size="small"
                              color="error"
                              aria-label="Deactivate shift"
                              disabled={saving}
                              onClick={() => deactivateLookupRow("shifts", row)}
                            >
                              <DeleteOutlineIcon fontSize="small" />
                            </IconButton>
                          ) : null}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          ) : null}

          {tab === 1 ? (
            <Card variant="outlined">
              <CardContent>
                <Stack direction="row" justifyContent="space-between" alignItems="flex-start" sx={{ mb: 1 }}>
                  <Box>
                    <Typography fontWeight={700}>Work streams</Typography>
                    <Typography variant="caption" color="text.secondary">
                      Deactivate to hide from scheduling (no hard delete).
                    </Typography>
                  </Box>
                  <Button size="small" startIcon={<AddIcon />} onClick={() => setEditStream(emptyStream())}>
                    Add stream
                  </Button>
                </Stack>
                <FormControlLabel
                  sx={{ mb: 1 }}
                  control={
                    <Switch size="small" checked={showInactiveStreams} onChange={(e) => setShowInactiveStreams(e.target.checked)} />
                  }
                  label="Show inactive streams"
                />
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Name</TableCell>
                      <TableCell>Order</TableCell>
                      <TableCell>Active</TableCell>
                      <TableCell align="right">Actions</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {streamRows
                      .filter((row) => showInactiveStreams || row.active !== false && row.active !== 0)
                      .map((row) => (
                      <TableRow key={row.id || row.name}>
                        <TableCell>{row.name}</TableCell>
                        <TableCell>{row.sort_order}</TableCell>
                        <TableCell>{row.active !== false && row.active !== 0 ? "Yes" : "No"}</TableCell>
                        <TableCell align="right">
                          <IconButton size="small" onClick={() => setEditStream({ ...row })}>
                            <EditOutlinedIcon fontSize="small" />
                          </IconButton>
                          {row.active !== false && row.active !== 0 ? (
                            <IconButton
                              size="small"
                              color="error"
                              disabled={saving}
                              aria-label="Deactivate stream"
                              onClick={() => deactivateLookupRow("streams", row)}
                            >
                              <DeleteOutlineIcon fontSize="small" />
                            </IconButton>
                          ) : null}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          ) : null}

          {tab === 2 ? (
            <Card variant="outlined">
              <CardContent>
                <Stack direction="row" justifyContent="space-between" alignItems="flex-start" sx={{ mb: 1 }}>
                  <Box>
                    <Typography fontWeight={700}>Roles</Typography>
                    <Typography variant="caption" color="text.secondary">
                      Deactivate to hide from scheduling (no hard delete).
                    </Typography>
                  </Box>
                  <Button size="small" startIcon={<AddIcon />} onClick={() => setEditRole(emptyRole())}>
                    Add role
                  </Button>
                </Stack>
                <FormControlLabel
                  sx={{ mb: 1 }}
                  control={
                    <Switch size="small" checked={showInactiveRoles} onChange={(e) => setShowInactiveRoles(e.target.checked)} />
                  }
                  label="Show inactive roles"
                />
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Name</TableCell>
                      <TableCell>Group</TableCell>
                      <TableCell>Order</TableCell>
                      <TableCell>Active</TableCell>
                      <TableCell align="right">Actions</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {roleRows
                      .filter((row) => showInactiveRoles || row.active !== false && row.active !== 0)
                      .map((row) => (
                      <TableRow key={row.id || row.name}>
                        <TableCell>{row.name}</TableCell>
                        <TableCell>{row.role_group || "—"}</TableCell>
                        <TableCell>{row.sort_order}</TableCell>
                        <TableCell>{row.active !== false && row.active !== 0 ? "Yes" : "No"}</TableCell>
                        <TableCell align="right">
                          <IconButton size="small" onClick={() => setEditRole({ ...row })}>
                            <EditOutlinedIcon fontSize="small" />
                          </IconButton>
                          {row.active !== false && row.active !== 0 ? (
                            <IconButton
                              size="small"
                              color="error"
                              disabled={saving}
                              aria-label="Deactivate role"
                              onClick={() => deactivateLookupRow("roles", row)}
                            >
                              <DeleteOutlineIcon fontSize="small" />
                            </IconButton>
                          ) : null}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          ) : null}

          {tab === 3 ? (
            <Card variant="outlined">
              <CardContent>
                <Stack direction="row" justifyContent="space-between" sx={{ mb: 2 }}>
                  <Typography fontWeight={700}>Coverage targets</Typography>
                  <Button size="small" startIcon={<AddIcon />} onClick={() => setEditCoverage(emptyCoverage(settings))}>
                    Add target
                  </Button>
                </Stack>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  Used by the planner to show covered / short / overstaffed gaps.
                </Typography>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Day</TableCell>
                      <TableCell>Shift</TableCell>
                      <TableCell>Stream</TableCell>
                      <TableCell>Role</TableCell>
                      <TableCell>Required</TableCell>
                      <TableCell>Active</TableCell>
                      <TableCell align="right">Edit</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {coverage.map((row) => (
                      <TableRow key={row.id}>
                        <TableCell>
                          {row.day_of_week == null ? "All" : DAY_OPTIONS.find((d) => d.value === row.day_of_week)?.label}
                        </TableCell>
                        <TableCell>{row.shift_name}</TableCell>
                        <TableCell>{row.work_stream_name}</TableCell>
                        <TableCell>{row.role_name}</TableCell>
                        <TableCell>{row.required_count}</TableCell>
                        <TableCell>{row.active ? "Yes" : "No"}</TableCell>
                        <TableCell align="right">
                          <IconButton size="small" onClick={() => setEditCoverage({ ...row })}>
                            <EditOutlinedIcon fontSize="small" />
                          </IconButton>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          ) : null}

          {tab === 4 && calendar ? (
            <Stack spacing={2}>
              {CALENDAR_CATS.map(({ key, label }) => {
                const row = calendar.categories?.[key] || {};
                return (
                  <Card key={key} variant="outlined">
                    <CardContent>
                      <Typography fontWeight={700} sx={{ mb: 1.5 }}>
                        {label}
                      </Typography>
                      <Stack spacing={1.5} direction={{ xs: "column", md: "row" }} flexWrap="wrap" useFlexGap>
                        <FormControl size="small" sx={{ minWidth: 140 }}>
                          <InputLabel>Week starts</InputLabel>
                          <Select
                            label="Week starts"
                            value={row.work_week_start_day ?? 0}
                            onChange={(e) => updateCalendarCat(key, "work_week_start_day", Number(e.target.value))}
                          >
                            {DOW_OPTIONS.map((d) => (
                              <MenuItem key={d.value} value={d.value}>
                                {d.label}
                              </MenuItem>
                            ))}
                          </Select>
                        </FormControl>
                        <FormControl size="small" sx={{ minWidth: 140 }}>
                          <InputLabel>Payment day</InputLabel>
                          <Select
                            label="Payment day"
                            value={row.payment_day_of_week ?? 5}
                            onChange={(e) => updateCalendarCat(key, "payment_day_of_week", Number(e.target.value))}
                          >
                            {DOW_OPTIONS.map((d) => (
                              <MenuItem key={d.value} value={d.value}>
                                {d.label}
                              </MenuItem>
                            ))}
                          </Select>
                        </FormControl>
                        <FormControl size="small" sx={{ minWidth: 120 }}>
                          <InputLabel>Pay frequency</InputLabel>
                          <Select
                            label="Pay frequency"
                            value={row.pay_frequency || "weekly"}
                            onChange={(e) => updateCalendarCat(key, "pay_frequency", e.target.value)}
                          >
                            {PAY_FREQ.map((p) => (
                              <MenuItem key={p.value} value={p.value}>
                                {p.label}
                              </MenuItem>
                            ))}
                          </Select>
                        </FormControl>
                        <TextField
                          size="small"
                          label="Payment lag (days)"
                          type="number"
                          sx={{ width: 140 }}
                          value={row.payment_lag_days ?? 0}
                          onChange={(e) => updateCalendarCat(key, "payment_lag_days", Number(e.target.value))}
                        />
                        <TextField
                          size="small"
                          label="OT threshold (hrs)"
                          type="number"
                          sx={{ width: 140 }}
                          value={row.overtime_threshold_hours ?? 40}
                          onChange={(e) => updateCalendarCat(key, "overtime_threshold_hours", Number(e.target.value))}
                        />
                        <TextField
                          size="small"
                          label="OT multiplier"
                          type="number"
                          sx={{ width: 120 }}
                          value={row.overtime_multiplier ?? ""}
                          onChange={(e) => updateCalendarCat(key, "overtime_multiplier", e.target.value === "" ? null : Number(e.target.value))}
                        />
                        <FormControlLabel
                          control={
                            <Switch
                              checked={!!row.overtime_enabled}
                              onChange={(e) => updateCalendarCat(key, "overtime_enabled", e.target.checked)}
                            />
                          }
                          label="Overtime enabled"
                        />
                        <FormControlLabel
                          control={
                            <Switch
                              checked={row.include_draft_schedule_in_forecast !== false}
                              onChange={(e) => updateCalendarCat(key, "include_draft_schedule_in_forecast", e.target.checked)}
                            />
                          }
                          label="Forecast includes draft"
                        />
                        <FormControlLabel
                          control={
                            <Switch
                              checked={row.include_published_schedule_in_forecast !== false}
                              onChange={(e) =>
                                updateCalendarCat(key, "include_published_schedule_in_forecast", e.target.checked)
                              }
                            />
                          }
                          label="Forecast includes published"
                        />
                      </Stack>
                    </CardContent>
                  </Card>
                );
              })}
              <Button variant="contained" startIcon={<SaveIcon />} disabled={saving} onClick={saveCalendar}>
                Save calendar settings
              </Button>
            </Stack>
          ) : null}

          {tab === 5 && settings && extras ? (
            <Card variant="outlined">
              <CardContent>
                <Typography fontWeight={700} sx={{ mb: 2 }}>
                  Scheduling rules & thresholds
                </Typography>
                <Stack spacing={2} direction={{ xs: "column", md: "row" }} flexWrap="wrap" useFlexGap>
                  <TextField
                    size="small"
                    label="Overtime threshold (hrs)"
                    type="number"
                    value={settings.overtime_threshold_hours ?? 40}
                    onChange={(e) => setSettings({ ...settings, overtime_threshold_hours: Number(e.target.value) })}
                  />
                  <TextField
                    size="small"
                    label="Underused hours threshold"
                    type="number"
                    value={settings.underused_hours_threshold ?? 15}
                    onChange={(e) => setSettings({ ...settings, underused_hours_threshold: Number(e.target.value) })}
                  />
                  <TextField
                    size="small"
                    label="Heavy hours threshold"
                    type="number"
                    value={settings.heavy_hours_threshold ?? 35}
                    onChange={(e) => setSettings({ ...settings, heavy_hours_threshold: Number(e.target.value) })}
                  />
                  <TextField
                    size="small"
                    label="Target hours / week"
                    type="number"
                    value={settings.target_hours_per_week ?? 32}
                    onChange={(e) => setSettings({ ...settings, target_hours_per_week: Number(e.target.value) })}
                  />
                  <TextField
                    size="small"
                    label="Default break (minutes)"
                    type="number"
                    value={settings.default_break_minutes ?? 0}
                    onChange={(e) => setSettings({ ...settings, default_break_minutes: Number(e.target.value) })}
                  />
                  <FormControl size="small" sx={{ minWidth: 160 }}>
                    <InputLabel>Org payment day</InputLabel>
                    <Select
                      label="Org payment day"
                      value={settings.payment_day_of_week ?? 6}
                      onChange={(e) => setSettings({ ...settings, payment_day_of_week: Number(e.target.value) })}
                    >
                      {DOW_OPTIONS.map((d) => (
                        <MenuItem key={d.value} value={d.value}>
                          {d.label}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                </Stack>
                <Divider sx={{ my: 2 }} />
                <Stack spacing={2} direction={{ xs: "column", md: "row" }} flexWrap="wrap" useFlexGap>
                  <TextField
                    size="small"
                    label="Late grace (min)"
                    type="number"
                    value={extras.scheduling_rules?.late_grace_minutes ?? 10}
                    onChange={(e) =>
                      setExtras({
                        ...extras,
                        scheduling_rules: { ...extras.scheduling_rules, late_grace_minutes: Number(e.target.value) },
                      })
                    }
                  />
                  <TextField
                    size="small"
                    label="Missing grace (min)"
                    type="number"
                    value={extras.scheduling_rules?.missing_grace_minutes ?? 15}
                    onChange={(e) =>
                      setExtras({
                        ...extras,
                        scheduling_rules: { ...extras.scheduling_rules, missing_grace_minutes: Number(e.target.value) },
                      })
                    }
                  />
                  <TextField
                    size="small"
                    label="Max scheduled days / week"
                    type="number"
                    value={extras.scheduling_rules?.max_scheduled_days_per_week ?? 6}
                    onChange={(e) =>
                      setExtras({
                        ...extras,
                        scheduling_rules: {
                          ...extras.scheduling_rules,
                          max_scheduled_days_per_week: Number(e.target.value),
                        },
                      })
                    }
                  />
                  <FormControlLabel
                    control={
                      <Switch
                        checked={!!extras.scheduling_rules?.default_break_paid}
                        onChange={(e) =>
                          setExtras({
                            ...extras,
                            scheduling_rules: { ...extras.scheduling_rules, default_break_paid: e.target.checked },
                          })
                        }
                      />
                    }
                    label="Default break paid (placeholder)"
                  />
                </Stack>
                <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
                  <Button
                    variant="contained"
                    startIcon={<SaveIcon />}
                    disabled={saving}
                    onClick={() => saveSettings(settings)}
                  >
                    Save org thresholds
                  </Button>
                  <Button variant="outlined" disabled={saving} onClick={saveExtras}>
                    Save grace / extras
                  </Button>
                </Stack>
              </CardContent>
            </Card>
          ) : null}

          {tab === 6 && extras ? (
            <BagVolumeForecastSettingsTab
              extras={extras}
              setExtras={setExtras}
              settings={settings}
              saving={saving}
              onSave={async (partial) => {
                setSaving(true);
                setError("");
                try {
                  const res = await putPayrollPlanningMaintenance({ ...extras, ...partial });
                  setExtras(res.data);
                  showMsg("Bag volume forecast settings saved.");
                } catch (e) {
                  setError(e.response?.data?.error || e.message || "Save failed");
                } finally {
                  setSaving(false);
                }
              }}
            />
          ) : null}

          {tab === 7 && extras ? (
            <Card variant="outlined">
              <CardContent>
                <Chip label="Phase 2 placeholder" size="small" sx={{ mb: 2 }} />
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  {extras.machine_capacity?.notes || "Machine capacity not connected to scheduling yet."}
                </Typography>
                <Alert severity="info">
                  Add washer/dryer rows in a future release. Store JSON notes below for planning reference.
                </Alert>
                <TextField
                  fullWidth
                  multiline
                  minRows={4}
                  sx={{ mt: 2 }}
                  label="Machine capacity notes (JSON or text)"
                  value={
                    typeof extras.machine_capacity === "string"
                      ? extras.machine_capacity
                      : JSON.stringify(extras.machine_capacity || {}, null, 2)
                  }
                  onChange={(e) => {
                    try {
                      setExtras({ ...extras, machine_capacity: JSON.parse(e.target.value) });
                    } catch {
                      setExtras({ ...extras, machine_capacity: { notes: e.target.value } });
                    }
                  }}
                />
                <Button sx={{ mt: 2 }} variant="outlined" disabled={saving} onClick={saveExtras}>
                  Save machine placeholder
                </Button>
              </CardContent>
            </Card>
          ) : null}
        </>
      )}

      {/* Shift dialog */}
      <Dialog open={!!editShift} onClose={() => setEditShift(null)} maxWidth="sm" fullWidth>
        <DialogTitle>{editShift?.id ? "Edit shift" : "Add shift"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <TextField label="Name" value={editShift?.name || ""} onChange={(e) => setEditShift({ ...editShift, name: e.target.value })} />
            <PlanningTimePicker
              label="Default start"
              value={timeInput(editShift?.start_time_default)}
              onChange={(start_time_default) => setEditShift({ ...editShift, start_time_default })}
            />
            <PlanningTimePicker
              label="Default end"
              value={timeInput(editShift?.end_time_default)}
              onChange={(end_time_default) => setEditShift({ ...editShift, end_time_default })}
            />
            <TextField
              label="Sort order"
              type="number"
              value={editShift?.sort_order ?? 0}
              onChange={(e) => setEditShift({ ...editShift, sort_order: Number(e.target.value) })}
            />
            <TextField
              label="Notes"
              value={editShift?.notes || ""}
              onChange={(e) => setEditShift({ ...editShift, notes: e.target.value })}
            />
            <FormControlLabel
              control={
                <Switch checked={editShift?.active !== false} onChange={(e) => setEditShift({ ...editShift, active: e.target.checked })} />
              }
              label="Active"
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditShift(null)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={() => {
              const list = [...shiftRows];
              const idx = list.findIndex((s) => s.id === editShift.id);
              const row = {
                ...editShift,
                start_time_default: `${timeInput(editShift.start_time_default)}:00`,
                end_time_default: `${timeInput(editShift.end_time_default)}:00`,
              };
              if (idx >= 0) list[idx] = row;
              else list.push(row);
              saveSettings({ shifts: list });
              setEditShift(null);
            }}
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>

      {/* Stream dialog */}
      <Dialog open={!!editStream} onClose={() => setEditStream(null)} maxWidth="xs" fullWidth>
        <DialogTitle>{editStream?.id ? "Edit work stream" : "Add work stream"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <TextField label="Name" value={editStream?.name || ""} onChange={(e) => setEditStream({ ...editStream, name: e.target.value })} />
            <TextField
              label="Sort order"
              type="number"
              value={editStream?.sort_order ?? 0}
              onChange={(e) => setEditStream({ ...editStream, sort_order: Number(e.target.value) })}
            />
            <TextField label="Notes" value={editStream?.notes || ""} onChange={(e) => setEditStream({ ...editStream, notes: e.target.value })} />
            <FormControlLabel
              control={
                <Switch checked={editStream?.active !== false} onChange={(e) => setEditStream({ ...editStream, active: e.target.checked })} />
              }
              label="Active"
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditStream(null)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={() => {
              const list = [...streamRows];
              const idx = list.findIndex((s) => s.id === editStream.id);
              if (idx >= 0) list[idx] = { ...editStream };
              else list.push(editStream);
              saveSettings({ work_streams: list });
              setEditStream(null);
            }}
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>

      {/* Role dialog */}
      <Dialog open={!!editRole} onClose={() => setEditRole(null)} maxWidth="xs" fullWidth>
        <DialogTitle>{editRole?.id ? "Edit role" : "Add role"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <TextField label="Name" value={editRole?.name || ""} onChange={(e) => setEditRole({ ...editRole, name: e.target.value })} />
            <TextField
              label="Role group (optional)"
              value={editRole?.role_group || ""}
              onChange={(e) => setEditRole({ ...editRole, role_group: e.target.value })}
            />
            <TextField
              label="Sort order"
              type="number"
              value={editRole?.sort_order ?? 0}
              onChange={(e) => setEditRole({ ...editRole, sort_order: Number(e.target.value) })}
            />
            <FormControlLabel
              control={
                <Switch checked={editRole?.active !== false} onChange={(e) => setEditRole({ ...editRole, active: e.target.checked })} />
              }
              label="Active"
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditRole(null)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={() => {
              const list = [...roleRows];
              const idx = list.findIndex((s) => s.id === editRole.id);
              if (idx >= 0) list[idx] = { ...editRole };
              else list.push(editRole);
              saveSettings({ roles: list });
              setEditRole(null);
            }}
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>

      {/* Coverage dialog */}
      <Dialog open={!!editCoverage} onClose={() => setEditCoverage(null)} maxWidth="sm" fullWidth>
        <DialogTitle>{editCoverage?.id ? "Edit coverage target" : "Add coverage target"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <FormControl size="small" fullWidth>
              <InputLabel>Day</InputLabel>
              <Select
                label="Day"
                value={editCoverage?.day_of_week === null || editCoverage?.day_of_week === "" ? "" : editCoverage?.day_of_week}
                onChange={(e) =>
                  setEditCoverage({
                    ...editCoverage,
                    day_of_week: e.target.value === "" ? null : Number(e.target.value),
                  })
                }
              >
                {DAY_OPTIONS.map((d) => (
                  <MenuItem key={String(d.value)} value={d.value}>
                    {d.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl size="small" fullWidth>
              <InputLabel>Shift</InputLabel>
              <Select
                label="Shift"
                value={editCoverage?.shift_id || ""}
                onChange={(e) => setEditCoverage({ ...editCoverage, shift_id: e.target.value })}
              >
                {shiftRows.filter((s) => s.active).map((s) => (
                  <MenuItem key={s.id} value={s.id}>
                    {s.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl size="small" fullWidth>
              <InputLabel>Work stream</InputLabel>
              <Select
                label="Work stream"
                value={editCoverage?.work_stream_id || ""}
                onChange={(e) => setEditCoverage({ ...editCoverage, work_stream_id: e.target.value })}
              >
                {streamRows.filter((s) => s.active).map((s) => (
                  <MenuItem key={s.id} value={s.id}>
                    {s.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl size="small" fullWidth>
              <InputLabel>Role</InputLabel>
              <Select
                label="Role"
                value={editCoverage?.role_id || ""}
                onChange={(e) => setEditCoverage({ ...editCoverage, role_id: e.target.value })}
              >
                {roleRows.filter((s) => s.active).map((s) => (
                  <MenuItem key={s.id} value={s.id}>
                    {s.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              label="Required count"
              type="number"
              value={editCoverage?.required_count ?? 1}
              onChange={(e) => setEditCoverage({ ...editCoverage, required_count: Number(e.target.value) })}
            />
            <TextField label="Notes" value={editCoverage?.notes || ""} onChange={(e) => setEditCoverage({ ...editCoverage, notes: e.target.value })} />
            <FormControlLabel
              control={
                <Switch
                  checked={editCoverage?.active !== false}
                  onChange={(e) => setEditCoverage({ ...editCoverage, active: e.target.checked })}
                />
              }
              label="Active"
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditCoverage(null)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={() => {
              const list = [...coverage];
              const idx = list.findIndex((c) => c.id === editCoverage.id);
              const row = { ...editCoverage };
              if (idx >= 0) list[idx] = row;
              else list.push(row);
              saveCoverageAll(list);
              setEditCoverage(null);
            }}
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
