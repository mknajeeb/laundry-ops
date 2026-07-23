import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  createTaskTrackingSwitchIdempotencyKey,
  getTaskTrackingSelectionTree,
  getTaSessionCurrent,
  postTaskTrackingSwitchTask,
  taBreakEnd,
} from "../api";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";
import { roleChoiceButtonSx } from "../utils/roleChoiceButtonSx";

const SWITCH_TIMEOUT_MESSAGE =
  "The role change is taking longer than expected and may already have completed. Refresh your current assignment before trying again.";

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
  const [pickMode, setPickMode] = useState("switch"); // switch | break_resume
  const [pendingCategoryId, setPendingCategoryId] = useState(null);
  const [switchBusy, setSwitchBusy] = useState(false);
  const [needsRefreshBeforeSwitch, setNeedsRefreshBeforeSwitch] = useState(false);
  const switchIdempotencyKeyRef = useRef(null);
  const breakResumeAttemptedRef = useRef(null);

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
    if (!session?.open_break) {
      breakResumeAttemptedRef.current = null;
      return undefined;
    }
    const breakKey = `${session.id}:${session.open_break.id || session.open_break.break_start_at}`;
    if (breakResumeAttemptedRef.current === breakKey) return undefined;
    breakResumeAttemptedRef.current = breakKey;
    let cancelled = false;
    (async () => {
      try {
        await taBreakEnd();
        if (!cancelled) await loadSession(true);
      } catch (e) {
        const data = e?.response?.data;
        if (data?.needs_category_role && Array.isArray(data.selection_tree)) {
          if (cancelled) return;
          setSelectionTree(data.selection_tree);
          const curCat = taskTracking?.current_category_id;
          const hasCur =
            curCat != null &&
            data.selection_tree.some((c) => Number(c.id) === Number(curCat));
          setPendingCategoryId(hasCur ? Number(curCat) : data.selection_tree[0]?.id ?? null);
          setPickMode("break_resume");
          setPickOpen(true);
          setActionError("");
          return;
        }
        console.error(e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [session?.id, session?.open_break, loadSession, taskTracking?.current_category_id]);

  useEffect(() => {
    if (authLoading || !isClockedIn) return undefined;
    const id = setInterval(() => loadSession(true), 30000);
    return () => clearInterval(id);
  }, [authLoading, isClockedIn, loadSession]);

  const openPicker = () => {
    if (needsRefreshBeforeSwitch) return;
    setPickMode("switch");
    const curCat = taskTracking?.current_category_id;
    const hasCur =
      curCat != null && selectionTree.some((c) => Number(c.id) === Number(curCat));
    setPendingCategoryId(hasCur ? Number(curCat) : selectionTree[0]?.id ?? null);
    switchIdempotencyKeyRef.current = null;
    setPickOpen(true);
  };

  const refreshAssignment = async () => {
    setActionError("");
    await loadSession(true);
    setNeedsRefreshBeforeSwitch(false);
    switchIdempotencyKeyRef.current = null;
  };

  const confirmRoleSelection = async (categoryId, roleId) => {
    if (!categoryId || !roleId || switchBusy) return;
    if (pickMode === "switch" && needsRefreshBeforeSwitch) return;
    setSwitchBusy(true);
    setActionError("");
    try {
      if (pickMode === "break_resume") {
        await taBreakEnd({ category_id: categoryId, role_id: roleId });
        setPickOpen(false);
        setPickMode("switch");
        await loadSession(true);
        return;
      }
      if (!switchIdempotencyKeyRef.current) {
        switchIdempotencyKeyRef.current = createTaskTrackingSwitchIdempotencyKey();
      }
      const idempotency_key = switchIdempotencyKeyRef.current;
      await postTaskTrackingSwitchTask({
        category_id: categoryId,
        role_id: roleId,
        idempotency_key,
      });
      switchIdempotencyKeyRef.current = null;
      setNeedsRefreshBeforeSwitch(false);
      setPickOpen(false);
      await loadSession(true);
    } catch (e) {
      if (pickMode === "switch" && e?.code === "ECONNABORTED") {
        setNeedsRefreshBeforeSwitch(true);
        setActionError(SWITCH_TIMEOUT_MESSAGE);
        try {
          await loadSession(true);
        } catch {
          /* keep timeout guidance even if refresh fails */
        }
      } else {
        setActionError(
          e?.response?.data?.error ||
            e?.message ||
            (pickMode === "break_resume" ? "Could not resume from break" : "Could not change role"),
        );
      }
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
        {needsRefreshBeforeSwitch ? (
          <Button
            fullWidth
            variant="outlined"
            onClick={refreshAssignment}
            sx={{ mb: 2, textTransform: "none", fontWeight: 700 }}
          >
            Refresh current assignment
          </Button>
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
                      disabled={
                        switchBusy || needsRefreshBeforeSwitch || selectionTree.length === 0
                      }
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
                      disabled={
                        switchBusy || needsRefreshBeforeSwitch || selectionTree.length === 0
                      }
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

      <Dialog
        open={pickOpen}
        onClose={() => !switchBusy && pickMode !== "break_resume" && setPickOpen(false)}
        fullWidth
        maxWidth="xs"
      >
        <DialogTitle sx={{ fontWeight: 800 }}>
          {pickMode === "break_resume" ? "Select role to resume" : "Change role"}
        </DialogTitle>
        <DialogContent>
          <Stack spacing={1.5} sx={{ pt: 1 }}>
            <Typography variant="subtitle2" fontWeight={800}>
              Category
            </Typography>
            <Grid container spacing={1}>
              {selectionTree.map((cat) => (
                <Grid item xs={6} key={cat.id}>
                  <Button
                    fullWidth
                    variant={Number(pendingCategoryId) === Number(cat.id) ? "contained" : "outlined"}
                    disabled={switchBusy}
                    onClick={() => {
                      setPendingCategoryId(cat.id);
                    }}
                    sx={{ textTransform: "none", fontWeight: 700, py: 1.5 }}
                  >
                    {cat.name}
                  </Button>
                </Grid>
              ))}
            </Grid>
            <Typography variant="subtitle2" fontWeight={800}>
              Role
            </Typography>
            <Grid container spacing={1}>
              {rolesForCategory.map((role) => (
                <Grid item xs={6} key={role.role_id || role.id}>
                  <Button
                    fullWidth
                    variant="outlined"
                    disabled={switchBusy || !pendingCategoryId || needsRefreshBeforeSwitch}
                    onClick={() => confirmRoleSelection(pendingCategoryId, role.role_id)}
                    sx={{
                      textTransform: "none",
                      fontWeight: 700,
                      py: 1.6,
                      ...roleChoiceButtonSx(role.role_name),
                    }}
                  >
                    {switchBusy ? <CircularProgress size={20} color="inherit" /> : role.role_name}
                  </Button>
                </Grid>
              ))}
            </Grid>
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          {pickMode === "break_resume" ? null : (
            <Button onClick={() => setPickOpen(false)} disabled={switchBusy}>
              {t("clock.cancel")}
            </Button>
          )}
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default ClockPage;
