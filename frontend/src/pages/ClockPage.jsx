import { useCallback, useEffect, useMemo, useState } from "react";
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
  getTaskTrackingSelectionTree,
  getTaSessionCurrent,
  postTaskTrackingSwitchTask,
  taBreakEnd,
} from "../api";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";

function formatTimeLabel(iso) {
  if (!iso) return null;
  const d = new Date(String(iso).replace(" ", "T"));
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

/**
 * Personal app: attendance is shared-register only.
 * When Category & Role Tracking is enabled and a shift is active, show/change assignment.
 */
function ClockPage({ user: washproUser }) {
  const { t } = useI18n();
  const { user: taUser, loading: authLoading } = useAuth();
  const [loading, setLoading] = useState(true);
  const [sessionRes, setSessionRes] = useState(null);
  const [actionError, setActionError] = useState("");

  const [selectionTree, setSelectionTree] = useState([]);
  const [pickOpen, setPickOpen] = useState(false);
  const [pickStep, setPickStep] = useState("category");
  const [pendingCategoryId, setPendingCategoryId] = useState(null);
  const [pendingRoleId, setPendingRoleId] = useState(null);
  const [switchBusy, setSwitchBusy] = useState(false);

  const session = sessionRes?.session;
  const trackingEnabled = !!(
    sessionRes?.category_role_tracking_enabled ??
    session?.category_role_tracking_enabled
  );
  const taskTracking = session?.task_tracking || session?.job_tracking;
  const isClockedIn = !!session;
  const needsAssignment =
    trackingEnabled && isClockedIn && !!taskTracking?.needs_current_assignment;

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

  const selectedCategory = useMemo(
    () => selectionTree.find((c) => Number(c.id) === Number(pendingCategoryId)) || null,
    [selectionTree, pendingCategoryId]
  );
  const rolesForCategory = selectedCategory?.roles || [];

  const loadSelectionTree = useCallback(async () => {
    try {
      const res = await getTaskTrackingSelectionTree();
      setSelectionTree(Array.isArray(res.data) ? res.data : []);
    } catch {
      setSelectionTree([]);
    }
  }, []);

  const loadSession = useCallback(async (silent) => {
    try {
      if (!silent) setLoading(true);
      const res = await getTaSessionCurrent();
      setSessionRes(res.data || null);
    } catch (error) {
      console.error(error);
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (authLoading) return;
    loadSession(false);
  }, [authLoading, loadSession]);

  useEffect(() => {
    if (authLoading || !trackingEnabled) return;
    loadSelectionTree();
  }, [authLoading, trackingEnabled, loadSelectionTree]);

  useEffect(() => {
    if (!session?.open_break) return undefined;
    let cancelled = false;
    (async () => {
      try {
        await taBreakEnd();
        if (!cancelled) await loadSession(true);
      } catch (e) {
        console.error(e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [session?.id, session?.open_break, loadSession]);

  useEffect(() => {
    if (authLoading || !isClockedIn) return undefined;
    const id = setInterval(() => loadSession(true), 30000);
    return () => clearInterval(id);
  }, [authLoading, isClockedIn, loadSession]);

  const openPicker = () => {
    setPickStep("category");
    const curCat = taskTracking?.current_category_id;
    const hasCur =
      curCat != null && selectionTree.some((c) => Number(c.id) === Number(curCat));
    setPendingCategoryId(hasCur ? Number(curCat) : selectionTree[0]?.id ?? null);
    setPendingRoleId(hasCur ? Number(taskTracking?.current_role_id) : null);
    setPickOpen(true);
  };

  const confirmRoleChange = async () => {
    if (!pendingCategoryId || !pendingRoleId) return;
    setSwitchBusy(true);
    setActionError("");
    try {
      await postTaskTrackingSwitchTask({
        category_id: pendingCategoryId,
        role_id: pendingRoleId,
      });
      setPickOpen(false);
      await loadSession(true);
    } catch (e) {
      setActionError(e?.response?.data?.error || e?.message || "Could not change role");
    } finally {
      setSwitchBusy(false);
    }
  };

  const assignmentStartedLabel = formatTimeLabel(taskTracking?.current_assignment_started_at);
  const currentLabel =
    taskTracking?.current_display_label ||
    (taskTracking?.current_category_name && taskTracking?.current_role_name
      ? `${taskTracking.current_category_name} — ${taskTracking.current_role_name}`
      : null);

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
          <Stack spacing={2} alignItems="center">
            <Typography
              sx={{
                fontSize: { xs: 28, sm: 34 },
                fontWeight: 800,
                letterSpacing: "-0.02em",
                lineHeight: 1.15,
              }}
            >
              {t("clock.notAtWork")}
            </Typography>
            <Typography color="text.secondary" sx={{ maxWidth: 360 }}>
              You are not currently checked in. Please use the shared attendance register to check
              in.
            </Typography>
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

            {trackingEnabled ? (
              <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, textAlign: "left" }}>
                {needsAssignment ? (
                  <>
                    <Typography variant="body1" sx={{ mb: 1.5 }}>
                      No current assignment has been selected. Please select your current Category
                      and Role.
                    </Typography>
                    <Button
                      fullWidth
                      variant="contained"
                      disabled={switchBusy || selectionTree.length === 0}
                      onClick={openPicker}
                      sx={{ textTransform: "none", fontWeight: 700, py: 1.5 }}
                    >
                      Select Current Assignment
                    </Button>
                  </>
                ) : (
                  <>
                    <Typography variant="overline" color="text.secondary">
                      Current assignment
                    </Typography>
                    <Typography variant="h6" fontWeight={800} sx={{ mb: 0.5 }}>
                      {currentLabel || "No role selected"}
                    </Typography>
                    {assignmentStartedLabel ? (
                      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
                        Started at {assignmentStartedLabel}
                      </Typography>
                    ) : null}
                    <Button
                      fullWidth
                      variant="contained"
                      disabled={switchBusy || selectionTree.length === 0}
                      onClick={openPicker}
                      sx={{ textTransform: "none", fontWeight: 700, py: 1.5 }}
                    >
                      Change Role
                    </Button>
                  </>
                )}
              </Paper>
            ) : null}

            <Typography variant="body2" color="text.secondary" textAlign="center">
              Check out on the shared attendance register when your shift ends.
            </Typography>
          </Stack>
        )}
      </Paper>

      <Dialog open={pickOpen} onClose={() => !switchBusy && setPickOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle sx={{ fontWeight: 800 }}>
          {pickStep === "category" ? "Select category" : "Select role"}
        </DialogTitle>
        <DialogContent>
          {pickStep === "category" ? (
            <Stack spacing={1} sx={{ pt: 1 }}>
              {selectionTree.map((cat) => (
                <Button
                  key={cat.id}
                  variant={Number(pendingCategoryId) === Number(cat.id) ? "contained" : "outlined"}
                  onClick={() => {
                    setPendingCategoryId(cat.id);
                    setPendingRoleId(null);
                    setPickStep("role");
                  }}
                  sx={{ justifyContent: "flex-start", textTransform: "none", fontWeight: 700, py: 1.5 }}
                >
                  {cat.name}
                </Button>
              ))}
            </Stack>
          ) : (
            <Stack spacing={1} sx={{ pt: 1 }}>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
                {selectedCategory?.name}
              </Typography>
              <Grid container spacing={1}>
                {rolesForCategory.map((role) => (
                  <Grid item xs={6} key={role.role_id || role.id}>
                    <Button
                      fullWidth
                      variant={Number(pendingRoleId) === Number(role.role_id) ? "contained" : "outlined"}
                      onClick={() => setPendingRoleId(role.role_id)}
                      sx={{ textTransform: "none", fontWeight: 700, py: 1.5 }}
                    >
                      {role.role_name}
                    </Button>
                  </Grid>
                ))}
              </Grid>
            </Stack>
          )}
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          {pickStep === "role" ? (
            <Button onClick={() => setPickStep("category")} disabled={switchBusy}>
              Back
            </Button>
          ) : (
            <Button onClick={() => setPickOpen(false)} disabled={switchBusy}>
              {t("clock.cancel")}
            </Button>
          )}
          {pickStep === "role" ? (
            <Button
              variant="contained"
              onClick={confirmRoleChange}
              disabled={switchBusy || !pendingRoleId}
              size="large"
            >
              {switchBusy ? <CircularProgress size={22} color="inherit" /> : "Confirm"}
            </Button>
          ) : null}
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default ClockPage;
