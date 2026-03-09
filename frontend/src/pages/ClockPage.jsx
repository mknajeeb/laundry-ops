import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Paper,
  Stack,
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
  const [live, setLive] = useState({ at_work_count: 0, at_work: [] });

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const [empRes, liveRes] = await Promise.all([getEmployees(), getAttendanceLive()]);
        const emp = Array.isArray(empRes.data) ? empRes.data : [];
        setEmployees(emp);
        if (emp.length) {
          setEmployeeId((prev) => prev || String(emp[0].id));
        }
        setLive(liveRes.data || { at_work_count: 0, at_work: [] });
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
            // silent background ping failure
            console.error(error);
          }
        },
        () => {},
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 20000 }
      );
    }, 30000);

    return () => clearInterval(intervalId);
  }, [employeeId]);

  const runPunch = (event_type) => {
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
          };

          if (event_type === "RINSE_SHIFT_START" || event_type === "RINSE_SHIFT_END") {
            const personal = window.prompt("Enter personal bags count for today (optional):", "0");
            if (personal !== null && personal !== "") {
              payload.personal_bags = Number(personal);
            }
          }

          const res = await punchAttendance(payload);
          setMessage({
            type: "success",
            text: `${event_type.replaceAll("_", " ")} recorded (${Math.round(res.data.distance_m)}m).`,
          });

          const liveRes = await getAttendanceLive();
          setLive(liveRes.data || { at_work_count: 0, at_work: [] });
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
      <Typography sx={{ color: "#6b7280", mt: 0.3 }}>Geo-fenced time punches</Typography>

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
        <Typography sx={{ fontWeight: 800, mb: 0.8 }}>Punch Actions</Typography>
        <Stack spacing={0.8}>
          <ActionButton icon={<PlayArrow />} label="Clock In" onClick={() => runPunch("CLOCK_IN")} disabled={busy} />
          <ActionButton icon={<Logout />} label="Clock Out" onClick={() => runPunch("CLOCK_OUT")} disabled={busy} />
          <ActionButton icon={<Coffee />} label="Break Start" onClick={() => runPunch("BREAK_START")} disabled={busy} />
          <ActionButton icon={<AccessTime />} label="Break End" onClick={() => runPunch("BREAK_END")} disabled={busy} />
          <ActionButton icon={<LocalShipping />} label="Rinse Shift Start" onClick={() => runPunch("RINSE_SHIFT_START")} disabled={busy} />
          <ActionButton icon={<Stop />} label="Rinse Shift End" onClick={() => runPunch("RINSE_SHIFT_END")} disabled={busy} />
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
    </Box>
  );
}

function ActionButton({ icon, label, onClick, disabled }) {
  return (
    <Button
      fullWidth
      startIcon={icon}
      variant="contained"
      onClick={onClick}
      disabled={disabled}
      sx={{ justifyContent: "flex-start", textTransform: "none", py: 1.1, borderRadius: 1.5 }}
    >
      {label}
    </Button>
  );
}

export default ClockPage;
