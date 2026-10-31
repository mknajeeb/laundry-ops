import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Stack,
  Typography,
} from "@mui/material";
import {
  attendancePinCleaningTasksApprove,
  attendancePinCleaningTasksReject,
  attendancePinCleaningTasksReview,
} from "../api";
import TaskVerificationReviewCard from "../components/tasks/TaskVerificationReviewCard";
import { formatDashboardTime } from "../components/tasks/taskDashboardFormat";
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

function reviewClock(value) {
  const text = formatDashboardTime(value);
  return text === "—" ? null : text;
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
  const [notice, setNotice] = useState("");

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
    setNotice("");
    try {
      const res = await attendancePinCleaningTasksReview(slug, hub.pin, { hubToken: hub.token });
      const body = res?.data || {};
      if (!body.ok) throw new Error(body.error || "Could not load review");
      setQueue(body);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Could not load review");
    } finally {
      setLoading(false);
    }
  }, [hub, slug]);

  useEffect(() => {
    load();
  }, [load]);

  const approveIds = async (ids, approveAll = false) => {
    const list = (ids || []).filter(Boolean);
    if (!list.length) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const res = await attendancePinCleaningTasksApprove(slug, hub.pin, {
        hubToken: hub.token,
        activity_ids: list,
        approve_all: approveAll,
      });
      const body = res?.data || {};
      if (!body.ok) throw new Error(body.error || "Could not approve");
      setNotice(approveAll ? "Assignment verified." : "Verified.");
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Could not approve");
    } finally {
      setBusy(false);
    }
  };

  const rejectIds = async (ids, rejectReason) => {
    const list = (ids || []).filter(Boolean);
    if (!list.length) return;
    if (String(rejectReason || "").trim().length < 3) {
      setError("A rejection reason is required.");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const res = await attendancePinCleaningTasksReject(slug, hub.pin, {
        hubToken: hub.token,
        activity_ids: list,
        reason: rejectReason,
      });
      const body = res?.data || {};
      if (!body.ok) throw new Error(body.error || "Could not reject");
      setNotice(list.length > 1 ? "Assignment sent back for redo." : "Item sent back for correction.");
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Could not reject");
    } finally {
      setBusy(false);
    }
  };

  const reviewCards = queue?.verification_cards || [];
  const sections = [
    ["In progress", queue?.in_progress || []],
    ["Overdue", queue?.overdue || []],
    ["Not started", queue?.not_started || []],
    ["Approved", queue?.approved || []],
    ["Rejected / redo", queue?.rejected || []],
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
          {notice ? (
        <Alert severity="success" sx={{ mb: 1.5 }}>
          {notice}
        </Alert>
      ) : null}
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
          <Box>
            <Typography sx={{ fontWeight: 800, mb: 1, color: OPS_MOBILE.navy }}>
              Pending approvals ({reviewCards.length})
            </Typography>
            <Stack spacing={1}>
              {reviewCards.length ? (
                reviewCards.map((card) => (
                  <TaskVerificationReviewCard
                    key={card.assignment_key}
                    card={card}
                    busy={busy}
                    onApproveAll={(ids) => approveIds(ids, true)}
                    onNeedsRedo={(ids, redoReason) => rejectIds(ids, redoReason)}
                    onRejectItem={(id, itemReason) => rejectIds([id], itemReason)}
                  />
                ))
              ) : (
                <Typography variant="body2" color="text.secondary">
                  None
                </Typography>
              )}
            </Stack>
          </Box>
          {sections.map(([label, rows]) => (
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
                          bgcolor: "#fff",
                        }}
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
                          {row.timing_label ? `Scheduled: ${row.timing_label}` : "Anytime"}
                          {act?.started_at
                            ? ` · Started: ${reviewClock(act.started_at) || "—"}`
                            : " · Not started"}
                          {act?.ended_at && reviewClock(act.ended_at) !== reviewClock(act.started_at)
                            ? ` · Finished: ${reviewClock(act.ended_at)}`
                            : ""}
                        </Typography>
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
        </Stack>
      )}
    </OpsMobileShell>
  );
}
