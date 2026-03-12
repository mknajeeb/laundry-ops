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
  MenuItem,
  Paper,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import {
  createMaintenanceAssignment,
  createMaintenanceLog,
  createMaintenanceTask,
  getEmployees,
  getGeofenceConfig,
  getMaintenanceAgenda,
  getMaintenanceAssignments,
  getMaintenanceLogs,
  getMaintenanceTasks,
  saveGeofenceConfig,
} from "../api";

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
  const [geofence, setGeofence] = useState({
    label: "Work",
    latitude: "",
    longitude: "",
    radius_m: "35",
    updated_by: "admin",
  });

  const [taskForm, setTaskForm] = useState({ task_code: "", task_name: "", category: "CLEANING" });
  const [assignForm, setAssignForm] = useState({
    task_id: "",
    assigned_to_employee_id: "",
    assigned_to_name: "",
    due_date: new Date().toISOString().slice(0, 10),
    frequency_type: "ONE_TIME",
    frequency_interval: 1,
    weekdays_csv: "",
    notes: "",
    created_by: "admin",
  });
  const [logForm, setLogForm] = useState({
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
  });

  const load = async () => {
    try {
      const [t, a, l, e, ag, g] = await Promise.all([
        getMaintenanceTasks(),
        getMaintenanceAssignments(),
        getMaintenanceLogs(),
        getEmployees(),
        getMaintenanceAgenda(),
        getGeofenceConfig(),
      ]);
      setTasks(Array.isArray(t.data) ? t.data : []);
      setAssignments(Array.isArray(a.data) ? a.data : []);
      setLogs(Array.isArray(l.data) ? l.data : []);
      setEmployees(Array.isArray(e.data) ? e.data : []);
      setAgenda(Array.isArray(ag.data) ? ag.data : []);
      const gf = g?.data?.geofence;
      if (gf) {
        setGeofence({
          label: gf.label || "Work",
          latitude: String(gf.latitude ?? ""),
          longitude: String(gf.longitude ?? ""),
          radius_m: String(gf.radius_m ?? "35"),
          updated_by: "admin",
        });
      }
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: "Failed to load maintenance data." });
    }
  };

  useEffect(() => {
    load();
  }, []);

  const overdueCount = useMemo(
    () => assignments.filter((x) => String(x.status).toUpperCase() !== "COMPLETED" && new Date(x.due_date) < new Date()).length,
    [assignments]
  );

  const saveTask = async () => {
    try {
      setSaving(true);
      await createMaintenanceTask(taskForm);
      setOpenTask(false);
      setTaskForm({ task_code: "", task_name: "", category: "CLEANING" });
      await load();
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: e?.response?.data?.error || "Task create failed." });
    } finally {
      setSaving(false);
    }
  };

  const saveAssign = async () => {
    try {
      setSaving(true);
      await createMaintenanceAssignment(assignForm);
      setOpenAssign(false);
      await load();
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: e?.response?.data?.error || "Assignment failed." });
    } finally {
      setSaving(false);
    }
  };

  const saveLog = async () => {
    try {
      setSaving(true);
      await createMaintenanceLog(logForm);
      setOpenLog(false);
      await load();
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: e?.response?.data?.error || "Log save failed." });
    } finally {
      setSaving(false);
    }
  };

  const saveGeo = async () => {
    try {
      setSaving(true);
      await saveGeofenceConfig({
        ...geofence,
        latitude: Number(geofence.latitude),
        longitude: Number(geofence.longitude),
        radius_m: Number(geofence.radius_m),
        active: true,
      });
      setMessage({ type: "success", text: "Geofence updated." });
    } catch (e) {
      console.error(e);
      setMessage({ type: "error", text: e?.response?.data?.error || "Geofence save failed." });
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
      {message.text && <Alert severity={message.type} sx={{ mt: 1 }}>{message.text}</Alert>}

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
            <Button variant="contained" onClick={() => setOpenAssign(true)}>Assign Task</Button>
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
                <Chip label={a.status} color={String(a.status).toUpperCase() === "COMPLETED" ? "success" : "warning"} />
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
            <Button variant="contained" onClick={() => setOpenLog(true)}>Log Task</Button>
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
                <Chip label={l.source_type} />
              </Stack>
            ))}
          </Stack>
        </Paper>
      )}

      {tab === "TASKS" && (
        <Paper sx={{ mt: 1.2, p: 1.5, borderRadius: 2 }}>
          <Stack direction="row" justifyContent="space-between">
            <Typography sx={{ fontSize: 20 }}>Task Catalog</Typography>
            <Button variant="contained" onClick={() => setOpenTask(true)}>Add Task</Button>
          </Stack>
          <Stack spacing={1} sx={{ mt: 1 }}>
            {tasks.map((t) => (
              <Stack key={t.id} direction="row" justifyContent="space-between" sx={{ border: "1px solid #e5e7eb", p: 1, borderRadius: 1.5 }}>
                <Typography>{t.task_name}</Typography>
                <Stack direction="row" spacing={1}><Chip label={t.task_code} /><Chip label={t.category} /></Stack>
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
            <Button variant="contained" onClick={saveGeo} disabled={saving}>Save GeoFence</Button>
          </Stack>
        </Paper>
      )}

      <Dialog open={openTask} onClose={() => setOpenTask(false)} fullWidth maxWidth="sm">
        <DialogTitle>Add Task</DialogTitle>
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
        <DialogTitle>Assign Task</DialogTitle>
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
            <TextField label="Notes" value={assignForm.notes} onChange={(e) => setAssignForm((p) => ({ ...p, notes: e.target.value }))} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpenAssign(false)}>Cancel</Button>
          <Button variant="contained" onClick={saveAssign} disabled={saving || !assignForm.task_id}>Assign</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={openLog} onClose={() => setOpenLog(false)} fullWidth maxWidth="sm">
        <DialogTitle>Log Maintenance Activity</DialogTitle>
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
            <TextField label="Start Time (e.g. 09:00 AM)" value={logForm.start_time} onChange={(e) => setLogForm((p) => ({ ...p, start_time: e.target.value }))} />
            <TextField label="End Time (e.g. 09:30 AM)" value={logForm.end_time} onChange={(e) => setLogForm((p) => ({ ...p, end_time: e.target.value }))} />
            <Stack direction="row" spacing={1}>
              <Button variant={logForm.pit1_done ? "contained" : "outlined"} onClick={() => setLogForm((p) => ({ ...p, pit1_done: !p.pit1_done }))}>Pit 1</Button>
              <Button variant={logForm.pit2_done ? "contained" : "outlined"} onClick={() => setLogForm((p) => ({ ...p, pit2_done: !p.pit2_done }))}>Pit 2</Button>
              <Button variant={logForm.big_pit_done ? "contained" : "outlined"} onClick={() => setLogForm((p) => ({ ...p, big_pit_done: !p.big_pit_done }))}>Big Pit</Button>
            </Stack>
            <TextField label="Washer No (optional)" value={logForm.washer_no} onChange={(e) => setLogForm((p) => ({ ...p, washer_no: e.target.value }))} />
            <TextField label="Notes" value={logForm.notes} onChange={(e) => setLogForm((p) => ({ ...p, notes: e.target.value }))} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpenLog(false)}>Cancel</Button>
          <Button variant="contained" onClick={saveLog} disabled={saving || !logForm.task_id || !logForm.performed_by_name}>Save Log</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default MaintenancePage;

