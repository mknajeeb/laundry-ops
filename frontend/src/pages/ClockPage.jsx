import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import {
  getClockPayrollUiSettings,
  getTaSessionCurrent,
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
};

function normalizeClockUi(raw) {
  const d = { ...DEFAULT_CLOCK_UI, ...(raw && typeof raw === "object" ? raw : {}) };
  return {
    ...d,
    ask_personal_laundry_bags: asBool(d.ask_personal_laundry_bags, false),
    dim_app_until_clocked_in: asBool(d.dim_app_until_clocked_in, false),
    sign_out_after_clock_out: asBool(d.sign_out_after_clock_out, false),
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

  const lastPosRef = useRef({ lat: null, lng: null });

  const session = sessionRes?.session;
  const clockHints = sessionRes?.clock_hints;
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
  }, [authLoading, loadClockUi]);

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
    }, 90000);
    return () => clearInterval(id);
  }, [authLoading, isClockedIn, refreshAll]);

  const runWithPosition = (fn) => {
    setBusy(true);
    navigator.geolocation?.getCurrentPosition(
      async (position) => {
        const { latitude, longitude } = position.coords;
        lastPosRef.current = { lat: latitude, lng: longitude };
        try {
          await fn(latitude, longitude);
        } catch (error) {
          console.error(error);
        } finally {
          setBusy(false);
        }
      },
      () => {
        setBusy(false);
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
    if (askBagsOnThisClockIn) {
      setPersonalBags(0);
      setBagsDialogOpen(true);
      return;
    }
    runWithPosition(async (lat, lng) => {
      await taClockIn({ latitude: lat, longitude: lng });
      await refreshAfterAction();
    });
  };

  const confirmBagsAndClockIn = () => {
    setBagsDialogOpen(false);
    runWithPosition(async (lat, lng) => {
      await taClockIn({
        latitude: lat,
        longitude: lng,
        personal_laundry_bags: Math.max(0, Math.floor(Number(personalBags) || 0)),
      });
      await refreshAfterAction();
    });
  };

  const submitClockOut = () => {
    setCheckoutConfirmOpen(false);
    runWithPosition(async (lat, lng) => {
      await taClockOut({ latitude: lat, longitude: lng });
      await refreshAfterAction();
      if (asBool(clockUi.sign_out_after_clock_out)) {
        clearAuthSession();
        navigate("/login", { replace: true });
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
        {!isClockedIn ? (
          <Stack spacing={3} alignItems="center">
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
          <Stack spacing={3} alignItems="center">
            <Typography
              sx={{
                fontSize: { xs: 26, sm: 32 },
                fontWeight: 800,
                color: "primary.main",
                letterSpacing: "-0.02em",
                lineHeight: 1.2,
              }}
            >
              {atWorkLabel}
            </Typography>
            <Button
              variant="contained"
              color="error"
              size="large"
              fullWidth
              disabled={busy}
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
          <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
            {t("clock.personalLaundryHelp")}
          </Typography>
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
