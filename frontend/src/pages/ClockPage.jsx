import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Grid,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import {
  authLogout,
  getClockPayrollUiSettings,
  getTaskTrackingTasks,
  getTaSessionCurrent,
  postTaskTrackingSwitchTask,
  taBreakEnd,
  taClockIn,
  taClockOut,
  clearAuthSession,
} from "../api";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";
import { asBool } from "../utils/bool";

const DEFAULT_CLOCK_UI = {
  dim_app_until_clocked_in: false,
  sign_out_after_clock_out: false,
  shared_device_attendance: false,
};

function normalizeClockUi(raw) {
  const d = { ...DEFAULT_CLOCK_UI, ...(raw && typeof raw === "object" ? raw : {}) };
  return {
    ...d,
    ask_personal_laundry_bags: asBool(d.ask_personal_laundry_bags, false),
    dim_app_until_clocked_in: asBool(d.dim_app_until_clocked_in, false),
    sign_out_after_clock_out: asBool(d.sign_out_after_clock_out, false),
    shared_device_attendance: asBool(d.shared_device_attendance, false),
  };
}

/** Minimal clock: Not at work / At work, optional first clock-in laundry bags (EST), checkout confirmation. */
function ClockPage({ user: washproUser }) {
  const navigate = useNavigate();
  const { t } = useI18n();
  const { user: taUser, loading: authLoading } = useAuth();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [sessionRes, setSessionRes] = useState(null);
  const [clockUi, setClockUi] = useState(DEFAULT_CLOCK_UI);

  const [checkInConfirmOpen, setCheckInConfirmOpen] = useState(false);
  const [bagsDialogOpen, setBagsDialogOpen] = useState(false);
  const [personalBags, setPersonalBags] = useState(0);
  const [checkoutConfirmOpen, setCheckoutConfirmOpen] = useState(false);
  const [actionError, setActionError] = useState("");
  const [tasks, setTasks] = useState([]);
  const [taskSelectOpen, setTaskSelectOpen] = useState(false);
  const [pendingTaskId, setPendingTaskId] = useState(null);
  const [switchTaskBusy, setSwitchTaskBusy] = useState(false);

  const lastPosRef = useRef({ lat: null, lng: null });

  const session = sessionRes?.session;
  const clockHints = sessionRes?.clock_hints;
  const taskTracking = session?.task_tracking || session?.job_tracking;
  const recentForceCheckout = sessionRes?.recent_force_checkout;
  const isClockedIn = !!session;

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

  const atWorkLabel = useMemo(
    () => t("clock.atWork").replace("{name}", foldedByName),
    [t, foldedByName]
  );

  const defaultCheckInTaskId = useMemo(() => {
    const lastId = clockHints?.last_check_in_task_id;
    if (lastId != null && tasks.some((task) => Number(task.id) === Number(lastId) && task.active !== false)) {
      return Number(lastId);
    }
    const firstActive = tasks.find((task) => task.active !== false);
    return firstActive?.id ?? tasks[0]?.id ?? null;
  }, [clockHints?.last_check_in_task_id, tasks]);

  const loadClockUi = useCallback(async () => {
    try {
      const res = await getClockPayrollUiSettings();
      const c = res.data?.clock || res.data;
      if (c && typeof c === "object") {
        setClockUi(normalizeClockUi(c));
      }
    } catch {
      setClockUi(DEFAULT_CLOCK_UI);
    }
  }, []);

  const loadTasks = useCallback(async () => {
    try {
      const res = await getTaskTrackingTasks();
      setTasks(Array.isArray(res.data) ? res.data : []);
    } catch {
      setTasks([]);
    }
  }, []);

  const loadSession = useCallback(async (silent, lat, lng) => {
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
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  const refreshAll = useCallback(
    async (silent) => {
      await new Promise((resolve) => {
        navigator.geolocation?.getCurrentPosition(
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
          {
            enableHighAccuracy: !silent,
            timeout: silent ? 8000 : 12000,
            maximumAge: silent ? 300000 : 0,
          }
        );
      });
    },
    [loadSession]
  );

  const refreshAfterAction = useCallback(async () => {
    const { lat, lng } = lastPosRef.current;
    if (lat != null && lng != null) {
      await loadSession(true, lat, lng);
    } else {
      await refreshAll(true);
    }
  }, [loadSession, refreshAll]);

  useEffect(() => {
    if (authLoading) return;
    loadClockUi();
    loadTasks();
  }, [authLoading, loadClockUi, loadTasks]);

  useEffect(() => {
    if (authLoading) return;
    refreshAll(false);
  }, [authLoading, refreshAll]);

  /** Legacy open break: end automatically so the simplified UI stays two-state only. */
  useEffect(() => {
    if (!session?.open_break) return undefined;
    let cancelled = false;
    (async () => {
      try {
        await taBreakEnd();
        if (!cancelled) await refreshAfterAction();
      } catch (e) {
        console.error(e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [session?.id, session?.open_break, refreshAfterAction]);

  useEffect(() => {
    if (authLoading || !isClockedIn) return undefined;
    const id = setInterval(() => {
      refreshAll(true);
    }, 30000);
    return () => clearInterval(id);
  }, [authLoading, isClockedIn, refreshAll]);

  const formatDeadline = (iso) => {
    if (!iso) return null;
    const d = new Date(String(iso).replace(" ", "T"));
    if (Number.isNaN(d.getTime())) return null;
    return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  };

  const scheduledEndLabel = formatDeadline(taskTracking?.effective_force_checkout_at);
  const checkInLabel = formatDeadline(session?.clock_in_at);

  const handleSwitchTask = async (taskId) => {
    setSwitchTaskBusy(true);
    setActionError("");
    try {
      await postTaskTrackingSwitchTask({ task_id: taskId });
      await refreshAfterAction();
    } catch (e) {
      const d = e?.response?.data;
      setActionError(d?.error || e?.message || "Could not switch task");
    } finally {
      setSwitchTaskBusy(false);
    }
  };

  const clockInWithTask = async (lat, lng, taskId, bags) => {
    const body = { latitude: lat, longitude: lng };
    if (taskId) body.task_id = taskId;
    if (bags != null) body.personal_laundry_bags = bags;
    await taClockIn(body);
    await refreshAfterAction();
  };

  const sharedDevice = asBool(clockUi.shared_device_attendance);

  const pinLockExcludedAdmin = useMemo(() => {
    const roles = Array.isArray(washproUser?.roles)
      ? washproUser.roles.map((r) => String(r).toUpperCase())
      : [];
    return (
      roles.includes("ADMIN") ||
      roles.includes("SUPER_ADMIN") ||
      roles.includes("PLATFORM_ADMIN")
    );
  }, [washproUser?.roles]);

  /** Clear session and show PIN lock (tenant admins keep the normal in-app session). */
  const lockSharedDeviceScreen = useCallback(async () => {
    try {
      await authLogout();
    } catch {
      /* ignore */
    }
    clearAuthSession();
    try {
      localStorage.removeItem("ta_token");
    } catch {
      /* ignore */
    }
    const slug =
      (typeof localStorage.getItem("washpro_org_slug") === "string" &&
        localStorage.getItem("washpro_org_slug")) ||
      washproUser?.organization_slug ||
      "";
    const s = String(slug).trim().toLowerCase();
    window.location.assign(s ? `/kiosk/${encodeURIComponent(s)}` : "/login");
  }, [washproUser?.organization_slug]);

  const runWithPosition = (fn) => {
    const run = async (lat, lng) => {
      setActionError("");
      try {
        await fn(lat, lng);
      } catch (e) {
        console.error(e);
        const d = e?.response?.data;
        const parts = [
          typeof d?.error === "string" ? d.error.trim() : "",
          typeof d?.detail === "string" ? d.detail.trim() : "",
        ].filter(Boolean);
        const msg =
          parts.join(" — ") ||
          e?.message ||
          "Clock action failed";
        setActionError(typeof msg === "string" ? msg : "Clock action failed");
      }
    };

    if (sharedDevice) {
      setBusy(true);
      navigator.geolocation?.getCurrentPosition(
        async (position) => {
          const { latitude, longitude } = position.coords;
          lastPosRef.current = { lat: latitude, lng: longitude };
          try {
            await run(latitude, longitude);
          } finally {
            setBusy(false);
          }
        },
        async () => {
          try {
            await run(null, null);
          } finally {
            setBusy(false);
          }
        },
        { enableHighAccuracy: true, timeout: 12000, maximumAge: 0 }
      );
      return;
    }

    setBusy(true);
    navigator.geolocation?.getCurrentPosition(
      async (position) => {
        const { latitude, longitude } = position.coords;
        lastPosRef.current = { lat: latitude, lng: longitude };
        try {
          await run(latitude, longitude);
        } finally {
          setBusy(false);
        }
      },
      () => {
        setBusy(false);
        setActionError(t("clock.locationRequired"));
      },
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 0 }
    );
  };

  const askBagsOnThisClockIn =
    asBool(clockUi.ask_personal_laundry_bags) && asBool(clockHints?.first_clock_in_est_today);

  const startClockInFlow = () => {
    setCheckInConfirmOpen(true);
  };

  /** After user confirms clock-in: optional laundry bags step, then API. */
  const proceedAfterClockInConfirm = () => {
    setCheckInConfirmOpen(false);
    if (tasks.length > 0) {
      setPendingTaskId(defaultCheckInTaskId);
      setTaskSelectOpen(true);
      return;
    }
    if (askBagsOnThisClockIn) {
      setPersonalBags(0);
      setBagsDialogOpen(true);
      return;
    }
    runWithPosition(async (lat, lng) => {
      await clockInWithTask(lat, lng, null, null);
      if (asBool(clockUi.shared_device_attendance) && !pinLockExcludedAdmin) {
        await lockSharedDeviceScreen();
        return;
      }
      navigate("/", { replace: true });
    });
  };

  const confirmTaskAndClockIn = () => {
    setTaskSelectOpen(false);
    if (askBagsOnThisClockIn) {
      setPersonalBags(0);
      setBagsDialogOpen(true);
      return;
    }
    runWithPosition(async (lat, lng) => {
      await clockInWithTask(lat, lng, pendingTaskId, null);
      if (asBool(clockUi.shared_device_attendance) && !pinLockExcludedAdmin) {
        await lockSharedDeviceScreen();
        return;
      }
      navigate("/", { replace: true });
    });
  };

  const confirmBagsAndClockIn = () => {
    setBagsDialogOpen(false);
    runWithPosition(async (lat, lng) => {
      await clockInWithTask(
        lat,
        lng,
        pendingTaskId,
        Math.max(0, Math.floor(Number(personalBags) || 0)),
      );
      if (asBool(clockUi.shared_device_attendance) && !pinLockExcludedAdmin) {
        await lockSharedDeviceScreen();
        return;
      }
      navigate("/", { replace: true });
    });
  };

  const submitClockOut = () => {
    setCheckoutConfirmOpen(false);
    runWithPosition(async (lat, lng) => {
      await taClockOut({ latitude: lat, longitude: lng });
      await refreshAfterAction();
      if (asBool(clockUi.shared_device_attendance) && !pinLockExcludedAdmin) {
        await lockSharedDeviceScreen();
        return;
      }
      if (asBool(clockUi.sign_out_after_clock_out)) {
        clearAuthSession();
        navigate("/login", { replace: true });
      } else {
        navigate("/", { replace: true });
      }
    });
  };

  if (loading) {
    return (
      <Stack alignItems="center" justifyContent="center" sx={{ minHeight: "65vh" }} spacing={1.2}>
        <CircularProgress size={28} />
        <Typography color="text.secondary">{t("clock.loading")}</Typography>
      </Stack>
    );
  }

  return (
    <Box
      sx={{
        p: { xs: 2, md: 3 },
        minHeight: "100%",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        pb: { xs: 8, md: 4 },
        ...(asBool(clockUi.dim_app_until_clocked_in) && !isClockedIn
          ? { filter: "brightness(0.92)", bgcolor: "rgba(15,23,42,0.03)" }
          : {}),
      }}
    >
      <Paper
        elevation={0}
        sx={{
          width: "100%",
          maxWidth: 440,
          p: { xs: 3, sm: 4 },
          borderRadius: 3,
          border: "1px solid",
          borderColor: "divider",
          textAlign: "center",
        }}
      >
        {actionError ? (
          <Alert severity="warning" sx={{ mb: 2, textAlign: "left" }} onClose={() => setActionError("")}>
            {actionError}
          </Alert>
        ) : null}
        {!isClockedIn ? (
          <Stack spacing={3} alignItems="center">
            {recentForceCheckout ? (
              <Alert severity="warning" sx={{ width: "100%", textAlign: "left" }}>
                Your shift ended automatically at{" "}
                {formatDeadline(recentForceCheckout.force_checked_out_at) || "scheduled time"}.
                {recentForceCheckout.continuation_allowed
                  ? " An admin has allowed you to continue — check in again when ready."
                  : " Contact a manager if you need to continue working."}
              </Alert>
            ) : null}
            <Typography
              sx={{
                fontSize: { xs: 28, sm: 34 },
                fontWeight: 800,
                color: "text.primary",
                letterSpacing: "-0.02em",
                lineHeight: 1.15,
              }}
            >
              {t("clock.notAtWork")}
            </Typography>
            <Button
              variant="contained"
              size="large"
              fullWidth
              disabled={busy}
              onClick={startClockInFlow}
              sx={{
                py: 2.5,
                fontSize: 22,
                fontWeight: 800,
                textTransform: "none",
                borderRadius: 2,
              }}
            >
              {busy ? <CircularProgress size={28} color="inherit" /> : t("clock.clockIn")}
            </Button>
          </Stack>
        ) : (
          <Stack spacing={2.5} alignItems="stretch" sx={{ width: "100%" }}>
            <Typography
              sx={{
                fontSize: { xs: 26, sm: 32 },
                fontWeight: 800,
                color: "primary.main",
                letterSpacing: "-0.02em",
                lineHeight: 1.2,
                textAlign: "center",
              }}
            >
              {atWorkLabel}
            </Typography>

            {checkInLabel ? (
              <Typography variant="body1" color="text.secondary" textAlign="center">
                Checked in at {checkInLabel}
              </Typography>
            ) : null}

            {scheduledEndLabel ? (
              <Alert
                severity={taskTracking?.force_checkout_blocked ? "error" : "info"}
                sx={{ textAlign: "left" }}
              >
                {taskTracking?.force_checkout_blocked
                  ? `Scheduled end (${scheduledEndLabel}) — shift should be closed.`
                  : `Scheduled end: ${scheduledEndLabel}`}
              </Alert>
            ) : null}

            <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, textAlign: "left" }}>
              <Typography variant="overline" color="text.secondary">
                Current task
              </Typography>
              <Typography variant="h6" fontWeight={800} sx={{ mb: 1.5 }}>
                {taskTracking?.current_task_name || "No task selected"}
              </Typography>
              <Grid container spacing={1}>
                {tasks.map((task) => {
                  const active = Number(taskTracking?.current_task_id) === Number(task.id);
                  return (
                    <Grid item xs={6} key={task.id}>
                      <Button
                        fullWidth
                        variant={active ? "contained" : "outlined"}
                        disabled={busy || switchTaskBusy || active}
                        onClick={() => handleSwitchTask(task.id)}
                        sx={{ textTransform: "none", fontWeight: 700, py: 1.5, fontSize: 15 }}
                      >
                        {task.name}
                      </Button>
                    </Grid>
                  );
                })}
              </Grid>
            </Paper>

            <Button
              variant="contained"
              color="error"
              size="large"
              fullWidth
              disabled={busy || switchTaskBusy}
              onClick={() => setCheckoutConfirmOpen(true)}
              sx={{
                py: 2.5,
                fontSize: 22,
                fontWeight: 800,
                textTransform: "none",
                borderRadius: 2,
              }}
            >
              {t("clock.clockOut")}
            </Button>
          </Stack>
        )}
      </Paper>

      <Dialog open={checkInConfirmOpen} onClose={() => !busy && setCheckInConfirmOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle sx={{ fontWeight: 800 }}>{t("clock.confirmClockInTitle")}</DialogTitle>
        <DialogContent>
          <Typography>{t("clock.confirmClockInBody")}</Typography>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={() => setCheckInConfirmOpen(false)} disabled={busy}>
            {t("clock.cancel")}
          </Button>
          <Button variant="contained" onClick={proceedAfterClockInConfirm} disabled={busy} size="large">
            {busy ? <CircularProgress size={22} color="inherit" /> : t("clock.confirm")}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={bagsDialogOpen} onClose={() => !busy && setBagsDialogOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle sx={{ fontWeight: 800 }}>{t("clock.personalLaundryTitle")}</DialogTitle>
        <DialogContent>
          <Stack spacing={0.75} sx={{ mb: 3 }}>
            <Typography variant="body1" color="text.secondary">
              {t("clock.personalLaundryHelpLead")}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 600 }}>
              {t("clock.personalLaundryHelpNote")}
            </Typography>
          </Stack>
          <Stack direction="row" alignItems="center" justifyContent="center" spacing={2}>
            <Button
              variant="outlined"
              size="large"
              disabled={busy || personalBags <= 0}
              onClick={() => setPersonalBags((n) => Math.max(0, n - 1))}
              sx={{ minWidth: 64, minHeight: 64, fontSize: 28, fontWeight: 700 }}
            >
              -
            </Button>
            <Typography sx={{ fontSize: 48, fontWeight: 800, minWidth: 80, textAlign: "center" }}>
              {personalBags}
            </Typography>
            <Button
              variant="outlined"
              size="large"
              disabled={busy || personalBags >= 99}
              onClick={() => setPersonalBags((n) => Math.min(99, n + 1))}
              sx={{ minWidth: 64, minHeight: 64, fontSize: 28, fontWeight: 700 }}
            >
              +
            </Button>
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={() => setBagsDialogOpen(false)} disabled={busy}>
            {t("clock.cancel")}
          </Button>
          <Button variant="contained" onClick={confirmBagsAndClockIn} disabled={busy} size="large">
            {busy ? <CircularProgress size={22} color="inherit" /> : t("clock.confirm")}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={taskSelectOpen} onClose={() => !busy && setTaskSelectOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle sx={{ fontWeight: 800 }}>Select starting task</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            Your last check-in task is preselected. Confirm or choose a different task.
          </Typography>
          <Stack spacing={1} sx={{ pt: 1 }}>
            {tasks.map((task) => (
              <Button
                key={task.id}
                variant={Number(pendingTaskId) === Number(task.id) ? "contained" : "outlined"}
                onClick={() => setPendingTaskId(task.id)}
                sx={{ justifyContent: "flex-start", textTransform: "none", fontWeight: 700, py: 1.5 }}
              >
                {task.name}
              </Button>
            ))}
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={() => setTaskSelectOpen(false)} disabled={busy}>
            {t("clock.cancel")}
          </Button>
          <Button variant="contained" onClick={confirmTaskAndClockIn} disabled={busy || !pendingTaskId} size="large">
            {busy ? <CircularProgress size={22} color="inherit" /> : t("clock.confirm")}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={checkoutConfirmOpen} onClose={() => !busy && setCheckoutConfirmOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle sx={{ fontWeight: 800 }}>{t("clock.confirmClockOutTitle")}</DialogTitle>
        <DialogContent>
          <Typography>{t("clock.confirmClockOutBody")}</Typography>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={() => setCheckoutConfirmOpen(false)} disabled={busy}>
            {t("clock.cancel")}
          </Button>
          <Button variant="contained" color="error" onClick={submitClockOut} disabled={busy} size="large">
            {busy ? <CircularProgress size={22} color="inherit" /> : t("clock.confirm")}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default ClockPage;
