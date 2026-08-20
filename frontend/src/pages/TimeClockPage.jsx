import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Dialog,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Typography,
  Stack,
} from "@mui/material";
import {
  getEmploymentCategories,
  getTaSessionCurrent,
  taBreakEnd,
  taBreakStart,
  taClockIn,
  taClockOut,
} from "../api";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";
import OpsRoleFirstSelector from "../opsMobile/OpsRoleFirstSelector";
import OpsTopBar from "../opsMobile/OpsTopBar";
import { OPS_MOBILE } from "../opsMobile/tokens";

function formatDuration(sec) {
  if (sec == null || sec < 0) return "—";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  return `${h}h ${m}m ${s}s`;
}

function TimeClockPage() {
  const { hasPerm } = useAuth();
  const { t } = useI18n();
  const [session, setSession] = useState(null);
  const [operational, setOperational] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(0);
  const [categories, setCategories] = useState([]);
  const [categoryId, setCategoryId] = useState("");
  const [resumeOpen, setResumeOpen] = useState(false);
  const [resumeTree, setResumeTree] = useState([]);
  const [resumeCategoryId, setResumeCategoryId] = useState(null);

  const canClock = hasPerm("ta.clock");

  const refresh = useCallback(async () => {
    if (!canClock) return;
    setError("");
    try {
      let pos = null;
      try {
        pos = await new Promise((resolve) => {
          if (!navigator.geolocation) {
            resolve(null);
            return;
          }
          navigator.geolocation.getCurrentPosition(resolve, () => resolve(null), {
            enableHighAccuracy: true,
            timeout: 8000,
          });
        });
      } catch {
        pos = null;
      }
      const params = {};
      if (pos?.coords) {
        params.latitude = pos.coords.latitude;
        params.longitude = pos.coords.longitude;
      }
      const res = await getTaSessionCurrent(params);
      setSession(res.data.session);
      setOperational(res.data.operational);
    } catch (e) {
      setError(e.response?.data?.error || "Could not load session");
    }
  }, [canClock]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    getEmploymentCategories()
      .then((r) => setCategories(r.data || []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const active = session && session.status === "active";
  const openBreak = session?.open_break;

  let shiftElapsed = 0;
  if (active && session.clock_in_at) {
    const start = new Date(session.clock_in_at).getTime();
    shiftElapsed = Math.floor((Date.now() - start) / 1000);
  }

  let breakElapsed = 0;
  if (openBreak?.break_start_at) {
    const bs = new Date(openBreak.break_start_at).getTime();
    breakElapsed = Math.floor((Date.now() - bs) / 1000);
  }

  async function doClockIn() {
    setBusy(true);
    setError("");
    try {
      const pos = await new Promise((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(resolve, reject, {
          enableHighAccuracy: true,
          timeout: 12000,
        });
      });
      const body = {
        latitude: pos.coords.latitude,
        longitude: pos.coords.longitude,
      };
      if (categoryId) body.employment_category_id = Number(categoryId);
      await taClockIn(body);
      await refresh();
    } catch (e) {
      const msg =
        e.response?.data?.error ||
        e.message ||
        "Clock-in failed (location permission or geofence).";
      setError(msg);
    } finally {
      setBusy(false);
    }
  }

  async function doClockOut() {
    setBusy(true);
    setError("");
    try {
      let body = {};
      try {
        const pos = await new Promise((resolve, reject) => {
          navigator.geolocation.getCurrentPosition(resolve, reject, {
            enableHighAccuracy: true,
            timeout: 12000,
          });
        });
        body = { latitude: pos.coords.latitude, longitude: pos.coords.longitude };
      } catch {
        body = {};
      }
      await taClockOut(body);
      await refresh();
    } catch (e) {
      setError(e.response?.data?.error || "Clock-out failed");
    } finally {
      setBusy(false);
    }
  }

  async function startBreak() {
    setBusy(true);
    try {
      await taBreakStart();
      await refresh();
    } catch (e) {
      setError(e.response?.data?.error || "Could not start break");
    } finally {
      setBusy(false);
    }
  }

  async function endBreak(assignment) {
    setBusy(true);
    setError("");
    try {
      const body = {};
      if (assignment?.category_id != null) body.category_id = assignment.category_id;
      if (assignment?.role_id != null) body.role_id = assignment.role_id;
      await taBreakEnd(body);
      setResumeOpen(false);
      setResumeTree([]);
      await refresh();
    } catch (e) {
      const data = e?.response?.data;
      if (data?.needs_category_role && Array.isArray(data.selection_tree)) {
        setResumeTree(data.selection_tree);
        setResumeCategoryId(data.selection_tree[0]?.id ?? null);
        setResumeOpen(true);
      } else {
        setError(data?.error || e?.message || "Could not end break");
      }
    } finally {
      setBusy(false);
    }
  }

  if (!canClock) {
    return (
      <div className="page">
        <Alert severity="info">Your role does not include time clock access.</Alert>
      </div>
    );
  }

  return (
    <div className="page">
      <Typography variant="h4" className="page-title" sx={{ mb: 2 }}>
        Time clock
      </Typography>

      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
        <Card sx={{ flex: 1 }}>
          <CardContent>
            <Typography variant="subtitle2" color="text.secondary">
              Status
            </Typography>
            <Stack direction="row" spacing={1} sx={{ mt: 1, flexWrap: "wrap" }}>
              <Chip
                label={active ? "Clocked in" : "Not clocked in"}
                color={active ? "success" : "default"}
              />
              {openBreak ? <Chip label="On break" color="warning" /> : null}
              {operational?.allowed === false ? (
                <Chip label="Operational hold" color="error" variant="outlined" />
              ) : null}
            </Stack>
            {operational?.reasons?.length ? (
              <Typography variant="caption" display="block" sx={{ mt: 1 }}>
                {operational.reasons.join(", ")}
              </Typography>
            ) : null}
            {session?.primary_geofence ? (
              <Typography variant="body2" sx={{ mt: 2 }}>
                Geofence: {session.primary_geofence.name} —{" "}
                {session.geofence_inside === true
                  ? "inside"
                  : session.geofence_inside === false
                    ? "outside"
                    : "location not sent"}
              </Typography>
            ) : null}
          </CardContent>
        </Card>

        <Card sx={{ flex: 1 }}>
          <CardContent>
            <Typography variant="subtitle2" color="text.secondary">
              Timers
            </Typography>
            <Typography variant="h6" sx={{ mt: 1 }}>
              Shift: {formatDuration(shiftElapsed)}
            </Typography>
            <Typography variant="h6">Break: {formatDuration(breakElapsed)}</Typography>
            <Typography variant="caption" color="text.secondary">
              tick {tick}
            </Typography>
          </CardContent>
        </Card>
      </Stack>

      <Card sx={{ mt: 2 }}>
        <CardContent>
          <Stack spacing={2} direction={{ xs: "column", sm: "row" }} flexWrap="wrap" useFlexGap>
            {!active ? (
              <>
                <FormControl sx={{ minWidth: 220 }}>
                  <InputLabel id="cat-label">Employment category (optional)</InputLabel>
                  <Select
                    labelId="cat-label"
                    label="Employment category (optional)"
                    value={categoryId}
                    onChange={(e) => setCategoryId(e.target.value)}
                  >
                    <MenuItem value="">
                      <em>Default from profile</em>
                    </MenuItem>
                    {categories.map((c) => (
                      <MenuItem key={c.id} value={c.id}>
                        {c.name}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <Button variant="contained" size="large" disabled={busy} onClick={doClockIn}>
                  Clock in
                </Button>
              </>
            ) : (
              <>
                {!openBreak ? (
                  <Button variant="outlined" disabled={busy} onClick={startBreak}>
                    Start break
                  </Button>
                ) : (
                  <Button variant="contained" color="warning" disabled={busy} onClick={() => endBreak()}>
                    End break
                  </Button>
                )}
                <Button variant="contained" color="secondary" disabled={busy} onClick={doClockOut}>
                  Clock out
                </Button>
              </>
            )}
          </Stack>
          <Typography variant="caption" display="block" sx={{ mt: 2 }}>
            Browser location is required for clock-in/out geofence checks. Allow location when
            prompted.
          </Typography>
        </CardContent>
      </Card>

      <Dialog
        open={resumeOpen}
        onClose={() => !busy && setResumeOpen(false)}
        fullScreen
        PaperProps={{
          sx: {
            bgcolor: OPS_MOBILE.mist,
            background: `linear-gradient(165deg, ${OPS_MOBILE.mist} 0%, #e8eeff 45%, rgba(72,101,238,0.12) 100%)`,
          },
        }}
      >
        <Box sx={{ px: { xs: 1.5, sm: 2.5, md: 3 }, py: { xs: 1.5, sm: 2 }, maxWidth: 880, mx: "auto", width: "100%" }}>
          <OpsTopBar
            title={t("mobileOps.selectRoleResume")}
            onBack={busy ? undefined : () => setResumeOpen(false)}
            backLabel={t("mobileOps.back")}
            sticky
          />
          <OpsRoleFirstSelector
            selectionTree={resumeTree}
            markCurrent={false}
            pending={busy}
            onSelectCombo={(combo) => {
              if (!combo) return;
              void endBreak({ category_id: combo.categoryId, role_id: combo.roleId });
            }}
            emptyMessage={t("mobileOps.roleUnavailable")}
            singleWorkTypeHint={t("mobileOps.tapToResume")}
            multiWorkTypeHint={t("mobileOps.tapToChooseWork")}
          />
        </Box>
      </Dialog>
    </div>
  );
}

export default TimeClockPage;
