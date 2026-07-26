import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Link,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import {
  closeVeewashStep1Day,
  getVeewashStep1DayStatus,
  reopenVeewashStep1Day,
  retryVeewashStep1Refresh,
} from "../../api";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

const BLOCKING_ROWS = [
  ["wf_pending", "WF Pending", { metric: "pending", title: "WF Pending", service: "wf" }],
  [
    "wf_review_required",
    "WF Review Required",
    { metric: "review_required", title: "WF Review Required", service: "wf" },
  ],
  [
    "hd_review_required",
    "HD Review Required",
    { metric: "review_required", title: "HD Review Required", service: "hd" },
  ],
  [
    "hd_partially_recorded",
    "HD Partially Recorded",
    {
      metric: "review_required",
      title: "HD Partially Recorded",
      service: "hd",
      queue: "partially_recorded",
    },
  ],
  [
    "other_unresolved",
    "Other unresolved exceptions",
    { metric: "review_required", title: "Other unresolved exceptions", service: "all" },
  ],
];

function fmtTs(v) {
  if (!v) return "—";
  const s = String(v);
  return s.length > 19 ? s.slice(0, 19).replace("T", " ") : s.replace("T", " ");
}

function emptyBlockingCounts() {
  return {
    wf_pending: 0,
    wf_review_required: 0,
    hd_review_required: 0,
    hd_partially_recorded: 0,
    other_unresolved: 0,
  };
}

export default function ShiftDayStatusBar({
  selectedDateEt,
  shiftDay,
  validation,
  isToday = false,
  onChanged,
  dataFreshness = null,
  onOpenBlockingList,
}) {
  const day = shiftDay || {};
  const status = String(day.status || "NOT_STARTED").toUpperCase();
  const readOnly = Boolean(day.read_only || status === "CLOSED");
  const notStarted = status === "NOT_STARTED";
  const reviewN = day.review_required_count ?? validation?.review_required_count ?? 0;
  const [closeOpen, setCloseOpen] = useState(false);
  const [reopenOpen, setReopenOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [retryMsg, setRetryMsg] = useState("");
  const [gateValidation, setGateValidation] = useState(validation || null);

  const refreshFailed =
    Boolean(day.step1_refresh_failed)
    || String(day.step1_refresh_status || "").toUpperCase() === "FAILED";

  useEffect(() => {
    setGateValidation(validation || null);
  }, [validation]);

  const statusColor = useMemo(() => {
    if (status === "CLOSED") return "default";
    if (status === "NOT_STARTED") return "default";
    if (status === "READY_TO_CLOSE") return "success";
    if (status === "REOPENED") return "warning";
    return "info";
  }, [status]);

  const statusLabel =
    status === "NOT_STARTED"
      ? "Not Started"
      : status.replaceAll("_", " ");

  const totals = gateValidation?.totals || validation?.totals || {};
  const blockingCounts = {
    ...emptyBlockingCounts(),
    ...(gateValidation?.blocking_counts || validation?.blocking_counts || {}),
  };
  const blockingTotal = BLOCKING_ROWS.reduce(
    (sum, [key]) => sum + (Number(blockingCounts[key]) || 0),
    0,
  );
  const canConfirmClose = blockingTotal === 0 && !notStarted;

  const refreshCloseGate = async () => {
    try {
      const res = await getVeewashStep1DayStatus({ date: selectedDateEt });
      if (res?.data?.validation) {
        setGateValidation(res.data.validation);
      }
    } catch {
      /* keep prior validation */
    }
  };

  const openCloseDialog = async () => {
    setError("");
    setCloseOpen(true);
    setBusy(true);
    try {
      await refreshCloseGate();
    } finally {
      setBusy(false);
    }
  };

  const submitClose = async () => {
    if (!canConfirmClose) {
      setError("Shift cannot be closed. Complete or review all admitted orders first.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const res = await closeVeewashStep1Day({
        date: selectedDateEt,
        reason: reason || undefined,
      });
      if (!res?.data?.ok) {
        const data = res?.data || {};
        if (data.blocking_counts) {
          setGateValidation((v) => ({ ...(v || {}), ...data, blocking_counts: data.blocking_counts }));
        }
        setError(
          data.message
            || "Shift cannot be closed. Complete or review all admitted orders first.",
        );
        return;
      }
      setCloseOpen(false);
      setReason("");
      onChanged?.();
    } catch (e) {
      const data = e?.response?.data || {};
      if (data.blocking_counts) {
        setGateValidation((v) => ({ ...(v || {}), ...data, blocking_counts: data.blocking_counts }));
      }
      setError(
        data.message
          || data.error
          || e?.message
          || "Shift cannot be closed. Complete or review all admitted orders first.",
      );
    } finally {
      setBusy(false);
    }
  };

  const submitReopen = async () => {
    if (!reason.trim()) {
      setError("Reopen reason is required");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const res = await reopenVeewashStep1Day({
        date: selectedDateEt,
        reason,
      });
      if (!res?.data?.ok) {
        setError(res?.data?.error || "Reopen failed");
        return;
      }
      setReopenOpen(false);
      setReason("");
      onChanged?.();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Reopen failed");
    } finally {
      setBusy(false);
    }
  };

  const submitRetryRefresh = async () => {
    setBusy(true);
    setError("");
    setRetryMsg("");
    try {
      const res = await retryVeewashStep1Refresh({
        date: selectedDateEt,
        import_batch_id: day.step1_refresh_scrape_batch_id,
      });
      if (!res?.data?.ok) {
        setError(
          res?.data?.error
            || "Portal import succeeded, but Shift Monitor refresh failed. Retry refresh.",
        );
        return;
      }
      setRetryMsg("Shift Monitor refresh succeeded.");
      onChanged?.();
    } catch (e) {
      setError(
        e?.response?.data?.error
          || e?.message
          || "Portal import succeeded, but Shift Monitor refresh failed. Retry refresh.",
      );
    } finally {
      setBusy(false);
    }
  };

  const openBlocking = (spec) => {
    if (!onOpenBlockingList || !spec) return;
    setCloseOpen(false);
    onOpenBlockingList(spec.metric, spec.title, {
      service: spec.service,
      queue: spec.queue || spec.metric,
    });
  };

  return (
    <Box
      sx={{
        mb: 1.5,
        p: 1.25,
        borderRadius: 2,
        border: "1px solid",
        borderColor: readOnly ? "#cbd5e1" : VEEWASH_DASHBOARD.primaryBlueBorder,
        bgcolor: readOnly ? "#f8fafc" : "#fff",
      }}
    >
      <Stack
        direction={{ xs: "column", sm: "row" }}
        spacing={1}
        justifyContent="space-between"
        alignItems={{ xs: "stretch", sm: "center" }}
      >
        <Stack spacing={0.35}>
          <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap>
            <Typography variant="subtitle2" fontWeight={800}>
              Shift Status
            </Typography>
            <Chip
              size="small"
              color={statusColor}
              label={statusLabel}
              variant={notStarted ? "outlined" : "filled"}
              sx={
                notStarted
                  ? { bgcolor: "#e2e8f0", color: "#475569", borderColor: "#cbd5e1" }
                  : undefined
              }
            />
            {isToday ? <Chip size="small" variant="outlined" label="Live" /> : null}
            {readOnly ? <Chip size="small" variant="outlined" label="Read-only" /> : null}
          </Stack>
          <Typography variant="caption" color="text.secondary">
            {notStarted
              ? "Shift has not started."
              : `Opened ${fmtTs(day.opened_at)} · Step-1 refreshed ${fmtTs(
                  day.step1_refreshed_at || day.last_sync_at
                )} · Review Required ${reviewN}`}
            {!notStarted && day.closed_by_display_name
              ? ` · Closed by ${day.closed_by_display_name} @ ${fmtTs(day.closed_at)}`
              : ""}
          </Typography>
          {refreshFailed ? (
            <Alert
              severity="warning"
              sx={{ mt: 0.75, py: 0.5 }}
              action={
                !readOnly ? (
                  <Button color="inherit" size="small" disabled={busy} onClick={submitRetryRefresh}>
                    Retry Shift Monitor Refresh
                  </Button>
                ) : null
              }
            >
              Portal import succeeded, but Shift Monitor refresh failed. Retry refresh.
              {day.step1_refresh_error
                ? ` (${String(day.step1_refresh_error).slice(0, 120)})`
                : ""}
            </Alert>
          ) : null}
          {retryMsg ? (
            <Alert severity="success" sx={{ mt: 0.75, py: 0.5 }} onClose={() => setRetryMsg("")}>
              {retryMsg}
            </Alert>
          ) : null}
          {dataFreshness && dataFreshness.status && dataFreshness.status !== "ok" ? (
            <Box sx={{ mt: 0.35 }}>
              <Typography variant="caption" color="warning.main" display="block" fontWeight={700}>
                Scan data freshness: {String(dataFreshness.status).replaceAll("_", " ")}
              </Typography>
              <Typography variant="caption" color="warning.main" display="block">
                Last scan refresh: {fmtTs(dataFreshness.last_scan_refresh_at || dataFreshness.most_recent_persisted_scan_at)}
                {" · "}
                Last portal scrape: {fmtTs(dataFreshness.last_portal_scrape_at || dataFreshness.portal_last_seen_at)}
              </Typography>
              <Typography variant="caption" color="warning.main" display="block">
                Portal ahead by:{" "}
                {dataFreshness.portal_ahead_bag_count ?? dataFreshness.stale_chronology_bag_count ?? 0}{" "}
                bag(s)
                {" · "}
                Pending count may be incomplete
              </Typography>
              <Typography variant="caption" color="text.secondary" display="block">
                Retry / Refresh Portal Sync to update status. Pending is provisional until freshness is ok.
              </Typography>
            </Box>
          ) : null}
        </Stack>
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          {!readOnly && isToday ? (
            <Button
              size="small"
              variant="outlined"
              color={refreshFailed ? "warning" : "primary"}
              disabled={notStarted || busy}
              onClick={submitRetryRefresh}
            >
              Retry Shift Monitor Refresh
            </Button>
          ) : null}
          {readOnly ? (
            <Button size="small" variant="outlined" onClick={() => setReopenOpen(true)}>
              Reopen Shift
            </Button>
          ) : (
            <Button
              size="small"
              variant="contained"
              disabled={notStarted || busy}
              onClick={openCloseDialog}
              sx={{ bgcolor: VEEWASH_DASHBOARD.primaryBlue }}
            >
              Close Shift
            </Button>
          )}
        </Stack>
      </Stack>

      <Dialog open={closeOpen} onClose={() => !busy && setCloseOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Close Shift · {selectedDateEt}</DialogTitle>
        <DialogContent dividers>
          {error ? (
            <Alert severity="error" sx={{ mb: 1 }} onClose={() => setError("")}>
              {error}
            </Alert>
          ) : null}
          {!canConfirmClose ? (
            <Alert severity="warning" sx={{ mb: 1.25 }}>
              Shift cannot be closed. Complete or review all admitted orders first.
            </Alert>
          ) : (
            <Alert severity="success" sx={{ mb: 1.25 }}>
              All admitted orders are completed or approved-excluded. Closing will freeze this
              snapshot.
            </Alert>
          )}
          <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 0.75 }}>
            Blocking status
          </Typography>
          <Stack spacing={0.5} sx={{ mb: 1.5 }}>
            {BLOCKING_ROWS.map(([key, label, spec]) => {
              const n = Number(blockingCounts[key]) || 0;
              const clickable = n > 0 && typeof onOpenBlockingList === "function";
              return (
                <Stack
                  key={key}
                  direction="row"
                  justifyContent="space-between"
                  alignItems="center"
                  sx={{
                    px: 1,
                    py: 0.5,
                    borderRadius: 1,
                    bgcolor: n > 0 ? "#fff7ed" : "#f8fafc",
                  }}
                >
                  {clickable ? (
                    <Link
                      component="button"
                      type="button"
                      underline="hover"
                      onClick={() => openBlocking(spec)}
                      sx={{ fontWeight: 700, textAlign: "left" }}
                    >
                      {label}
                    </Link>
                  ) : (
                    <Typography variant="body2" fontWeight={n > 0 ? 700 : 500}>
                      {label}
                    </Typography>
                  )}
                  <Typography
                    variant="body2"
                    fontWeight={800}
                    color={n > 0 ? "warning.dark" : "text.secondary"}
                  >
                    {n}
                  </Typography>
                </Stack>
              );
            })}
          </Stack>
          <Box sx={{ mt: 0.5, p: 1, bgcolor: "#f8fafc", borderRadius: 1 }}>
            <Typography variant="caption" display="block" fontWeight={700}>
              Final totals
            </Typography>
            <Typography variant="caption" display="block">
              TOTAL Active {totals.active ?? "—"} · Completed {totals.completed ?? "—"} · Pending{" "}
              {totals.pending ?? "—"} · Review {totals.review_required ?? reviewN}
              {totals.approved_excluded != null
                ? ` · Excluded ${totals.approved_excluded}`
                : ""}
            </Typography>
            <Typography variant="caption" display="block">
              WF Pending {totals.wf?.pending ?? blockingCounts.wf_pending} / Review{" "}
              {totals.wf?.review_required ?? blockingCounts.wf_review_required} / Done{" "}
              {totals.wf?.completed ?? "—"}
            </Typography>
            <Typography variant="caption" display="block">
              HD Review {totals.hd?.review_required ?? blockingCounts.hd_review_required} / Partial{" "}
              {totals.hd?.partially_recorded ?? blockingCounts.hd_partially_recorded} / Recorded{" "}
              {totals.hd?.completed ?? "—"}
            </Typography>
          </Box>
          <TextField
            sx={{ mt: 1.25 }}
            fullWidth
            size="small"
            label="Close note (optional)"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            multiline
            minRows={2}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCloseOpen(false)} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant="contained"
            onClick={submitClose}
            disabled={busy || !canConfirmClose}
          >
            {busy ? "Closing…" : "Confirm Close"}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={reopenOpen} onClose={() => !busy && setReopenOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle>Reopen Shift · {selectedDateEt}</DialogTitle>
        <DialogContent dividers>
          {error ? (
            <Alert severity="error" sx={{ mb: 1 }} onClose={() => setError("")}>
              {error}
            </Alert>
          ) : null}
          <TextField
            fullWidth
            size="small"
            required
            label="Reopen reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            multiline
            minRows={2}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setReopenOpen(false)} disabled={busy}>
            Cancel
          </Button>
          <Button variant="contained" onClick={submitReopen} disabled={busy}>
            {busy ? "Reopening…" : "Confirm Reopen"}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
