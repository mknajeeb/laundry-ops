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
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { AccessTime, Coffee, Logout, PlayArrow } from "@mui/icons-material";
import {
  getClockPayrollUiSettings,
  getTaSessionCurrent,
  taBreakEnd,
  taBreakStart,
  taClockIn,
  taClockOut,
  clearAuthSession,
} from "../api";
import { useAuth } from "../context/AuthContext";
import { asBool } from "../utils/bool";

function formatDuration(totalSeconds) {
  const s = Math.max(0, Math.floor(Number(totalSeconds) || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h} hr ${m} min`;
}

const DEFAULT_CLOCK_UI = {
  outside_geofence_label_enabled: true,
  outside_geofence_label_text: "You are outside the designated work area.",
  clock_banner_enabled: false,
  clock_banner_text: "",
  show_outside_geofence_on_clock: true,
  show_outside_geofence_on_summary: true,
  ask_personal_laundry_bags: false,
  dim_app_until_clocked_in: false,
  sign_out_after_clock_out: false,
};

const BANNER_FALLBACK_TEXT = "Company notice — check with your supervisor for updates.";

/** Same haversine as backend.ta_helpers (meters). */
function haversineMeters(lat1, lon1, lat2, lon2) {
  const R = 6371000;
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(a)));
}

function apiErrorMessage(error, fallback) {
  const d = error?.response?.data;
  if (d?.detail && String(d.detail).trim()) return String(d.detail).trim();
  if (d?.error && String(d.error).trim()) return String(d.error).trim();
  return fallback;
}

function normalizeClockUi(raw) {
  const d = { ...DEFAULT_CLOCK_UI, ...(raw && typeof raw === "object" ? raw : {}) };
  return {
    ...d,
    outside_geofence_label_enabled: asBool(
      d.outside_geofence_label_enabled,
      DEFAULT_CLOCK_UI.outside_geofence_label_enabled
    ),
    clock_banner_enabled: asBool(d.clock_banner_enabled, false),
    show_outside_geofence_on_clock: asBool(d.show_outside_geofence_on_clock, true),
    show_outside_geofence_on_summary: asBool(d.show_outside_geofence_on_summary, true),
    ask_personal_laundry_bags: asBool(d.ask_personal_laundry_bags, false),
    dim_app_until_clocked_in: asBool(d.dim_app_until_clocked_in, false),
    sign_out_after_clock_out: asBool(d.sign_out_after_clock_out, false),
  };
}

function ClockPage({ user: washproUser }) {
  const navigate = useNavigate();
  const { user: taUser, loading: authLoading } = useAuth();
  const [tick, setTick] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [sessionRes, setSessionRes] = useState(null);
  const [clockUi, setClockUi] = useState(DEFAULT_CLOCK_UI);
  const [message, setMessage] = useState({ type: "info", text: "" });
  const [checkoutOpen, setCheckoutOpen] = useState(false);
  const [checkoutStep, setCheckoutStep] = useState("bags");
  const [laundryBags, setLaundryBags] = useState("");
  const [doneSummary, setDoneSummary] = useState(null);
  const [geoTick, setGeoTick] = useState(0);

  const lastPosRef = useRef({ lat: null, lng: null });
  const sessionLoadAbortRef = useRef(null);

  const session = sessionRes?.session;
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
      const err = apiErrorMessage(error, "Failed to load clock state.");
      if (!silent) setMessage({ type: "error", text: err });
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  const refreshAll = useCallback(
    async (silent) => {
      await new Promise((resolve) => {
        navigator.geolocation.getCurrentPosition(
          async (pos) => {
            const { latitude: la, longitude: ln } = pos.coords;
            lastPosRef.current = { lat: la, lng: ln };
            setGeoTick((x) => x + 1);
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

  /** After clock/break actions we already have coords in lastPosRef — skip another GPS round-trip. */
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
  }, [authLoading, loadClockUi]);

  useEffect(
    () => () => {
      sessionLoadAbortRef.current?.abort();
    },
    []
  );

  useEffect(() => {
    if (authLoading) return;
    refreshAll(false);
  }, [authLoading, refreshAll]);

  useEffect(() => {
    if (authLoading || !isClockedIn) return undefined;

    let watchId = null;
    let fallbackId = null;
    const throttleMs = 1200;
    let lastAt = 0;

    const apply = (la, ln) => {
      lastPosRef.current = { lat: la, lng: ln };
      setGeoTick((x) => x + 1);
      void loadSession(true, la, ln);
    };

    const onWatch = (pos) => {
      const now = Date.now();
      if (now - lastAt < throttleMs) return;
      lastAt = now;
      const { latitude: la, longitude: ln } = pos.coords;
      apply(la, ln);
    };

    const geo = typeof navigator !== "undefined" ? navigator.geolocation : null;

    // Fresh fix immediately (mobile watchPosition first callback is often delayed).
    geo?.getCurrentPosition?.(onWatch, () => {}, {
      enableHighAccuracy: true,
      maximumAge: 0,
      timeout: 15000,
    });

    if (geo?.watchPosition) {
      watchId = geo.watchPosition(onWatch, () => {}, {
        enableHighAccuracy: true,
        maximumAge: 0,
        timeout: 20000,
      });
    }

    fallbackId = setInterval(
      () => {
        refreshAll(true);
      },
      geo?.watchPosition ? 18000 : 8000
    );

    return () => {
      if (watchId != null && geo?.clearWatch) geo.clearWatch(watchId);
      if (fallbackId != null) clearInterval(fallbackId);
    };
  }, [authLoading, isClockedIn, loadSession, refreshAll]);

  useEffect(() => {
    const id = setInterval(() => setTick((x) => x + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const operational = sessionRes?.operational;

  const runWithPosition = (fn) => {
    setBusy(true);
    navigator.geolocation.getCurrentPosition(
      async (position) => {
        const { latitude, longitude } = position.coords;
        lastPosRef.current = { lat: latitude, lng: longitude };
        setGeoTick((x) => x + 1);
        try {
          await fn(latitude, longitude);
        } catch (error) {
          console.error(error);
          setMessage({ type: "error", text: apiErrorMessage(error, "Action failed.") });
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
        setDoneSummary(null);
        setMessage({ type: "success", text: "Clock in recorded." });
        await refreshAfterAction();
      });
      return;
    }
    if (action === "BREAK_START") {
      setBusy(true);
      try {
        await taBreakStart();
        setMessage({ type: "success", text: "Break started." });
        await refreshAfterAction();
      } catch (error) {
        setMessage({ type: "error", text: apiErrorMessage(error, "Action failed.") });
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
        await refreshAfterAction();
      } catch (error) {
        setMessage({ type: "error", text: apiErrorMessage(error, "Action failed.") });
      } finally {
        setBusy(false);
      }
    }
  };

  const askPersonalBags = asBool(clockUi.ask_personal_laundry_bags);

  const beginCheckout = () => {
    setDoneSummary(null);
    if (askPersonalBags) {
      setCheckoutStep("bags");
      setLaundryBags("");
    } else {
      setCheckoutStep("summary");
    }
    setCheckoutOpen(true);
  };

  const submitClockOut = () => {
    runWithPosition(async (lat, lng) => {
      const body = { latitude: lat, longitude: lng };
      if (askPersonalBags) {
        const n = Number.parseInt(String(laundryBags).trim(), 10);
        body.personal_laundry_bags = Number.isFinite(n) && n >= 0 ? Math.floor(n) : 0;
      }
      const res = await taClockOut(body);
      setCheckoutOpen(false);
      setMessage({ type: "success", text: "Clock out recorded." });
      setDoneSummary(res.data?.summary || null);
      await refreshAfterAction();
      if (asBool(clockUi.sign_out_after_clock_out)) {
        clearAuthSession();
        navigate("/login", { replace: true });
      }
    });
  };

  const onBreak = !!session?.open_break;

  /** Server uses Eastern-naive instants; avoid client Date.parse(clock_in_at) drift vs elapsed_* fields. */
  const shiftAnchorRef = useRef(null);
  const liveShiftSec = useMemo(() => {
    if (!session?.clock_in_at) return 0;
    const el = session.elapsed_shift_seconds;
    if (el != null) {
      const k = `${session.id}-${el}`;
      if (!shiftAnchorRef.current || shiftAnchorRef.current.k !== k) {
        shiftAnchorRef.current = {
          k,
          sec: Math.max(0, Math.floor(Number(el) || 0)),
          atMs: Date.now(),
        };
      }
      const a = shiftAnchorRef.current;
      return Math.max(0, a.sec + Math.floor((Date.now() - a.atMs) / 1000));
    }
    const t0 = Date.parse(session.clock_in_at);
    if (Number.isNaN(t0)) return 0;
    return Math.max(0, Math.floor((Date.now() - t0) / 1000));
  }, [session?.id, session?.elapsed_shift_seconds, session?.clock_in_at, tick]);

  const shiftLabel = formatDuration(liveShiftSec);
  const workLabel =
    session?.elapsed_work_seconds != null
      ? formatDuration(session.elapsed_work_seconds)
      : "0 hr 0 min";
  const breakLabel =
    session?.elapsed_break_seconds != null
      ? formatDuration(session.elapsed_break_seconds)
      : "0 hr 0 min";
  const outsideSec = Number(session?.outside_geofence_seconds) || 0;
  const outsideLabel = formatDuration(outsideSec);

  const displayGeofenceInside = useMemo(() => {
    if (session?.clock_geofence_exempt) return true;
    const srv = session?.geofence_inside;
    if (srv === true || srv === false) return srv;
    const { lat, lng } = lastPosRef.current;
    if (lat == null || lng == null) return null;
    const list = session?.assigned_geofences;
    const geos = Array.isArray(list) && list.length > 0 ? list : session?.primary_geofence ? [session.primary_geofence] : [];
    if (geos.length === 0) return null;
    for (const gf of geos) {
      const dist = haversineMeters(lat, lng, Number(gf.latitude), Number(gf.longitude));
      if (dist <= Number(gf.radius_meters)) return true;
    }
    return false;
  }, [session, geoTick]);

  const showOutsideOnClock =
    asBool(clockUi.show_outside_geofence_on_clock) && isClockedIn;
  const outsideWarning =
    asBool(clockUi.outside_geofence_label_enabled) &&
    isClockedIn &&
    displayGeofenceInside === false;

  if (loading) {
    return (
      <Stack alignItems="center" justifyContent="center" sx={{ minHeight: "65vh" }} spacing={1.2}>
        <CircularProgress size={28} />
        <Typography color="text.secondary">Loading...</Typography>
      </Stack>
    );
  }

  return (
    <Box
      sx={{
        p: { xs: 1.2, md: 2 },
        minHeight: "100%",
        position: "relative",
        pb: { xs: 10, md: 3 },
        ...(asBool(clockUi.dim_app_until_clocked_in) && !isClockedIn
          ? { filter: "brightness(0.92)", bgcolor: "rgba(15,23,42,0.03)" }
          : {}),
      }}
    >
      {message.text && (
        <Alert
          severity={message.type}
          sx={{ mb: 1.2 }}
          onClose={() => setMessage({ type: "info", text: "" })}
        >
          {message.text}
        </Alert>
      )}

      {asBool(clockUi.clock_banner_enabled) ? (
        <Alert severity="info" sx={{ mb: 1.2 }}>
          {(clockUi.clock_banner_text || "").trim() || BANNER_FALLBACK_TEXT}
        </Alert>
      ) : null}

      {outsideWarning ? (
        <Alert severity="error" sx={{ mb: 1.2 }}>
          {(clockUi.outside_geofence_label_text || "").trim() ||
            DEFAULT_CLOCK_UI.outside_geofence_label_text}
        </Alert>
      ) : null}

      <Paper
        sx={{
          p: { xs: 1.6, md: 2 },
          borderRadius: 2,
          border: "1px solid #dbe3ef",
          boxShadow: "none",
        }}
      >
        {!isClockedIn ? (
          <Stack alignItems="center" justifyContent="center" spacing={3} sx={{ py: 4 }}>
            <Typography sx={{ fontSize: { xs: 22, md: 26 }, color: "#0f172a", fontWeight: 600 }}>
              Hi {foldedByName}
            </Typography>
            <Button
              size="large"
              variant="contained"
              startIcon={<PlayArrow />}
              disabled={busy}
              onClick={() => runAction("CLOCK_IN")}
              sx={{
                minWidth: 300,
                py: 2,
                px: 4,
                fontSize: 20,
                textTransform: "none",
                borderRadius: 3,
                fontWeight: 700,
              }}
            >
              Clock in
            </Button>
          </Stack>
        ) : (
          <Stack spacing={2.5}>
            <Stack
              direction={{ xs: "column", sm: "row" }}
              spacing={2}
              justifyContent="space-between"
              alignItems={{ xs: "stretch", sm: "flex-start" }}
            >
              <Paper
                variant="outlined"
                sx={{
                  p: 1.5,
                  flex: 1,
                  borderRadius: 2,
                  borderColor: "#e2e8f0",
                  boxShadow: "none",
                }}
              >
                <Typography sx={{ color: "#64748b", fontSize: 12, fontWeight: 600, mb: 0.5 }}>
                  Shift time (total)
                </Typography>
                <Typography sx={{ fontSize: 28, fontWeight: 700, color: "#0f172a", lineHeight: 1.2 }}>
                  {shiftLabel}
                </Typography>
                <Typography sx={{ color: "#64748b", fontSize: 11, fontWeight: 600, mt: 1.2, mb: 0.5 }}>
                  Net work (excl. breaks)
                </Typography>
                <Typography sx={{ fontSize: 20, fontWeight: 700, color: "#334155", lineHeight: 1.2 }}>
                  {workLabel}
                </Typography>
              </Paper>
              <Stack spacing={1} sx={{ flex: 1, alignItems: { xs: "stretch", sm: "flex-end" } }}>
                <Paper
                  variant="outlined"
                  sx={{
                    p: 1.5,
                    width: "100%",
                    maxWidth: 320,
                    borderRadius: 2,
                    borderColor: "#e2e8f0",
                    boxShadow: "none",
                  }}
                >
                  <Typography sx={{ color: "#64748b", fontSize: 12, fontWeight: 600, mb: 0.5 }}>
                    Total break time
                  </Typography>
                  <Typography sx={{ fontSize: 22, fontWeight: 700, color: "#0f172a" }}>
                    {breakLabel}
                  </Typography>
                </Paper>
                {showOutsideOnClock ? (
                  <Paper
                    variant="outlined"
                    sx={{
                      p: 1.5,
                      width: "100%",
                      maxWidth: 320,
                      borderRadius: 2,
                      borderColor: outsideSec > 0 ? "#fecaca" : "#e2e8f0",
                      bgcolor: outsideSec > 0 ? "#fff1f2" : "transparent",
                      boxShadow: "none",
                    }}
                  >
                    <Typography sx={{ color: "#64748b", fontSize: 12, fontWeight: 600, mb: 0.5 }}>
                      Outside geofence
                    </Typography>
                    <Typography
                      sx={{
                        fontSize: 20,
                        fontWeight: 700,
                        color: outsideSec > 0 ? "#b91c1c" : "#0f172a",
                      }}
                    >
                      {outsideLabel}
                    </Typography>
                  </Paper>
                ) : null}
              </Stack>
            </Stack>

            <Stack
              direction={{ xs: "column", sm: "row" }}
              spacing={1.5}
              justifyContent="center"
              alignItems="stretch"
              sx={{ pt: 1 }}
            >
              {!onBreak ? (
                <>
                  <Button
                    variant="contained"
                    color="warning"
                    size="large"
                    startIcon={<Coffee />}
                    disabled={busy}
                    onClick={() => runAction("BREAK_START")}
                    sx={{
                      flex: 1,
                      maxWidth: 360,
                      py: 2,
                      textTransform: "none",
                      fontSize: 18,
                      fontWeight: 700,
                      borderRadius: 3,
                    }}
                  >
                    Start break
                  </Button>
                  <Button
                    variant="outlined"
                    color="error"
                    size="large"
                    startIcon={<Logout />}
                    disabled={busy}
                    onClick={beginCheckout}
                    sx={{
                      flex: 1,
                      maxWidth: 360,
                      py: 2,
                      textTransform: "none",
                      fontSize: 18,
                      fontWeight: 700,
                      borderRadius: 3,
                    }}
                  >
                    Clock out
                  </Button>
                </>
              ) : null}
            </Stack>
          </Stack>
        )}
      </Paper>

      {doneSummary && !isClockedIn ? (
        <Paper sx={{ mt: 2, p: 2, borderRadius: 2, border: "1px solid #bbf7d0", bgcolor: "#f0fdf4" }}>
          <Typography fontWeight={700} sx={{ mb: 1 }}>
            Session complete
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Working time (net): {formatDuration(doneSummary.net_work_seconds || 0)}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Breaks: {formatDuration(doneSummary.total_break_seconds || 0)}
          </Typography>
          {asBool(clockUi.show_outside_geofence_on_summary) ? (
            <Typography variant="body2" color="text.secondary">
              Outside geofence: {formatDuration(doneSummary.outside_geofence_seconds || 0)}
            </Typography>
          ) : null}
          {askPersonalBags &&
          doneSummary.personal_laundry_bags != null &&
          doneSummary.personal_laundry_bags !== undefined ? (
            <Typography variant="body2" color="text.secondary">
              Personal laundry bags: {doneSummary.personal_laundry_bags}
            </Typography>
          ) : null}
        </Paper>
      ) : null}

      <Dialog open={checkoutOpen} onClose={() => !busy && setCheckoutOpen(false)} fullWidth maxWidth="xs">
        {checkoutStep === "bags" ? (
          <>
            <DialogTitle>Personal laundry bags</DialogTitle>
            <DialogContent>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                How many personal laundry bags did you process this shift? (optional)
              </Typography>
              <TextField
                fullWidth
                type="number"
                inputProps={{ min: 0 }}
                label="Count"
                value={laundryBags}
                onChange={(e) => setLaundryBags(e.target.value)}
              />
            </DialogContent>
            <DialogActions>
              <Button onClick={() => setCheckoutOpen(false)}>Cancel</Button>
              <Button variant="contained" onClick={() => setCheckoutStep("summary")}>
                Continue
              </Button>
            </DialogActions>
          </>
        ) : (
          <>
            <DialogTitle>Confirm clock out</DialogTitle>
            <DialogContent>
              <Stack spacing={1}>
                <Typography variant="body2">
                  <strong>Working hours:</strong> {workLabel}
                </Typography>
                <Typography variant="body2">
                  <strong>Total break:</strong> {breakLabel}
                </Typography>
                {asBool(clockUi.show_outside_geofence_on_summary) ? (
                  <Typography variant="body2">
                    <strong>Time outside geofence:</strong> {outsideLabel}
                  </Typography>
                ) : null}
              </Stack>
            </DialogContent>
            <DialogActions>
              <Button onClick={() => setCheckoutOpen(false)} disabled={busy}>
                Cancel
              </Button>
              <Button variant="contained" onClick={submitClockOut} disabled={busy}>
                {busy ? "…" : "Confirm clock out"}
              </Button>
            </DialogActions>
          </>
        )}
      </Dialog>

      {onBreak && (
        <Box
          sx={{
            position: "fixed",
            inset: 0,
            background: "rgba(15, 23, 42, 0.72)",
            zIndex: 1400,
            display: "grid",
            placeItems: "center",
            p: 2,
          }}
        >
          <Paper sx={{ p: 3, width: "min(440px, 92vw)", borderRadius: 2, textAlign: "center" }}>
            <Typography sx={{ fontWeight: 700, fontSize: 18, mb: 1 }}>On break</Typography>
            <Typography sx={{ mb: 2, color: "text.secondary" }}>
              Work timer is paused. Come back when you are ready.
            </Typography>
            <Button
              variant="contained"
              color="success"
              size="large"
              startIcon={<AccessTime />}
              onClick={() => runAction("BREAK_END")}
              disabled={busy}
              sx={{ minWidth: 220, textTransform: "none", py: 1.5, fontWeight: 700 }}
            >
              End break
            </Button>
          </Paper>
        </Box>
      )}
    </Box>
  );
}

export default ClockPage;
