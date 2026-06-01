import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  FormLabel,
  MenuItem,
  Radio,
  RadioGroup,
  Paper,
  Stack,
  Switch,
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
  getDailyOperationalResetSettings,
  getEmployees,
  getGeofenceConfig,
  getMaintenanceAgenda,
  getMaintenanceAssignments,
  getMaintenanceLogs,
  getMaintenanceTasks,
  putDailyOperationalResetSettings,
  putOpsUiFlags,
  saveGeofenceConfig,
  updateMaintenanceAssignment,
  updateMaintenanceLog,
  updateMaintenanceTask,
} from "../api";
import { useI18n } from "../i18n/I18nContext";
import { useAuth } from "../context/AuthContext";

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
  const { t } = useI18n();
  const { opsUi, refreshMe } = useAuth();
  const [tab, setTab] = useState("ASSIGNED");
  const [tasks, setTasks] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [logs, setLogs] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [agenda, setAgenda] = useState([]);
  const [message, setMessage] = useState({ type: "info", text: "" });
  const [saving, setSaving] = useState(false);
  const [dailyResetSettings, setDailyResetSettings] = useState(undefined);

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
    let cancelled = false;
    (async () => {
      try {
        const r = await getDailyOperationalResetSettings();
        if (!cancelled)
          setDailyResetSettings(
            r.data || { enabled: false, last_reset_est_date: null, trigger: "lazy" },
          );
      } catch {
        if (!cancelled) setDailyResetSettings(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

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

      {dailyResetSettings != null && (
        <Paper sx={{ mt: 1.2, p: 1.5, borderRadius: 2, border: "1px solid #e2e8f0" }}>
          <Typography sx={{ fontWeight: 700, mb: 0.5 }}>{t("maintenance.dailyResetTitle")}</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.2 }}>
            {t("maintenance.dailyResetHint")}
          </Typography>
          <FormControlLabel
            control={
              <Switch
                checked={!!dailyResetSettings.enabled}
                disabled={saving}
                onChange={async (e) => {
                  const v = e.target.checked;
                  const trig =
                    dailyResetSettings.trigger === "midnight_est" ? "midnight_est" : "lazy";
                  try {
                    setSaving(true);
                    const r = await putDailyOperationalResetSettings({
                      enabled: v,
                      trigger: trig,
                    });
                    setDailyResetSettings(
                      r.data || { ...dailyResetSettings, enabled: v, trigger: trig },
                    );
                    setMessage({ type: "success", text: t("maintenance.dailyResetSaved") });
                  } catch (err) {
                    console.error(err);
                    setMessage({
                      type: "error",
                      text: err?.response?.data?.error || "Could not save daily reset setting.",
                    });
                  } finally {
                    setSaving(false);
                  }
                }}
              />
            }
            label={t("maintenance.dailyResetLabel")}
          />
          <FormControl component="fieldset" variant="standard" sx={{ mt: 1.2, display: "block" }}>
            <FormLabel component="legend">{t("maintenance.dailyResetTriggerLabel")}</FormLabel>
            <RadioGroup
              row
              value={dailyResetSettings.trigger === "midnight_est" ? "midnight_est" : "lazy"}
              onChange={async (e) => {
                const v = e.target.value;
                try {
                  setSaving(true);
                  const r = await putDailyOperationalResetSettings({
                    enabled: !!dailyResetSettings.enabled,
                    trigger: v,
                  });
                  setDailyResetSettings(r.data || { ...dailyResetSettings, trigger: v });
                  setMessage({ type: "success", text: t("maintenance.dailyResetSaved") });
                } catch (err) {
                  console.error(err);
                  setMessage({
                    type: "error",
                    text: err?.response?.data?.error || "Could not save daily reset setting.",
                  });
                } finally {
                  setSaving(false);
                }
              }}
            >
              <FormControlLabel
                value="lazy"
                control={<Radio disabled={saving} />}
                label={t("maintenance.dailyResetTriggerLazy")}
              />
              <FormControlLabel
                value="midnight_est"
                control={<Radio disabled={saving} />}
                label={t("maintenance.dailyResetTriggerMidnight")}
              />
            </RadioGroup>
          </FormControl>
          {dailyResetSettings.trigger === "midnight_est" && (
            <Typography variant="caption" color="warning.main" display="block" sx={{ mt: 1 }}>
              {t("maintenance.dailyResetCronHint")}
            </Typography>
          )}
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
            {t("maintenance.dailyResetLast")}: {dailyResetSettings.last_reset_est_date || "—"}
          </Typography>
        </Paper>
      )}

      <Paper sx={{ mt: 1.2, p: 1.5, borderRadius: 2, border: "1px solid #e2e8f0" }}>
        <Typography sx={{ fontWeight: 700, mb: 0.5 }}>Checkout and orders devices</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.2 }}>
          When a switch is off, that feature is hidden or disabled for everyone in this business (admins should use Maintenance to turn it back on).
          When scan or browse is on, Checkout and Orders open with that mode enabled by default; if both are on, scan is the default until someone changes the toolbar toggles.
        </Typography>
        <FormControlLabel
          control={
            <Switch
              checked={!!opsUi?.scan_lookup_enabled}
              disabled={saving}
              onChange={async (e) => {
                const v = e.target.checked;
                try {
                  setSaving(true);
                  await putOpsUiFlags({ scan_lookup_enabled: v });
                  await refreshMe();
                  setMessage({ type: "success", text: "Scan lookup setting saved." });
                } catch (err) {
                  console.error(err);
                  setMessage({
                    type: "error",
                    text: err?.response?.data?.error || "Could not save scan setting (admin only).",
                  });
                } finally {
                  setSaving(false);
                }
              }}
            />
          }
          label="Bag QR scan / scan lookup (Checkout & Orders)"
        />
        <FormControlLabel
          sx={{ display: "block", mt: 0.5 }}
          control={
            <Switch
              checked={!!opsUi?.browse_list_enabled}
              disabled={saving}
              onChange={async (e) => {
                const v = e.target.checked;
                try {
                  setSaving(true);
                  await putOpsUiFlags({ browse_list_enabled: v });
                  await refreshMe();
                  setMessage({ type: "success", text: "Browse list setting saved." });
                } catch (err) {
                  console.error(err);
                  setMessage({
                    type: "error",
                    text: err?.response?.data?.error || "Could not save browse list setting (admin only).",
                  });
                } finally {
                  setSaving(false);
                }
              }}
            />
          }
          label="Browse list and A–Z index (Checkout and Orders)"
        />
        <FormControlLabel
          sx={{ display: "block", mt: 0.5 }}
          control={
            <Switch
              checked={!!opsUi?.dryer_qr_scan_enabled}
              disabled={saving}
              onChange={async (e) => {
                const v = e.target.checked;
                try {
                  setSaving(true);
                  await putOpsUiFlags({ dryer_qr_scan_enabled: v });
                  await refreshMe();
                  setMessage({ type: "success", text: "Dryer QR setting saved." });
                } catch (err) {
                  console.error(err);
                  setMessage({
                    type: "error",
                    text: err?.response?.data?.error || "Could not save dryer QR setting (admin only).",
                  });
                } finally {
                  setSaving(false);
                }
              }}
            />
          }
          label="Dryer QR scan (Orders → dryer flow)"
        />
        <FormControlLabel
          sx={{ display: "block", mt: 0.5 }}
          control={
            <Switch
              checked={opsUi?.upload_batch_require_both_csv !== false}
              disabled={saving}
              onChange={async (e) => {
                const v = e.target.checked;
                try {
                  setSaving(true);
                  await putOpsUiFlags({ upload_batch_require_both_csv: v });
                  await refreshMe();
                  setMessage({
                    type: "success",
                    text: v
                      ? "Upload batch now requires portal order CSV and scan-events CSV before confirm."
                      : "Upload batch may be confirmed with only the portal CSV or only scan-events (override).",
                  });
                } catch (err) {
                  console.error(err);
                  setMessage({
                    type: "error",
                    text: err?.response?.data?.error || "Could not save upload batch setting (admin only).",
                  });
                } finally {
                  setSaving(false);
                }
              }}
            />
          }
          label="Require portal order CSV and Rinse scan-events CSV before confirming upload batch"
        />
        <FormControl sx={{ display: "block", mt: 1.5 }} disabled={saving}>
          <FormLabel sx={{ fontWeight: 600, color: "text.primary", mb: 0.5 }}>
            Checkout batch source
          </FormLabel>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 0.75 }}>
            Controls which confirmed batch drives Rush Bag Checkout card subtitles. Washpro manual upload: Manual.
            VeeWash scheduled scrape: Auto. Switch to Auto when Washpro moves to scheduled scrape.
          </Typography>
          <RadioGroup
            row
            value={opsUi?.checkout_batch_source === "auto" ? "auto" : "manual"}
            onChange={async (e) => {
              const v = e.target.value === "auto" ? "auto" : "manual";
              try {
                setSaving(true);
                await putOpsUiFlags({ checkout_batch_source: v });
                await refreshMe();
                setMessage({
                  type: "success",
                  text:
                    v === "auto"
                      ? "Checkout cards now use the latest auto-scrape batch."
                      : "Checkout cards now use the latest manual upload batch.",
                });
              } catch (err) {
                console.error(err);
                setMessage({
                  type: "error",
                  text: err?.response?.data?.error || "Could not save checkout batch source (admin only).",
                });
              } finally {
                setSaving(false);
              }
            }}
          >
            <FormControlLabel value="manual" control={<Radio />} label="Manual upload" />
            <FormControlLabel value="auto" control={<Radio />} label="Auto scrape" />
          </RadioGroup>
        </FormControl>
      </Paper>

      <Paper sx={{ mt: 1.2, borderRadius: 2, overflow: "hidden" }}>
        <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" scrollButtons="auto">
          <Tab value="ASSIGNED" label="Assigned Tasks" />
          <Tab value="ADHOC" label="Ad-hoc Log" />
          <Tab value="TASKS" label="Task Catalog" />
          <Tab value="GEOFENCE" label="GeoFence" />
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
