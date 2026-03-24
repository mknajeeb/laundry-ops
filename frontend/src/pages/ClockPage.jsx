import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Divider,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { AccessTime, Coffee, Logout, PlayArrow, Refresh } from "@mui/icons-material";
import {
  getAttendanceMyState,
  getAttendancePayrollMonitor,
  pingAttendanceLocation,
  punchAttendanceMy,
} from "../api";

function ClockPage({ user }) {
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [state, setState] = useState(null);
  const [payroll, setPayroll] = useState(null);
  const [message, setMessage] = useState({ type: "info", text: "" });
  const [personalBags, setPersonalBags] = useState("");
  const [showClockOutInput, setShowClockOutInput] = useState(false);

  const foldedByName = useMemo(
    () => state?.employee_name || user?.display_name || user?.username || "User",
    [state?.employee_name, user?.display_name, user?.username]
  );

  const isManagerView = useMemo(() => {
    const roles = (user?.roles || []).map((r) => String(r).toUpperCase());
    return roles.includes("ADMIN");
  }, [user?.roles]);

  const load = async (silent = false) => {
    try {
      if (!silent) setLoading(true);
      if (isManagerView) {
        const [stateRes, payrollRes] = await Promise.all([
          getAttendanceMyState(),
          getAttendancePayrollMonitor(),
        ]);
        setState(stateRes.data || null);
        setPayroll(payrollRes.data || null);
      } else {
        const stateRes = await getAttendanceMyState();
        setState(stateRes.data || null);
        setPayroll(null);
      }
    } catch (error) {
      console.error(error);
      const err = error?.response?.data?.error || "Failed to load clock state.";
      setMessage({ type: "error", text: err });
    } finally {
      if (!silent) setLoading(false);
    }
  };

  useEffect(() => {
    load(false);
  }, [isManagerView]);

  useEffect(() => {
    const id = setInterval(() => load(true), 30000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (!state?.employee_id) return;

    const id = setInterval(() => {
      navigator.geolocation.getCurrentPosition(
        async (pos) => {
          try {
            await pingAttendanceLocation({
              employee_id: Number(state.employee_id),
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

    return () => clearInterval(id);
  }, [state?.employee_id]);

  const runPunch = (event_type, extra = {}) => {
    setBusy(true);
    navigator.geolocation.getCurrentPosition(
      async (position) => {
        try {
          const payload = {
            event_type,
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
            device_time: new Date().toISOString(),
            ...extra,
          };
          const res = await punchAttendanceMy(payload);
          setMessage({
            type: "success",
            text: `${res?.data?.event_type?.replaceAll("_", " ") || event_type} recorded.`,
          });
          setShowClockOutInput(false);
          setPersonalBags("");
          await load(true);
        } catch (error) {
          console.error(error);
          const err = error?.response?.data?.error || "Action failed.";
          setMessage({ type: "error", text: err });
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

  const isClockedIn = !!state?.is_clocked_in;
  const onBreak = !!state?.on_break;

  const capacitySuggestion = useMemo(() => {
    const current = Array.isArray(payroll?.worked_this_week) ? payroll.worked_this_week : [];
    const previous = Array.isArray(payroll?.worked_previous_week) ? payroll.worked_previous_week : [];
    const today = new Date();
    const nextDay = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1);
    const targetWeekday = nextDay.getDay(); // 0..6

    const byWeekday = (rows) => {
      const out = {};
      rows.forEach((r) => {
        const d = r?.d ? new Date(r.d) : null;
        if (!d || Number.isNaN(d.getTime())) return;
        out[d.getDay()] = Number(r.workers || 0);
      });
      return out;
    };

    const currentBy = byWeekday(current);
    const previousBy = byWeekday(previous);
    const cur = currentBy[targetWeekday] || 0;
    const prev = previousBy[targetWeekday] || 0;
    const recommended = Math.max(cur, prev);
    return {
      targetLabel: nextDay.toLocaleDateString([], { weekday: "long" }),
      current: cur,
      previous: prev,
      recommended,
    };
  }, [payroll?.worked_this_week, payroll?.worked_previous_week]);

  const handleClockOut = () => {
    const bags = personalBags === "" ? null : Number(personalBags);
    runPunch("CLOCK_OUT", { personal_bags: bags });
  };

  if (loading) {
    return (
      <Stack alignItems="center" justifyContent="center" sx={{ minHeight: "65vh" }} spacing={1.2}>
        <CircularProgress size={28} />
        <Typography color="text.secondary">Loading...</Typography>
      </Stack>
    );
  }

  return (
    <Box sx={{ p: { xs: 1.2, md: 2 }, minHeight: "100%", position: "relative" }}>
      {message.text && (
        <Alert severity={message.type} sx={{ mb: 1.2 }} onClose={() => setMessage({ type: "info", text: "" })}>
          {message.text}
        </Alert>
      )}

      <Paper sx={{ p: { xs: 1.6, md: 2 }, borderRadius: 2, border: "1px solid #dbe3ef", boxShadow: "none" }}>
        {!isClockedIn ? (
          <Stack alignItems="center" justifyContent="center" sx={{ minHeight: "56vh" }} spacing={2}>
            <Typography sx={{ fontSize: { xs: 26, md: 30 }, color: "#0f172a" }}>Hi {foldedByName}</Typography>
            <Button
              size="large"
              variant="contained"
              startIcon={<PlayArrow />}
              disabled={busy}
              onClick={() => runPunch("CLOCK_IN")}
              sx={{ minWidth: 280, py: 1.6, fontSize: 22, textTransform: "none", borderRadius: 2 }}
            >
              Clock In
            </Button>
          </Stack>
        ) : (
          <Stack spacing={1.4}>
            <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" spacing={1.2}>
              <Paper sx={{ p: 1.2, border: "1px solid #e5e7eb", boxShadow: "none", borderRadius: 2, minWidth: 190 }}>
                <Typography sx={{ color: "#64748b", fontSize: 13 }}>Working Time</Typography>
                <Typography sx={{ fontSize: 24, color: "#0f172a" }}>{state?.worked_label || "0 hr 0 min"}</Typography>
              </Paper>

              <Stack alignItems={{ xs: "flex-start", md: "flex-end" }} spacing={0.5}>
                <Typography sx={{ color: "#0f172a", fontSize: 14 }}>{state?.today_label || ""}</Typography>
                <Typography sx={{ color: "#475569", fontSize: 14 }}>{foldedByName}</Typography>
                {!onBreak && (
                  <Button
                    variant="outlined"
                    startIcon={<Logout />}
                    onClick={() => setShowClockOutInput((v) => !v)}
                    sx={{ textTransform: "none", borderRadius: 2 }}
                  >
                    Clock Out
                  </Button>
                )}
              </Stack>
            </Stack>

            <Stack direction="row" spacing={1} justifyContent="center">
              {!onBreak ? (
                <Button
                  variant="contained"
                  color="warning"
                  startIcon={<Coffee />}
                  disabled={busy}
                  onClick={() => runPunch("BREAK_START")}
                  sx={{ minWidth: 220, textTransform: "none", py: 1.2, borderRadius: 2 }}
                >
                  Take a Break
                </Button>
              ) : (
                <Button
                  variant="contained"
                  color="success"
                  startIcon={<AccessTime />}
                  disabled={busy}
                  onClick={() => runPunch("BREAK_END")}
                  sx={{ minWidth: 240, textTransform: "none", py: 1.2, borderRadius: 2 }}
                >
                  Back to Work
                </Button>
              )}
            </Stack>

            {showClockOutInput && !onBreak && (
              <Paper sx={{ p: 1.2, border: "1px solid #e5e7eb", borderRadius: 2, boxShadow: "none" }}>
                <Stack direction={{ xs: "column", md: "row" }} spacing={1} alignItems="center">
                  <TextField
                    fullWidth
                    size="small"
                    type="number"
                    inputProps={{ min: 0 }}
                    placeholder="Personal bags"
                    value={personalBags}
                    onChange={(e) => setPersonalBags(e.target.value)}
                  />
                  <Button variant="contained" disabled={busy} onClick={handleClockOut} sx={{ textTransform: "none", minWidth: 160 }}>
                    Confirm Clock Out
                  </Button>
                </Stack>
              </Paper>
            )}
          </Stack>
        )}
      </Paper>

      {state?.discrepancies?.length > 0 && (
        <Paper sx={{ mt: 1.2, p: 1.2, border: "1px solid #f5d0d0", borderRadius: 2, background: "#fff7f7", boxShadow: "none" }}>
          <Typography sx={{ color: "#7f1d1d", mb: 0.8 }}>Attendance Discrepancies</Typography>
          <Stack spacing={0.6}>
            {state.discrepancies.slice(0, 8).map((d) => (
              <Typography key={d.id} sx={{ color: "#991b1b", fontSize: 13 }}>
                {d.discrepancy_type} • {d.status} • {d.start_time ? new Date(d.start_time).toLocaleString() : ""}
              </Typography>
            ))}
          </Stack>
        </Paper>
      )}

      {isManagerView && (
      <Paper sx={{ mt: 1.2, p: 1.2, border: "1px solid #e5e7eb", borderRadius: 2, boxShadow: "none" }}>
        <Stack direction="row" alignItems="center" justifyContent="space-between">
          <Typography sx={{ color: "#0f172a" }}>Payroll Monitor</Typography>
          <Button startIcon={<Refresh />} onClick={() => load(true)} sx={{ textTransform: "none" }}>Refresh</Button>
        </Stack>
        <Divider sx={{ my: 1 }} />
        <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
          <Box>
            <Typography sx={{ color: "#64748b", fontSize: 13 }}>Payroll Cycle</Typography>
            <Typography sx={{ color: "#0f172a" }}>
              {payroll?.payroll_cycle?.code || "-"} ({payroll?.payroll_cycle?.week_start || "-"} to {payroll?.payroll_cycle?.week_end || "-"})
            </Typography>
          </Box>
          <Box>
            <Typography sx={{ color: "#64748b", fontSize: 13 }}>Working Now</Typography>
            <Typography sx={{ color: "#0f172a" }}>{payroll?.at_work_count ?? 0}</Typography>
          </Box>
          <Box>
            <Typography sx={{ color: "#64748b", fontSize: 13 }}>Discrepancies This Cycle</Typography>
            <Typography sx={{ color: "#0f172a" }}>{payroll?.discrepancies?.length ?? 0}</Typography>
          </Box>
        </Stack>
        <Divider sx={{ my: 1 }} />
        <Typography sx={{ color: "#64748b", fontSize: 13 }}>
          Next-day capacity ({capacitySuggestion.targetLabel})
        </Typography>
        <Typography sx={{ color: "#0f172a", mt: 0.3 }}>
          This week: {capacitySuggestion.current} • Previous week: {capacitySuggestion.previous} • Suggested staffing: {capacitySuggestion.recommended}
        </Typography>
      </Paper>
      )}

      {onBreak && (
        <Box
          sx={{
            position: "fixed",
            inset: 0,
            background: "rgba(15, 23, 42, 0.62)",
            zIndex: 1400,
            display: "grid",
            placeItems: "center",
            p: 2,
          }}
        >
          <Paper sx={{ p: 2, width: "min(480px, 92vw)", borderRadius: 2, textAlign: "center" }}>
            <Typography sx={{ color: "#ffffff", background: "#0f172a", borderRadius: 1.2, py: 0.8, mb: 1.2 }}>
              Break Active
            </Typography>
            <Typography sx={{ mb: 1.2 }}>Everything is paused while on break.</Typography>
            <Button
              variant="contained"
              color="success"
              startIcon={<AccessTime />}
              onClick={() => runPunch("BREAK_END")}
              disabled={busy}
              sx={{ minWidth: 220, textTransform: "none" }}
            >
              Back to Work
            </Button>
          </Paper>
        </Box>
      )}
    </Box>
  );
}

export default ClockPage;
