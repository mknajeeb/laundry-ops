import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Collapse,
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
import { OpsLocaleToggle, OpsMobileShell, OpsTopBar, OPS_MOBILE } from "../opsMobile";
import { useI18n } from "../i18n/I18nContext";
import {
  clearPinHubSession,
  loadPinHubSession,
  pinHubMenuPath,
} from "../utils/pinHubSession";

function ReviewGroup({ label, count, startOpen, children }) {
  const [open, setOpen] = useState(startOpen);
  return (
    <Box>
      <Button
        fullWidth
        onClick={() => setOpen((value) => !value)}
        sx={{ justifyContent: "space-between", textTransform: "none", fontWeight: 800, px: 0, color: OPS_MOBILE.navy }}
      >
        <span>
          {label} ({count})
        </span>
        <span>{open ? "−" : "+"}</span>
      </Button>
      <Collapse in={open}>{children}</Collapse>
    </Box>
  );
}

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
  const { t } = useI18n();
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
      setError(t("tasks.pin.enterPin"));
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    setNotice("");
    try {
      const res = await attendancePinCleaningTasksReview(slug, hub.pin, { hubToken: hub.token });
      const body = res?.data || {};
      if (!body.ok) throw new Error(body.error || t("tasks.pin.loadReview"));
      setQueue(body);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("tasks.pin.loadReview"));
    } finally {
      setLoading(false);
    }
  }, [hub, slug, t]);

  useEffect(() => {
    load();
  }, [load]);

  const approveIds = async (ids, approveAll = false, supervisorRemark = "") => {
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
        supervisor_remark: supervisorRemark || "",
      });
      const body = res?.data || {};
      if (!body.ok) throw new Error(body.error || t("tasks.pin.approveFailed"));
      setNotice(approveAll ? t("tasks.pin.assignmentVerified") : t("tasks.pin.verifiedNotice"));
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("tasks.pin.approveFailed"));
    } finally {
      setBusy(false);
    }
  };

  const rejectIds = async (ids, rejectReason) => {
    const list = (ids || []).filter(Boolean);
    if (!list.length) return;
    if (String(rejectReason || "").trim().length < 3) {
      setError(t("tasks.pin.reasonRequired"));
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
      if (!body.ok) throw new Error(body.error || t("tasks.pin.rejectFailed"));
      setNotice(list.length > 1 ? t("tasks.pin.assignmentRedo") : t("tasks.pin.itemCorrection"));
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || t("tasks.pin.rejectFailed"));
    } finally {
      setBusy(false);
    }
  };

  const reviewCards = queue?.verification_cards || [];
  const endOfDayClose = Array.isArray(queue?.shift_end?.end_of_day_close)
    ? queue.shift_end.end_of_day_close
    : (queue?.shift_end?.blocking_close || []).filter(
        (row) => String(row?.category_code || row?.activity?.category_code || "") === "end_of_day"
      );
  const sections = [
    [t("tasks.pin.inProgress"), queue?.in_progress || []],
    [t("tasks.pin.status.overdue"), queue?.overdue || []],
    [t("tasks.pin.notStarted"), queue?.not_started || []],
    [t("tasks.pin.approved"), queue?.approved || []],
    [t("tasks.pin.rejectedRedo"), queue?.rejected || []],
  ];

  if (!hub?.token) {
    return (
      <OpsMobileShell>
        <Alert severity="warning">{t("tasks.pin.enterPin")}</Alert>
        <Button onClick={lock}>{t("tasks.pin.backToPin")}</Button>
      </OpsMobileShell>
    );
  }

  return (
    <OpsMobileShell>
      <OpsTopBar
        title={t("tasks.pin.reviewTitle")}
        onBack={goHub}
        onLock={lock}
        lockLabel={t("mobileOps.lock")}
        identity={hub.employee_first_name || hub.employee_name || ""}
        right={<OpsLocaleToggle />}
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
          <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
            {[
              [t("tasks.dashboard.waiting"), reviewCards.length],
              [t("tasks.pin.inProgress"), (queue?.in_progress || []).length],
              [t("tasks.pin.status.overdue"), (queue?.overdue || []).length],
              [t("tasks.pin.approved"), (queue?.approved || []).length],
              [t("tasks.pin.rejectedRedo"), (queue?.rejected || []).length],
            ].map(([label, count]) => (
              <Box
                key={label}
                sx={{
                  px: 1,
                  py: 0.5,
                  borderRadius: 1.5,
                  bgcolor: "#fff",
                  border: `1px solid ${OPS_MOBILE.border}`,
                  minWidth: 72,
                }}
              >
                <Typography variant="caption" color="text.secondary" display="block" sx={{ lineHeight: 1.1 }}>
                  {label}
                </Typography>
                <Typography sx={{ fontWeight: 800, lineHeight: 1.2 }}>{count}</Typography>
              </Box>
            ))}
          </Stack>
          {endOfDayClose.length ? (
            <Typography variant="body2" color="text.secondary">
              {t("tasks.pin.blockingClose", {
                count: endOfDayClose.length,
                plural: endOfDayClose.length === 1 ? "" : "s",
              })}
            </Typography>
          ) : null}
          <Box>
            <Typography sx={{ fontWeight: 800, mb: 1, color: OPS_MOBILE.navy }}>
              {t("tasks.pin.pendingApprovals", { count: reviewCards.length })}
            </Typography>
            <Stack spacing={1}>
              {reviewCards.length ? (
                reviewCards.map((card) => (
                  <TaskVerificationReviewCard
                    key={card.assignment_key}
                    card={card}
                    busy={busy}
                    onApproveAll={(ids, extra) => approveIds(ids, extra?.section ? false : true, extra?.remark || "")}
                    onNeedsRedo={(ids, redoReason) => rejectIds(ids, redoReason)}
                    onRejectItem={(id, itemReason) => rejectIds([id], itemReason)}
                  />
                ))
              ) : (
                <Typography variant="body2" color="text.secondary">
                  {t("tasks.pin.none")}
                </Typography>
              )}
            </Stack>
          </Box>
          {sections.map(([label, rows], index) => (
            <ReviewGroup
              key={label}
              label={label}
              count={rows.length}
              startOpen={index === 0 || index === 1 || index === 4}
            >
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
                          {row.timing_label ? t("tasks.pin.scheduled", { time: row.timing_label }) : t("tasks.pin.anytime")}
                          {act?.started_at
                            ? ` · ${t("tasks.pin.started", { time: reviewClock(act.started_at) || "—" })}`
                            : ` · ${t("tasks.pin.notStarted")}`}
                          {act?.ended_at && reviewClock(act.ended_at) !== reviewClock(act.started_at)
                            ? ` · ${t("tasks.pin.finished", { time: reviewClock(act.ended_at) })}`
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
                    {t("tasks.pin.none")}
                  </Typography>
                )}
              </Stack>
            </ReviewGroup>
          ))}
        </Stack>
      )}
    </OpsMobileShell>
  );
}
