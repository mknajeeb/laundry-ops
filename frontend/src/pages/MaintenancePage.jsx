import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  Paper,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import {
  clearGeofenceConfig,
  createMaintenanceAssignment,
  createMaintenanceLog,
  createMaintenanceTask,
  deleteMaintenanceAssignment,
  deleteMaintenanceLog,
  deleteMaintenanceTask,
  getClockPayrollUiSettings,
  getEmployees,
  getGeofenceConfig,
  getMaintenanceAgenda,
  getMaintenanceAssignments,
  getMaintenanceLogs,
  getMaintenanceTasks,
  putClockPayrollUiSettings,
  saveGeofenceConfig,
  updateMaintenanceAssignment,
  updateMaintenanceLog,
  updateMaintenanceTask,
} from "../api";

const emptyTaskForm = { task_code: "", task_name: "", category: "CLEANING", active: true };
const emptyAssignForm = {
  id: "",
  task_id: "",
  assigned_to_employee_id: "",
  assigned_to_name: "",
  due_date: new Date().toISOString().slice(0, 10),
  frequency_type: "ONE_TIME",
  frequency_interval: 1,
  weekdays_csv: "",
  status: "ASSIGNED",
  notes: "",
  created_by: "admin",
};
const DEFAULT_CLOCK_PAYROLL_UI = {
  clock: {
    outside_geofence_label_enabled: true,
    outside_geofence_label_text: "You are outside the designated work area.",
    clock_banner_enabled: false,
    clock_banner_text: "",
    show_outside_geofence_on_clock: true,
    show_outside_geofence_on_summary: true,
    ask_personal_laundry_bags: false,
  },
  payroll: {
    nav_payroll_visible: true,
    tab_live: true,
    tab_maintenance: true,
    tab_period: true,
    monitor_show_cycle_filter: true,
    monitor_show_user_filter: true,
    monitor_show_apply: true,
    monitor_col_id: true,
    monitor_col_user: true,
    monitor_col_cycle: true,
    monitor_col_clock_in: true,
    monitor_col_clock_out: true,
    monitor_col_net: true,
    monitor_col_status: true,
    monitor_col_geofence: true,
    monitor_col_actions: true,
  },
};

const emptyLogForm = {
  id: "",
  assignment_id: "",
  task_id: "",
  performed_by_employee_id: "",
  performed_by_name: "",
  performed_date: new Date().toISOString().slice(0, 10),
  start_time: "",
  end_time: "",
  pit1_done: false,
  pit2_done: false,
  big_pit_done: false,
  washer_no: "",
  notes: "",
  source_type: "ADHOC",
};

function MaintenancePage() {
  const [tab, setTab] = useState("ASSIGNED");
  const [tasks, setTasks] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [logs, setLogs] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [agenda, setAgenda] = useState([]);
  const [message, setMessage] = useState({ type: "info", text: "" });
  const [saving, setSaving] = useState(false);

  const [openTask, setOpenTask] = useState(false);
  const [openAssign, setOpenAssign] = useState(false);
  const [openLog, setOpenLog] = useState(false);
  const [taskMode, setTaskMode] = useState("create");
  const [assignMode, setAssignMode] = useState("create");
  const [logMode, setLogMode] = useState("create");

  const [geofence, setGeofence] = useState({
    label: "Work",
    latitude: "",
    longitude: "",
    radius_m: "35",
    updated_by: "admin",
  });

  const [clockPayrollUi, setClockPayrollUi] = useState(DEFAULT_CLOCK_PAYROLL_UI);

  const [taskForm, setTaskForm] = useState(emptyTaskForm);
  const [assignForm, setAssignForm] = useState(emptyAssignForm);
  const [logForm, setLogForm] = useState(emptyLogForm);

  const load = async () => {
    const results = await Promise.allSettled([
      getMaintenanceTasks(),
      getMaintenanceAssignments(),
      getMaintenanceLogs(),
      getEmployees(),
      getMaintenanceAgenda(),
      getGeofenceConfig(),
    ]);

    const [t, a, l, e, ag, g] = results;
    const errors = [];

    if (t.status === "fulfilled") {
      setTasks(Array.isArray(t.value?.data) ? t.value.data : []);
    } else {
      console.error(t.reason);
      setTasks([]);
      errors.push("tasks");
    }

    if (a.status === "fulfilled") {
      setAssignments(Array.isArray(a.value?.data) ? a.value.data : []);
    } else {
      console.error(a.reason);
      setAssignments([]);
      errors.push("assignments");
    }

    if (l.status === "fulfilled") {
      setLogs(Array.isArray(l.value?.data) ? l.value.data : []);
    } else {
      console.error(l.reason);
      setLogs([]);
      errors.push("logs");
    }

    if (e.status === "fulfilled") {
      setEmployees(Array.isArray(e.value?.data) ? e.value.data : []);
    } else {
      console.error(e.reason);
      setEmployees([]);
      errors.push("employees");
    }

    if (ag.status === "fulfilled") {
      setAgenda(Array.isArray(ag.value?.data) ? ag.value.data : []);
    } else {
      console.error(ag.reason);
      setAgenda([]);
      errors.push("agenda");
    }

    if (g.status === "fulfilled") {
      const gf = g.value?.data?.geofence;
      if (gf) {
        setGeofence({
          label: gf.label || "Work",
          latitude: String(gf.latitude ?? ""),
          longitude: String(gf.longitude ?? ""),
          radius_m: String(gf.radius_m ?? "35"),
          updated_by: "admin",
        });
      }
    } else {
      console.error(g.reason);
      errors.push("geofence");
    }

    if (errors.length) {
      setMessage({
        type: "warning",
        text: `Loaded with partial errors: ${errors.join(", ")}.`,
      });
      return;
    }

    setMessage({ type: "", text: "" });
  };

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    getClockPayrollUiSettings()
      .then((res) => {
        const d = res.data;
        if (!d?.clock || !d?.payroll) return;
        setClockPayrollUi({
          clock: { ...DEFAULT_CLOCK_PAYROLL_UI.clock, ...d.clock },
          payroll: { ...DEFAULT_CLOCK_PAYROLL_UI.payroll, ...d.payroll },
        });
      })
      .catch(() => {});
  }, []);

  const saveClockPayrollUi = async () => {
    try {
      setSaving(true);
      await putClockPayrollUiSettings(clockPayrollUi);
      setMessage({ type: "success", text: "Clock / payroll UI settings saved." });
    } catch (e) {
      console.error(e);
      setMessage({
        type: "error",
        text: e?.response?.data?.error || "Save failed (need payroll settings permission).",
      });
    } finally {
      setSaving(false);
    }
  };

  const overdueCount = useMemo(
    () => assignments.filter((x) => String(x.status).toUpperCase() !== "COMPLETED" && new Date(x.due_date) < new Date()).length,
    [assignments]
  );

  const openTaskCreate = () => {
    setTaskMode("create");
    setTaskForm(emptyTaskForm);
    setOpenTask(true);
  };

  const openTaskEdit = (t) => {
    setTaskMode("edit");
    setTaskForm({
      id: t.id,
      task_code: t.task_code || "",
      task_name: t.task_name || "",
      category: t.category || "CLEANING",
      active: Boolean(t.active),
    });
    setOpenTask(true);
  };

  const saveTask = async () => {
    try {
      setSaving(true);
      if (taskMode === "edit") {
        await updateMaintenanceTask(taskForm);
        setMessage({ type: "success", text: "Task updated." });
      } else {
        await createMaintenanceTask(taskForm);
        setMessage({ type: "success", text: "Task added." });
      }
      setOpenTask(false);
      setTaskForm(emptyTaskForm);
      await load();
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: e?.response?.data?.error || "Task save failed." });
    } finally {
      setSaving(false);
    }
  };

  const removeTask = async (id) => {
    if (!window.confirm("Delete this task?")) return;
    try {
      await deleteMaintenanceTask(id);
      setMessage({ type: "success", text: "Task removed." });
      await load();
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: e?.response?.data?.error || "Task remove failed." });
    }
  };

  const openAssignCreate = () => {
    setAssignMode("create");
    setAssignForm(emptyAssignForm);
    setOpenAssign(true);
  };

  const openAssignEdit = (a) => {
    setAssignMode("edit");
    setAssignForm({
      ...emptyAssignForm,
      id: a.id,
      task_id: String(a.task_id || ""),
      assigned_to_employee_id: String(a.assigned_to_employee_id || ""),
      assigned_to_name: a.assigned_to_name || "",
      due_date: String(a.due_date || "").slice(0, 10),
      frequency_type: a.frequency_type || "ONE_TIME",
      frequency_interval: a.frequency_interval || 1,
      weekdays_csv: a.weekdays_csv || "",
      status: a.status || "ASSIGNED",
      notes: a.notes || "",
      created_by: "admin",
    });
    setOpenAssign(true);
  };

  const saveAssign = async () => {
    try {
      setSaving(true);
      if (assignMode === "edit") {
        await updateMaintenanceAssignment(assignForm);
        setMessage({ type: "success", text: "Assignment updated." });
      } else {
        await createMaintenanceAssignment(assignForm);
        setMessage({ type: "success", text: "Task assigned." });
      }
      setOpenAssign(false);
      setAssignForm(emptyAssignForm);
      await load();
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: e?.response?.data?.error || "Assignment save failed." });
    } finally {
      setSaving(false);
    }
  };

  const removeAssign = async (id) => {
    if (!window.confirm("Delete this assignment?")) return;
    try {
      await deleteMaintenanceAssignment(id);
      setMessage({ type: "success", text: "Assignment removed." });
      await load();
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: e?.response?.data?.error || "Assignment remove failed." });
    }
  };

  const openLogCreate = () => {
    setLogMode("create");
    setLogForm(emptyLogForm);
    setOpenLog(true);
  };

  const openLogEdit = (l) => {
    setLogMode("edit");
    setLogForm({
      ...emptyLogForm,
      id: l.id,
      assignment_id: String(l.assignment_id || ""),
      task_id: String(l.task_id || ""),
      performed_by_employee_id: String(l.performed_by_employee_id || ""),
      performed_by_name: l.performed_by_name || "",
      performed_date: String(l.performed_date || "").slice(0, 10),
      start_time: l.start_time ? String(l.start_time).slice(11, 16) : "",
      end_time: l.end_time ? String(l.end_time).slice(11, 16) : "",
      pit1_done: Boolean(l.pit1_done),
      pit2_done: Boolean(l.pit2_done),
      big_pit_done: Boolean(l.big_pit_done),
      washer_no: l.washer_no || "",
      notes: l.notes || "",
      source_type: l.source_type || "ADHOC",
    });
    setOpenLog(true);
  };

  const saveLog = async () => {
    try {
      setSaving(true);
      if (logMode === "edit") {
        await updateMaintenanceLog(logForm);
        setMessage({ type: "success", text: "Log updated." });
      } else {
        await createMaintenanceLog(logForm);
        setMessage({ type: "success", text: "Log saved." });
      }
      setOpenLog(false);
      setLogForm(emptyLogForm);
      await load();
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: e?.response?.data?.error || "Log save failed." });
    } finally {
      setSaving(false);
    }
  };

  const removeLog = async (id) => {
    if (!window.confirm("Delete this log?")) return;
    try {
      await deleteMaintenanceLog(id);
      setMessage({ type: "success", text: "Log removed." });
      await load();
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: e?.response?.data?.error || "Log remove failed." });
    }
  };

  const saveGeo = async () => {
    try {
      setSaving(true);

      if (
        geofence.latitude === "" ||
        geofence.longitude === "" ||
        geofence.radius_m === ""
      ) {
        setMessage({
          type: "error",
          text: "Latitude, Longitude, and Radius are required.",
        });
        return;
      }

      await saveGeofenceConfig({
        ...geofence,
        latitude: Number(geofence.latitude),
        longitude: Number(geofence.longitude),
        radius_m: Number(geofence.radius_m),
        active: true,
      });
      setMessage({ type: "success", text: "Geofence updated." });
      await load();
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: e?.response?.data?.error || "Geofence save failed." });
    } finally {
      setSaving(false);
    }
  };

  const clearGeo = async () => {
    if (!window.confirm("Clear active geofence?")) return;
    try {
      setSaving(true);
      await clearGeofenceConfig();
      setGeofence({ label: "Work", latitude: "", longitude: "", radius_m: "35", updated_by: "admin" });
      setMessage({ type: "success", text: "Geofence cleared." });
      await load();
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: e?.response?.data?.error || "Geofence clear failed." });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Box sx={{ p: { xs: 1.2, md: 2 }, minHeight: "100%" }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Typography sx={{ fontSize: 28 }}>Maintenance</Typography>
        <Stack direction="row" spacing={1}>
          <Chip label={`Assigned ${assignments.length}`} color="primary" />
          <Chip label={`Overdue ${overdueCount}`} color={overdueCount > 0 ? "error" : "default"} />
        </Stack>
      </Stack>
      {message.text && <Alert severity={message.type || "info"} sx={{ mt: 1 }}>{message.text}</Alert>}

      <Paper sx={{ mt: 1.2, borderRadius: 2, overflow: "hidden" }}>
        <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" scrollButtons="auto">
          <Tab value="ASSIGNED" label="Assigned Tasks" />
          <Tab value="ADHOC" label="Ad-hoc Log" />
          <Tab value="TASKS" label="Task Catalog" />
          <Tab value="GEOFENCE" label="GeoFence" />
          <Tab value="CLOCK_PAYROLL" label="Clock / payroll UI" />
        </Tabs>
      </Paper>

      {tab === "ASSIGNED" && (
        <Paper sx={{ mt: 1.2, p: 1.5, borderRadius: 2 }}>
          <Stack direction="row" justifyContent="space-between">
            <Typography sx={{ fontSize: 20 }}>Assignments</Typography>
            <Button variant="contained" onClick={openAssignCreate}>Assign Task</Button>
          </Stack>
          <Stack spacing={1} sx={{ mt: 1 }}>
            {assignments.map((a) => (
              <Stack key={a.id} direction="row" justifyContent="space-between" sx={{ border: "1px solid #e5e7eb", p: 1, borderRadius: 1.5 }}>
                <Box>
                  <Typography>{a.task_name}</Typography>
                  <Typography sx={{ color: "#64748b", fontSize: 13 }}>
                    Due {String(a.due_date).slice(0, 10)} • {a.assigned_to_name || "Unassigned"}
                  </Typography>
                </Box>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Chip label={a.status} color={String(a.status).toUpperCase() === "COMPLETED" ? "success" : "warning"} />
                  <Button size="small" onClick={() => openAssignEdit(a)}>Edit</Button>
                  <Button size="small" color="error" onClick={() => removeAssign(a.id)}>Remove</Button>
                </Stack>
              </Stack>
            ))}
          </Stack>
          {agenda.length > 0 && (
            <>
              <Typography sx={{ mt: 2, mb: 0.8, fontSize: 18 }}>Upcoming / Overdue</Typography>
              <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap" }}>
                {agenda.slice(0, 20).map((x) => (
                  <Chip key={`${x.assignment_id}-${x.due_date}`} label={`${x.task_name} • ${String(x.due_date).slice(0, 10)} • ${x.agenda_state}`} />
                ))}
              </Stack>
            </>
          )}
        </Paper>
      )}

      {tab === "ADHOC" && (
        <Paper sx={{ mt: 1.2, p: 1.5, borderRadius: 2 }}>
          <Stack direction="row" justifyContent="space-between">
            <Typography sx={{ fontSize: 20 }}>Task Logs</Typography>
            <Button variant="contained" onClick={openLogCreate}>Log Task</Button>
          </Stack>
          <Stack spacing={1} sx={{ mt: 1 }}>
            {logs.slice(0, 80).map((l) => (
              <Stack key={l.id} direction="row" justifyContent="space-between" sx={{ border: "1px solid #e5e7eb", p: 1, borderRadius: 1.5 }}>
                <Box>
                  <Typography>{l.task_name}</Typography>
                  <Typography sx={{ color: "#64748b", fontSize: 13 }}>
                    {String(l.performed_date).slice(0, 10)} • {l.performed_by_name}
                  </Typography>
                </Box>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Chip label={l.source_type} />
                  <Button size="small" onClick={() => openLogEdit(l)}>Edit</Button>
                  <Button size="small" color="error" onClick={() => removeLog(l.id)}>Remove</Button>
                </Stack>
              </Stack>
            ))}
          </Stack>
        </Paper>
      )}

      {tab === "TASKS" && (
        <Paper sx={{ mt: 1.2, p: 1.5, borderRadius: 2 }}>
          <Stack direction="row" justifyContent="space-between">
            <Typography sx={{ fontSize: 20 }}>Task Catalog</Typography>
            <Button variant="contained" onClick={openTaskCreate}>Add Task</Button>
          </Stack>
          <Stack spacing={1} sx={{ mt: 1 }}>
            {tasks.map((t) => (
              <Stack key={t.id} direction="row" justifyContent="space-between" sx={{ border: "1px solid #e5e7eb", p: 1, borderRadius: 1.5 }}>
                <Typography>{t.task_name}</Typography>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Chip label={t.task_code} />
                  <Chip label={t.category} />
                  <Button size="small" onClick={() => openTaskEdit(t)}>Edit</Button>
                  <Button size="small" color="error" onClick={() => removeTask(t.id)}>Remove</Button>
                </Stack>
              </Stack>
            ))}
          </Stack>
        </Paper>
      )}

      {tab === "CLOCK_PAYROLL" && (
        <Paper sx={{ mt: 1.2, p: 1.5, borderRadius: 2 }}>
          <Typography sx={{ fontSize: 20, mb: 1 }}>Clock (PWA) & payroll screens</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Control geofence warnings, optional banner text, checkout prompts, and which payroll management
            tabs and columns employees see.
          </Typography>
          <Typography fontWeight={600} sx={{ mb: 1 }}>
            Time clock (mobile)
          </Typography>
          <Stack spacing={1} sx={{ mb: 2 }}>
            <FormControlLabel
              control={
                <Checkbox
                  checked={clockPayrollUi.clock.outside_geofence_label_enabled}
                  onChange={(e) =>
                    setClockPayrollUi((p) => ({
                      ...p,
                      clock: { ...p.clock, outside_geofence_label_enabled: e.target.checked },
                    }))
                  }
                />
              }
              label="Show red alert when outside geofence (while clocked in)"
            />
            <TextField
              fullWidth
              label="Outside geofence message"
              value={clockPayrollUi.clock.outside_geofence_label_text}
              onChange={(e) =>
                setClockPayrollUi((p) => ({
                  ...p,
                  clock: { ...p.clock, outside_geofence_label_text: e.target.value },
                }))
              }
            />
            <FormControlLabel
              control={
                <Checkbox
                  checked={clockPayrollUi.clock.clock_banner_enabled}
                  onChange={(e) =>
                    setClockPayrollUi((p) => ({
                      ...p,
                      clock: { ...p.clock, clock_banner_enabled: e.target.checked },
                    }))
                  }
                />
              }
              label="Show info banner on clock screen"
            />
            <TextField
              fullWidth
              label="Banner message (all clock users)"
              value={clockPayrollUi.clock.clock_banner_text}
              onChange={(e) =>
                setClockPayrollUi((p) => ({
                  ...p,
                  clock: { ...p.clock, clock_banner_text: e.target.value },
                }))
              }
            />
            <FormControlLabel
              control={
                <Checkbox
                  checked={clockPayrollUi.clock.show_outside_geofence_on_clock}
                  onChange={(e) =>
                    setClockPayrollUi((p) => ({
                      ...p,
                      clock: { ...p.clock, show_outside_geofence_on_clock: e.target.checked },
                    }))
                  }
                />
              }
              label="Show accumulated outside-geofence time on clock (while in session)"
            />
            <FormControlLabel
              control={
                <Checkbox
                  checked={clockPayrollUi.clock.show_outside_geofence_on_summary}
                  onChange={(e) =>
                    setClockPayrollUi((p) => ({
                      ...p,
                      clock: { ...p.clock, show_outside_geofence_on_summary: e.target.checked },
                    }))
                  }
                />
              }
              label="Show outside-geofence time on clock-out confirmation & recap"
            />
            <FormControlLabel
              control={
                <Checkbox
                  checked={clockPayrollUi.clock.ask_personal_laundry_bags}
                  onChange={(e) =>
                    setClockPayrollUi((p) => ({
                      ...p,
                      clock: { ...p.clock, ask_personal_laundry_bags: e.target.checked },
                    }))
                  }
                />
              }
              label="Ask for personal laundry bag count before clock out"
            />
          </Stack>
          <Typography fontWeight={600} sx={{ mb: 1 }}>
            Payroll management screen
          </Typography>
          <Stack spacing={0.5} sx={{ mb: 2 }}>
            <FormControlLabel
              control={
                <Checkbox
                  checked={clockPayrollUi.payroll.nav_payroll_visible}
                  onChange={(e) =>
                    setClockPayrollUi((p) => ({
                      ...p,
                      payroll: { ...p.payroll, nav_payroll_visible: e.target.checked },
                    }))
                  }
                />
              }
              label="Show Payroll management in sidebar"
            />
            <FormControlLabel
              control={
                <Checkbox
                  checked={clockPayrollUi.payroll.tab_live}
                  onChange={(e) =>
                    setClockPayrollUi((p) => ({
                      ...p,
                      payroll: { ...p.payroll, tab_live: e.target.checked },
                    }))
                  }
                />
              }
              label="Tab: Live sessions"
            />
            <FormControlLabel
              control={
                <Checkbox
                  checked={clockPayrollUi.payroll.tab_maintenance}
                  onChange={(e) =>
                    setClockPayrollUi((p) => ({
                      ...p,
                      payroll: { ...p.payroll, tab_maintenance: e.target.checked },
                    }))
                  }
                />
              }
              label="Tab: Attendance / setup"
            />
            <FormControlLabel
              control={
                <Checkbox
                  checked={clockPayrollUi.payroll.tab_period}
                  onChange={(e) =>
                    setClockPayrollUi((p) => ({
                      ...p,
                      payroll: { ...p.payroll, tab_period: e.target.checked },
                    }))
                  }
                />
              }
              label="Tab: Pay period"
            />
            <Typography sx={{ mt: 1, fontWeight: 600 }}>Live monitor — filters</Typography>
            <FormControlLabel
              control={
                <Checkbox
                  checked={clockPayrollUi.payroll.monitor_show_cycle_filter}
                  onChange={(e) =>
                    setClockPayrollUi((p) => ({
                      ...p,
                      payroll: { ...p.payroll, monitor_show_cycle_filter: e.target.checked },
                    }))
                  }
                />
              }
              label="Cycle filter"
            />
            <FormControlLabel
              control={
                <Checkbox
                  checked={clockPayrollUi.payroll.monitor_show_user_filter}
                  onChange={(e) =>
                    setClockPayrollUi((p) => ({
                      ...p,
                      payroll: { ...p.payroll, monitor_show_user_filter: e.target.checked },
                    }))
                  }
                />
              }
              label="User filter"
            />
            <FormControlLabel
              control={
                <Checkbox
                  checked={clockPayrollUi.payroll.monitor_show_apply}
                  onChange={(e) =>
                    setClockPayrollUi((p) => ({
                      ...p,
                      payroll: { ...p.payroll, monitor_show_apply: e.target.checked },
                    }))
                  }
                />
              }
              label="Apply button"
            />
            <Typography sx={{ mt: 1, fontWeight: 600 }}>Live monitor — table columns</Typography>
            {[
              ["monitor_col_id", "ID"],
              ["monitor_col_user", "User"],
              ["monitor_col_cycle", "Cycle"],
              ["monitor_col_clock_in", "Clock in"],
              ["monitor_col_clock_out", "Clock out"],
              ["monitor_col_net", "Net seconds"],
              ["monitor_col_status", "Status"],
              ["monitor_col_geofence", "Geofence"],
              ["monitor_col_actions", "Actions"],
            ].map(([colKey, label]) => (
              <FormControlLabel
                key={colKey}
                control={
                  <Checkbox
                    checked={clockPayrollUi.payroll[colKey]}
                    onChange={(e) =>
                      setClockPayrollUi((p) => ({
                        ...p,
                        payroll: { ...p.payroll, [colKey]: e.target.checked },
                      }))
                    }
                  />
                }
                label={label}
              />
            ))}
          </Stack>
          <Button variant="contained" onClick={saveClockPayrollUi} disabled={saving}>
            Save clock / payroll UI
          </Button>
        </Paper>
      )}

      {tab === "GEOFENCE" && (
        <Paper sx={{ mt: 1.2, p: 1.5, borderRadius: 2 }}>
          <Typography sx={{ fontSize: 20, mb: 1 }}>GeoFence Settings</Typography>
          <Stack spacing={1}>
            <TextField label="Label" value={geofence.label} onChange={(e) => setGeofence((p) => ({ ...p, label: e.target.value }))} />
            <TextField label="Latitude" value={geofence.latitude} onChange={(e) => setGeofence((p) => ({ ...p, latitude: e.target.value }))} />
            <TextField label="Longitude" value={geofence.longitude} onChange={(e) => setGeofence((p) => ({ ...p, longitude: e.target.value }))} />
            <TextField label="Radius (m)" value={geofence.radius_m} onChange={(e) => setGeofence((p) => ({ ...p, radius_m: e.target.value }))} />
            <Stack direction="row" spacing={1}>
              <Button variant="contained" onClick={saveGeo} disabled={saving}>Save GeoFence</Button>
              <Button variant="outlined" color="error" onClick={clearGeo} disabled={saving}>Remove GeoFence</Button>
            </Stack>
          </Stack>
        </Paper>
      )}

      <Dialog open={openTask} onClose={() => setOpenTask(false)} fullWidth maxWidth="sm">
        <DialogTitle>{taskMode === "edit" ? "Edit Task" : "Add Task"}</DialogTitle>
        <DialogContent>
          <Stack spacing={1.2} sx={{ mt: 0.8 }}>
            <TextField label="Task Code" value={taskForm.task_code} onChange={(e) => setTaskForm((p) => ({ ...p, task_code: e.target.value }))} />
            <TextField label="Task Name" value={taskForm.task_name} onChange={(e) => setTaskForm((p) => ({ ...p, task_name: e.target.value }))} />
            <TextField select label="Category" value={taskForm.category} onChange={(e) => setTaskForm((p) => ({ ...p, category: e.target.value }))}>
              <MenuItem value="CLEANING">CLEANING</MenuItem>
              <MenuItem value="MAINTENANCE">MAINTENANCE</MenuItem>
              <MenuItem value="INSPECTION">INSPECTION</MenuItem>
            </TextField>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpenTask(false)}>Cancel</Button>
          <Button variant="contained" onClick={saveTask} disabled={saving || !taskForm.task_code || !taskForm.task_name}>Save</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={openAssign} onClose={() => setOpenAssign(false)} fullWidth maxWidth="sm">
        <DialogTitle>{assignMode === "edit" ? "Edit Assignment" : "Assign Task"}</DialogTitle>
        <DialogContent>
          <Stack spacing={1.2} sx={{ mt: 0.8 }}>
            <TextField select label="Task" value={assignForm.task_id} onChange={(e) => setAssignForm((p) => ({ ...p, task_id: e.target.value }))}>
              {tasks.map((t) => <MenuItem key={t.id} value={t.id}>{t.task_name}</MenuItem>)}
            </TextField>
            <TextField select label="Employee" value={assignForm.assigned_to_employee_id} onChange={(e) => {
              const emp = employees.find((x) => String(x.id) === String(e.target.value));
              setAssignForm((p) => ({ ...p, assigned_to_employee_id: e.target.value, assigned_to_name: emp?.name || "" }));
            }}>
              {employees.map((e) => <MenuItem key={e.id} value={e.id}>{e.name}</MenuItem>)}
            </TextField>
            <TextField type="date" label="Due Date" value={assignForm.due_date} InputLabelProps={{ shrink: true }} onChange={(e) => setAssignForm((p) => ({ ...p, due_date: e.target.value }))} />
            <TextField select label="Frequency" value={assignForm.frequency_type} onChange={(e) => setAssignForm((p) => ({ ...p, frequency_type: e.target.value }))}>
              <MenuItem value="ONE_TIME">ONE_TIME</MenuItem>
              <MenuItem value="DAILY">DAILY</MenuItem>
              <MenuItem value="WEEKLY">WEEKLY</MenuItem>
              <MenuItem value="MONTHLY">MONTHLY</MenuItem>
            </TextField>
            <TextField select label="Status" value={assignForm.status} onChange={(e) => setAssignForm((p) => ({ ...p, status: e.target.value }))}>
              <MenuItem value="ASSIGNED">ASSIGNED</MenuItem>
              <MenuItem value="COMPLETED">COMPLETED</MenuItem>
              <MenuItem value="OVERDUE">OVERDUE</MenuItem>
            </TextField>
            <TextField label="Notes" value={assignForm.notes} onChange={(e) => setAssignForm((p) => ({ ...p, notes: e.target.value }))} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpenAssign(false)}>Cancel</Button>
          <Button variant="contained" onClick={saveAssign} disabled={saving || !assignForm.task_id}>Save</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={openLog} onClose={() => setOpenLog(false)} fullWidth maxWidth="sm">
        <DialogTitle>{logMode === "edit" ? "Edit Activity Log" : "Log Maintenance Activity"}</DialogTitle>
        <DialogContent>
          <Stack spacing={1.2} sx={{ mt: 0.8 }}>
            <TextField select label="Assignment (optional)" value={logForm.assignment_id} onChange={(e) => setLogForm((p) => ({ ...p, assignment_id: e.target.value }))}>
              <MenuItem value="">None</MenuItem>
              {assignments.map((a) => <MenuItem key={a.id} value={a.id}>{a.task_name} - {String(a.due_date).slice(0, 10)}</MenuItem>)}
            </TextField>
            <TextField select label="Task" value={logForm.task_id} onChange={(e) => setLogForm((p) => ({ ...p, task_id: e.target.value }))}>
              {tasks.map((t) => <MenuItem key={t.id} value={t.id}>{t.task_name}</MenuItem>)}
            </TextField>
            <TextField select label="Performed By" value={logForm.performed_by_employee_id} onChange={(e) => {
              const emp = employees.find((x) => String(x.id) === String(e.target.value));
              setLogForm((p) => ({ ...p, performed_by_employee_id: e.target.value, performed_by_name: emp?.name || "" }));
            }}>
              {employees.map((e) => <MenuItem key={e.id} value={e.id}>{e.name}</MenuItem>)}
            </TextField>
            <TextField type="date" label="Performed Date" value={logForm.performed_date} InputLabelProps={{ shrink: true }} onChange={(e) => setLogForm((p) => ({ ...p, performed_date: e.target.value }))} />
            <TextField label="Start Time (09:00 AM)" value={logForm.start_time} onChange={(e) => setLogForm((p) => ({ ...p, start_time: e.target.value }))} />
            <TextField label="End Time (09:30 AM)" value={logForm.end_time} onChange={(e) => setLogForm((p) => ({ ...p, end_time: e.target.value }))} />
            <Stack direction="row" spacing={1}>
              <Button variant={logForm.pit1_done ? "contained" : "outlined"} onClick={() => setLogForm((p) => ({ ...p, pit1_done: !p.pit1_done }))}>Pit 1</Button>
              <Button variant={logForm.pit2_done ? "contained" : "outlined"} onClick={() => setLogForm((p) => ({ ...p, pit2_done: !p.pit2_done }))}>Pit 2</Button>
              <Button variant={logForm.big_pit_done ? "contained" : "outlined"} onClick={() => setLogForm((p) => ({ ...p, big_pit_done: !p.big_pit_done }))}>Big Pit</Button>
            </Stack>
            <TextField label="Washer No" value={logForm.washer_no} onChange={(e) => setLogForm((p) => ({ ...p, washer_no: e.target.value }))} />
            <TextField label="Notes" value={logForm.notes} onChange={(e) => setLogForm((p) => ({ ...p, notes: e.target.value }))} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpenLog(false)}>Cancel</Button>
          <Button variant="contained" onClick={saveLog} disabled={saving || !logForm.task_id || !logForm.performed_by_name}>Save</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default MaintenancePage;
