import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import {
  attendancePinCleaningTasksApprove,
  attendancePinCleaningTasksReject,
  attendancePinCleaningTasksReview,
} from "../api";
import { OpsMobileShell, OpsTopBar, OPS_MOBILE } from "../opsMobile";
import {
  clearPinHubSession,
  loadPinHubSession,
  pinHubMenuPath,
} from "../utils/pinHubSession";

function sanitizeSlug(raw) {
  if (!raw) return "";
  try {
    return decodeURIComponent(String(raw))
      .toLowerCase()
      .replace(/[^a-z0-9-]/g, "")
      .slice(0, 64);
  } catch {
    return "";
  }
}

function formatDuration(seconds) {
  if (seconds == null) return "—";
  const sec = Math.max(0, Number(seconds) || 0);
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

/**
 * Supervisor PIN Task Review — verify / reject completed tasks.
 */
export default function CleaningTaskReviewPinPage() {
  const { orgSlug: routeSlug } = useParams();
  const navigate = useNavigate();
  const slug = sanitizeSlug(routeSlug);
  const hub = useMemo(() => loadPinHubSession(), []);

  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [queue, setQueue] = useState(null);
  const [rejectId, setRejectId] = useState(null);
  const [reason, setReason] = useState("");
  const [selected, setSelected] = useState(() => new Set());

  const goHub = useCallback(() => {
    navigate(pinHubMenuPath(slug || hub?.organization_slug || ""), { replace: true });
  }, [navigate, slug, hub?.organization_slug]);

  const lock = useCallback(() => {
    clearPinHubSession();
    navigate(`/pin/${encodeURIComponent(slug || hub?.organization_slug || "")}`, { replace: true });
  }, [navigate, slug, hub?.organization_slug]);

  const load = useCallback(async () => {
    if (!hub?.token || !slug) {
      setError("Enter your PIN again.");
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const res = await attendancePinCleaningTasksReview(slug, hub.pin, { hubToken: hub.token });
      const body = res?.data || {};
      if (!body.ok) throw new Error(body.error || "Could not load review");
      setQueue(body);
      setSelected(new Set());
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Could not load review");
    } finally {
      setLoading(false);
    }
  }, [hub, slug]);

  useEffect(() => {
    load();
  }, [load]);

  const toggle = (id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const approveIds = async (ids) => {
    const list = (ids || []).filter(Boolean);
    if (!list.length) return;
    setBusy(true);
    setError("");
    try {
      const res = await attendancePinCleaningTasksApprove(slug, hub.pin, {
        hubToken: hub.token,
        activity_ids: list,
      });
      const body = res?.data || {};
      if (!body.ok) throw new Error(body.error || "Could not approve");
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Could not approve");
    } finally {
      setBusy(false);
    }
  };

  const approveSelected = async () => approveIds([...selected]);

  const rejectOne = async () => {
    if (!rejectId) return;
    setBusy(true);
    setError("");
    try {
      const res = await attendancePinCleaningTasksReject(slug, hub.pin, {
        hubToken: hub.token,
        activity_id: rejectId,
        reason,
      });
      const body = res?.data || {};
      if (!body.ok) throw new Error(body.error || "Could not reject");
      setRejectId(null);
      setReason("");
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Could not reject");
    } finally {
      setBusy(false);
    }
  };

  const sections = [
    ["Pending approvals", queue?.pending_approval || [], true],
    ["In progress", queue?.in_progress || [], false],
    ["Overdue", queue?.overdue || [], false],
    ["Not started", queue?.not_started || [], false],
    ["Approved", queue?.approved || [], false],
    ["Rejected / redo", queue?.rejected || [], false],
  ];

  if (!hub?.token) {
    return (
      <OpsMobileShell>
        <Alert severity="warning">Enter your PIN again.</Alert>
        <Button onClick={lock}>Back to PIN</Button>
      </OpsMobileShell>
    );
  }

  return (
    <OpsMobileShell>
      <OpsTopBar
        title="Task Review"
        onBack={goHub}
        onLock={lock}
        identity={hub.employee_first_name || hub.employee_name || ""}
      />
      {error ? (
        <Alert severity="error" sx={{ mb: 1.5 }}>
          {error}
        </Alert>
      ) : null}
      {loading ? (
        <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
          <CircularProgress />
        </Box>
      ) : (
        <Stack spacing={2}>
          {queue?.approval_policy_label ? (
            <Alert severity="info">{queue.approval_policy_label}</Alert>
          ) : null}
          {(queue?.shift_end?.blocking_close || []).length ? (
            <Alert severity="warning">
              Before closing the day: {(queue.shift_end.blocking_close || []).length} incomplete,
              overdue, rejected, or pending-approval contribution
              {(queue.shift_end.blocking_close || []).length === 1 ? "" : "s"} still open. Completed
              tasks stay Pending Approval until a supervisor verifies them.
            </Alert>
          ) : (
            <Alert severity="success">No open cleaning items blocking close for today.</Alert>
          )}
          {(queue?.pending_approval || []).length ? (
            <Button
              variant="contained"
              disabled={busy || selected.size === 0}
              onClick={approveSelected}
              sx={{ fontWeight: 800, textTransform: "none" }}
            >
              Approve selected ({selected.size})
            </Button>
          ) : null}
          {sections.map(([label, rows, selectable]) => (
            <Box key={label}>
              <Typography sx={{ fontWeight: 800, mb: 1, color: OPS_MOBILE.navy }}>
                {label} ({rows.length})
              </Typography>
              <Stack spacing={1}>
                {rows.length ? (
                  rows.map((row) => {
                    const act = row.activity;
                    const id = act?.id;
                    return (
                      <Box
                        key={`${row.responsibility_id}-${id || "none"}`}
                        sx={{
                          p: 1.5,
                          borderRadius: 2,
                          border: `1px solid ${OPS_MOBILE.border}`,
                          bgcolor: selectable && id && selected.has(id) ? "#eff6ff" : "#fff",
                        }}
                        onClick={() => selectable && id && toggle(id)}
                      >
                        <Typography sx={{ fontWeight: 800 }}>
                          {row.role_label || row.role} · {row.employee_name}
                        </Typography>
                        {row.activity_group_label ? (
                          <Typography variant="caption" color="text.secondary" display="block">
                            {row.activity_group_label}
                          </Typography>
                        ) : null}
                        <Typography variant="body2" color="text.secondary">
                          Timing {row.timing_label || "Anytime"}
                          {act
                            ? ` · ${act.started_at || "—"} → ${act.ended_at || "—"} (${formatDuration(act.duration_seconds)})`
                            : " · Not started"}
                        </Typography>
                        {selectable && id ? (
                          <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
                            <Button
                              size="small"
                              variant="contained"
                              disabled={busy}
                              onClick={(e) => {
                                e.stopPropagation();
                                approveIds([id]);
                              }}
                              sx={{ textTransform: "none", fontWeight: 700 }}
                            >
                              Approve
                            </Button>
                            <Button
                              size="small"
                              color="warning"
                              variant="outlined"
                              disabled={busy}
                              onClick={(e) => {
                                e.stopPropagation();
                                setRejectId(id);
                                setReason("");
                              }}
                              sx={{ textTransform: "none", fontWeight: 700 }}
                            >
                              Needs redo
                            </Button>
                          </Stack>
                        ) : null}
                        {act?.rejection_reason ? (
                          <Typography variant="caption" color="error" display="block" sx={{ mt: 0.5 }}>
                            {act.rejection_reason}
                          </Typography>
                        ) : null}
                      </Box>
                    );
                  })
                ) : (
                  <Typography variant="body2" color="text.secondary">
                    None
                  </Typography>
                )}
              </Stack>
            </Box>
          ))}
          {rejectId ? (
            <Box sx={{ p: 1.5, borderRadius: 2, border: `1px solid ${OPS_MOBILE.border}`, bgcolor: "#fff7ed" }}>
              <Typography sx={{ fontWeight: 800, mb: 1 }}>Rejection reason</Typography>
              <TextField
                fullWidth
                size="small"
                multiline
                minRows={2}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Required"
              />
              <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
                <Button variant="contained" color="warning" disabled={busy} onClick={rejectOne} sx={{ textTransform: "none", fontWeight: 800 }}>
                  Reject
                </Button>
                <Button disabled={busy} onClick={() => setRejectId(null)} sx={{ textTransform: "none" }}>
                  Cancel
                </Button>
              </Stack>
            </Box>
          ) : null}
        </Stack>
      )}
    </OpsMobileShell>
  );
}
