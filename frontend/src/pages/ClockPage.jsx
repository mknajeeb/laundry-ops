import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Divider,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import { AccessTime, Coffee, Logout, PlayArrow, Refresh } from "@mui/icons-material";
import {
  getMonitorSessions,
  getPayrollCycles,
  getTaSessionCurrent,
  taBreakEnd,
  taBreakStart,
  taClockIn,
  taClockOut,
} from "../api";
import { useAuth } from "../context/AuthContext";

function formatDuration(totalSeconds) {
  const s = Math.max(0, Math.floor(Number(totalSeconds) || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h} hr ${m} min`;
}

function todayIsoDate() {
  const d = new Date();
  const y = d.getFullYear();
  const mo = String(d.getMonth() + 1).padStart(2, "0");
  const da = String(d.getDate()).padStart(2, "0");
  return `${y}-${mo}-${da}`;
}

function ClockPage({ user: washproUser }) {
  const { user: taUser, hasPerm } = useAuth();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [sessionRes, setSessionRes] = useState(null);
  const [managerSnap, setManagerSnap] = useState(null);
  const [message, setMessage] = useState({ type: "info", text: "" });
  const [showClockOutConfirm, setShowClockOutConfirm] = useState(false);

  const lastPosRef = useRef({ lat: null, lng: null });

  const canMonitor = hasPerm("ta.monitor");

  const foldedByName = useMemo(() => {
    if (taUser?.first_name || taUser?.last_name) {
      return [taUser.first_name, taUser.last_name].filter(Boolean).join(" ").trim();
    }
    return taUser?.display_name || washproUser?.display_name || washproUser?.username || "User";
  }, [
    taUser?.first_name,
    taUser?.last_name,
    taUser?.display_name,
    washproUser?.display_name,
    washproUser?.username,
  ]);

  const loadSession = useCallback(
    async (silent, lat, lng) => {
      try {
        if (!silent) setLoading(true);
        const params = {};
        if (lat != null && lng != null) {
          params.latitude = lat;
          params.longitude = lng;
        }
        const res = await getTaSessionCurrent(params);
        setSessionRes(res.data || null);
      } catch (error) {
        console.error(error);
        const err = error?.response?.data?.error || "Failed to load clock state.";
        if (!silent) setMessage({ type: "error", text: err });
      } finally {
        if (!silent) setLoading(false);
      }
    },
    []
  );

  const loadManager = useCallback(async () => {
    if (!canMonitor) return;
    try {
      const [cyclesRes, sessRes] = await Promise.all([getPayrollCycles(), getMonitorSessions({})]);
      const cycles = cyclesRes.data || [];
      const today = todayIsoDate();
      const current =
        cycles.find(
          (c) =>
            String(c.week_start_date || "") <= today && String(c.week_end_date || "") >= today
        ) || cycles[0];
      const rows = sessRes.data || [];
      const atWork = rows.filter((r) => r.status === "active").length;
      setManagerSnap({ cycle: current, atWork });
    } catch (e) {
      console.error(e);
    }
  }, [canMonitor]);

  const refreshAll = useCallback(
    async (silent) => {
      await new Promise((resolve) => {
        navigator.geolocation.getCurrentPosition(
          async (pos) => {
            const { latitude: la, longitude: ln } = pos.coords;
            lastPosRef.current = { lat: la, lng: ln };
            await loadSession(silent, la, ln);
            resolve();
          },
          async () => {
            await loadSession(silent, null, null);
            resolve();
          },
          { enableHighAccuracy: true, timeout: 12000, maximumAge: silent ? 60000 : 0 }
        );
      });
      if (canMonitor) await loadManager();
    },
    [loadSession, loadManager, canMonitor]
  );

  useEffect(() => {
    refreshAll(false);
  }, [refreshAll]);

  useEffect(() => {
    const id = setInterval(() => {
      const { lat, lng } = lastPosRef.current;
      loadSession(true, lat, lng);
      if (canMonitor) loadManager();
    }, 30000);
    return () => clearInterval(id);
  }, [loadSession, loadManager, canMonitor]);

  useEffect(() => {
    const id = setInterval(() => {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          lastPosRef.current = { lat: pos.coords.latitude, lng: pos.coords.longitude };
          loadSession(true, pos.coords.latitude, pos.coords.longitude);
        },
        () => {},
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 20000 }
      );
    }, 30000);
    return () => clearInterval(id);
  }, [loadSession]);

  const session = sessionRes?.session;
  const operational = sessionRes?.operational;

  const runWithPosition = (fn) => {
    setBusy(true);
    navigator.geolocation.getCurrentPosition(
      async (position) => {
        const { latitude, longitude } = position.coords;
        lastPosRef.current = { lat: latitude, lng: longitude };
        try {
          await fn(latitude, longitude);
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

  const runAction = async (action) => {
    if (action === "CLOCK_IN") {
      runWithPosition(async (lat, lng) => {
        await taClockIn({ latitude: lat, longitude: lng });
        setMessage({ type: "success", text: "Clock in recorded." });
        await refreshAll(true);
      });
      return;
    }
    if (action === "CLOCK_OUT") {
      runWithPosition(async (lat, lng) => {
        await taClockOut({ latitude: lat, longitude: lng });
        setMessage({ type: "success", text: "Clock out recorded." });
        setShowClockOutConfirm(false);
        await refreshAll(true);
      });
      return;
    }
    if (action === "BREAK_START") {
      setBusy(true);
      try {
        await taBreakStart();
        setMessage({ type: "success", text: "Break started." });
        await refreshAll(true);
      } catch (error) {
        const err = error?.response?.data?.error || "Action failed.";
        setMessage({ type: "error", text: err });
      } finally {
        setBusy(false);
      }
      return;
    }
    if (action === "BREAK_END") {
      setBusy(true);
      try {
        await taBreakEnd();
        setMessage({ type: "success", text: "Break ended." });
        await refreshAll(true);
      } catch (error) {
        const err = error?.response?.data?.error || "Action failed.";
        setMessage({ type: "error", text: err });
      } finally {
        setBusy(false);
      }
    }
  };

  const isClockedIn = !!session;
  const onBreak = !!session?.open_break;
  const workedLabel =
      session?.elapsed_work_seconds != null
      ? formatDuration(session.elapsed_work_seconds)
      : "0 hr 0 min";

  const geoHint = useMemo(() => {
    if (!operational?.reasons?.length) return null;
    return operational.reasons.join(", ");
  }, [operational]);

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
      {geoHint && isClockedIn && !onBreak && (
        <Alert severity="warning" sx={{ mb: 1.2 }}>
          {geoHint}
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
              onClick={() => runAction("CLOCK_IN")}
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
                <Typography sx={{ fontSize: 24, color: "#0f172a" }}>{workedLabel}</Typography>
              </Paper>

              <Stack alignItems={{ xs: "flex-start", md: "flex-end" }} spacing={0.5}>
                <Typography sx={{ color: "#0f172a", fontSize: 14 }}>
                  {session?.clock_in_at ? new Date(session.clock_in_at).toLocaleString() : ""}
                </Typography>
                <Typography sx={{ color: "#475569", fontSize: 14 }}>{foldedByName}</Typography>
                {!onBreak && (
                  <Button
                    variant="outlined"
                    startIcon={<Logout />}
                    onClick={() => setShowClockOutConfirm((v) => !v)}
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
                  onClick={() => runAction("BREAK_START")}
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
                  onClick={() => runAction("BREAK_END")}
                  sx={{ minWidth: 240, textTransform: "none", py: 1.2, borderRadius: 2 }}
                >
                  Back to Work
                </Button>
              )}
            </Stack>

            {showClockOutConfirm && !onBreak && (
              <Paper sx={{ p: 1.2, border: "1px solid #e5e7eb", borderRadius: 2, boxShadow: "none" }}>
                <Stack direction="row" spacing={1} justifyContent="center" alignItems="center">
                  <Button
                    variant="contained"
                    disabled={busy}
                    onClick={() => runAction("CLOCK_OUT")}
                    sx={{ textTransform: "none", minWidth: 180 }}
                  >
                    Confirm Clock Out
                  </Button>
                </Stack>
              </Paper>
            )}
          </Stack>
        )}
      </Paper>

      {canMonitor && (
        <Paper sx={{ mt: 1.2, p: 1.2, border: "1px solid #e5e7eb", borderRadius: 2, boxShadow: "none" }}>
          <Stack direction="row" alignItems="center" justifyContent="space-between">
            <Typography sx={{ color: "#0f172a" }}>Payroll snapshot</Typography>
            <Button startIcon={<Refresh />} onClick={() => refreshAll(true)} sx={{ textTransform: "none" }}>
              Refresh
            </Button>
          </Stack>
          <Divider sx={{ my: 1 }} />
          <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
            <Box>
              <Typography sx={{ color: "#64748b", fontSize: 13 }}>Payroll cycle (ref)</Typography>
              <Typography sx={{ color: "#0f172a" }}>
                {managerSnap?.cycle?.cycle_ref || "—"} ({managerSnap?.cycle?.week_start_date || "—"} to{" "}
                {managerSnap?.cycle?.week_end_date || "—"})
              </Typography>
            </Box>
            <Box>
              <Typography sx={{ color: "#64748b", fontSize: 13 }}>Active sessions (all cycles in view)</Typography>
              <Typography sx={{ color: "#0f172a" }}>{managerSnap?.atWork ?? "—"}</Typography>
            </Box>
          </Stack>
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
              onClick={() => runAction("BREAK_END")}
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
