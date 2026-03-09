import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import {
  AccessTime,
  Coffee,
  LocalShipping,
  Logout,
  PlayArrow,
  Stop,
} from "@mui/icons-material";
import {
  getAttendanceEventsToday,
  getAttendanceLive,
  getEmployees,
  pingAttendanceLocation,
  punchAttendance,
} from "../api";

function ClockPage() {
  const [employees, setEmployees] = useState([]);
  const [employeeId, setEmployeeId] = useState("");

  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const [message, setMessage] = useState({ type: "info", text: "" });
  const [live, setLive] = useState({ at_work_count: 0, at_work: [], all_today: [] });
  const [todayEvents, setTodayEvents] = useState([]);

  const [leaveDialogOpen, setLeaveDialogOpen] = useState(false);
  const [clockOutDialogOpen, setClockOutDialogOpen] = useState(false);
  const [personalBags, setPersonalBags] = useState("");

  const selectedEmployeeName = useMemo(
    () => employees.find((emp) => String(emp.id) === String(employeeId))?.name || "",
    [employees, employeeId]
  );

  const employeeLiveRow = useMemo(
    () => (live.all_today || []).find((row) => String(row.employee_id) === String(employeeId)),
    [live.all_today, employeeId]
  );

  const isClockedIn = (employeeLiveRow?.last_event || "").toUpperCase() === "CLOCK_IN";

  const rinseStart = useMemo(
    () => todayEvents.find((e) => e.event_type === "RINSE_SHIFT_START")?.event_time || null,
    [todayEvents]
  );

  const rinseEnd = useMemo(
    () => todayEvents.find((e) => e.event_type === "RINSE_SHIFT_END")?.event_time || null,
    [todayEvents]
  );

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const [empRes, liveRes] = await Promise.all([getEmployees(), getAttendanceLive()]);
        const emp = Array.isArray(empRes.data) ? empRes.data : [];
        setEmployees(emp);
        setEmployeeId((prev) => prev || (emp[0] ? String(emp[0].id) : ""));
        setLive(liveRes.data || { at_work_count: 0, at_work: [], all_today: [] });
      } catch (error) {
        console.error(error);
        setMessage({ type: "error", text: "Failed to load employees/live status." });
      } finally {
        setLoading(false);
      }
    }

    load();
  }, []);

  useEffect(() => {
    async function loadEvents() {
      if (!employeeId) return;
      try {
        const res = await getAttendanceEventsToday(Number(employeeId));
        setTodayEvents(Array.isArray(res.data) ? res.data : []);
      } catch (error) {
        console.error(error);
      }
    }

    loadEvents();
  }, [employeeId]);

  useEffect(() => {
    if (!employeeId) return;

    const intervalId = setInterval(() => {
      navigator.geolocation.getCurrentPosition(
        async (pos) => {
          try {
            await pingAttendanceLocation({
              employee_id: Number(employeeId),
              latitude: pos.coords.latitude,
              longitude: pos.coords.longitude,
            });
          } catch (error) {
            console.error(error);
          }
        },
        () => {},
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 20000 }
      );
    }, 30000);

    return () => clearInterval(intervalId);
  }, [employeeId]);

  const refreshLiveAndEvents = async () => {
    const [liveRes, eventsRes] = await Promise.all([
      getAttendanceLive(),
      employeeId ? getAttendanceEventsToday(Number(employeeId)) : Promise.resolve({ data: [] }),
    ]);

    setLive(liveRes.data || { at_work_count: 0, at_work: [], all_today: [] });
    setTodayEvents(Array.isArray(eventsRes.data) ? eventsRes.data : []);
  };

  const runPunch = (event_type, extra = {}) => {
    if (!employeeId) {
      setMessage({ type: "warning", text: "Select employee first." });
      return;
    }

    setBusy(true);

    navigator.geolocation.getCurrentPosition(
      async (position) => {
        try {
          const payload = {
            employee_id: Number(employeeId),
            event_type,
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
            device_time: new Date().toISOString(),
            ...extra,
          };

          const res = await punchAttendance(payload);
          setMessage({
            type: "success",
            text: `${event_type.replaceAll("_", " ")} recorded (${Math.round(res.data.distance_m)}m).`,
          });

          await refreshLiveAndEvents();
        } catch (error) {
          console.error(error);
          const text =
            error?.response?.data?.error ||
            "Punch failed. Check geofence settings or connection.";
          setMessage({ type: "error", text });
        } finally {
          setBusy(false);
        }
      },
      () => {
        setBusy(false);
        setMessage({ type: "error", text: "Location permission is required." });
      },
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 0 }
    );
  };

  const handlePrimaryPunch = () => {
    if (isClockedIn) {
      setClockOutDialogOpen(true);
    } else {
      runPunch("CLOCK_IN");
    }
  };

  const handleConfirmClockOut = () => {
    const bags = personalBags === "" ? null : Number(personalBags);
    runPunch("CLOCK_OUT", { personal_bags: bags });
    setClockOutDialogOpen(false);
    setPersonalBags("");
    setLeaveDialogOpen(false);
  };

  const formatTime = (value) => {
    if (!value) return "-";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return String(value);
    return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  };

  if (loading) {
    return (
      <Stack alignItems="center" justifyContent="center" sx={{ minHeight: "60vh" }} spacing={1.2}>
        <CircularProgress size={28} />
        <Typography color="text.secondary">Loading clock...</Typography>
      </Stack>
    );
  }

  return (
    <Box sx={{ minHeight: "100%", bgcolor: "#ffffff", px: { xs: 1.2, md: 2 }, py: 1.2 }}>
      <Typography sx={{ fontSize: 26, fontWeight: 900 }}>Clock</Typography>
      <Typography sx={{ color: "#6b7280", mt: 0.3 }}>Simple geo-fenced attendance</Typography>

      <Paper sx={{ mt: 1.2, p: 1.2, borderRadius: 2, border: "1px solid #e5e7eb", boxShadow: "none" }}>
        <Typography sx={{ fontWeight: 800, mb: 0.6 }}>Employee</Typography>
        <Stack direction="row" spacing={0.6} sx={{ flexWrap: "wrap", gap: 0.6 }}>
          {employees.map((emp) => (
            <Chip
              key={emp.id}
              label={emp.name}
              clickable
              color={String(emp.id) === employeeId ? "primary" : "default"}
              onClick={() => setEmployeeId(String(emp.id))}
            />
          ))}
        </Stack>
      </Paper>

      {message.text && (
        <Alert severity={message.type} sx={{ mt: 1.1 }}>
          {message.text}
        </Alert>
      )}

      <Paper sx={{ mt: 1.2, p: 1.2, borderRadius: 2, border: "1px solid #e5e7eb", boxShadow: "none" }}>
        <Typography sx={{ fontWeight: 800 }}>{selectedEmployeeName || "Select employee"}</Typography>
        <Typography sx={{ color: "#6b7280", mb: 1 }}>
          Status: {isClockedIn ? "Clocked In" : "Clocked Out"}
        </Typography>

        <Button
          fullWidth
          size="large"
          startIcon={isClockedIn ? <Logout /> : <PlayArrow />}
          variant="contained"
          onClick={handlePrimaryPunch}
          disabled={busy}
          sx={{ textTransform: "none", py: 1.2, fontWeight: 800, borderRadius: 1.8 }}
        >
          {isClockedIn ? "Clock Out" : "Clock In"}
        </Button>

        {isClockedIn && (
          <Button
            fullWidth
            variant="outlined"
            onClick={() => setLeaveDialogOpen(true)}
            disabled={busy}
            sx={{ mt: 0.9, textTransform: "none", py: 1.1, borderRadius: 1.8 }}
          >
            Leaving Work
          </Button>
        )}
      </Paper>

      <Paper sx={{ mt: 1.2, p: 1.2, borderRadius: 2, border: "1px solid #e5e7eb", boxShadow: "none" }}>
        <Typography sx={{ fontWeight: 800, mb: 0.8 }}>Rinse Shift</Typography>
        <Stack spacing={0.8}>
          <Button
            fullWidth
            startIcon={<AccessTime />}
            variant="outlined"
            onClick={() => runPunch("BREAK_END")}
            disabled={busy}
            sx={{ textTransform: "none", justifyContent: "flex-start" }}
          >
            End Break
          </Button>
          <Button
            fullWidth
            startIcon={<LocalShipping />}
            variant="outlined"
            onClick={() => runPunch("RINSE_SHIFT_START")}
            disabled={busy}
            sx={{ textTransform: "none", justifyContent: "flex-start" }}
          >
            Rinse Shift Start
          </Button>
          <Button
            fullWidth
            startIcon={<Stop />}
            variant="outlined"
            onClick={() => runPunch("RINSE_SHIFT_END")}
            disabled={busy}
            sx={{ textTransform: "none", justifyContent: "flex-start" }}
          >
            Rinse Shift End
          </Button>
          <Typography sx={{ fontSize: 13, color: "#6b7280" }}>
            Start: {formatTime(rinseStart)} • End: {formatTime(rinseEnd)}
          </Typography>
        </Stack>
      </Paper>

      <Paper sx={{ mt: 1.2, p: 1.2, borderRadius: 2, border: "1px solid #e5e7eb", boxShadow: "none" }}>
        <Typography sx={{ fontWeight: 800 }}>At Work Now: {live.at_work_count || 0}</Typography>
        <Stack spacing={0.5} sx={{ mt: 0.7 }}>
          {(live.at_work || []).map((row) => (
            <Typography key={row.employee_id} sx={{ fontSize: 14 }}>
              {row.name} {row.is_inside ? "• inside" : "• outside"}
            </Typography>
          ))}
          {(!live.at_work || !live.at_work.length) && (
            <Typography sx={{ color: "#6b7280", fontSize: 14 }}>No one currently clocked in.</Typography>
          )}
        </Stack>
      </Paper>

      <Dialog open={leaveDialogOpen} onClose={() => setLeaveDialogOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle>Leaving Work</DialogTitle>
        <DialogContent dividers>
          <Typography>Choose an action:</Typography>
        </DialogContent>
        <DialogActions sx={{ p: 2 }}>
          <Button
            startIcon={<Coffee />}
            variant="outlined"
            onClick={() => {
              runPunch("BREAK_START");
              setLeaveDialogOpen(false);
            }}
          >
            Start Break
          </Button>
          <Button
            startIcon={<Logout />}
            variant="contained"
            onClick={() => {
              setLeaveDialogOpen(false);
              setClockOutDialogOpen(true);
            }}
          >
            Clock Out
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={clockOutDialogOpen} onClose={() => setClockOutDialogOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle>Clock Out</DialogTitle>
        <DialogContent dividers>
          <Typography sx={{ mb: 1 }}>How many personal laundry bags today?</Typography>
          <TextField
            fullWidth
            size="small"
            type="number"
            inputProps={{ min: 0 }}
            value={personalBags}
            onChange={(e) => setPersonalBags(e.target.value)}
            placeholder="0"
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setClockOutDialogOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleConfirmClockOut}>
            Confirm Clock Out
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default ClockPage;
