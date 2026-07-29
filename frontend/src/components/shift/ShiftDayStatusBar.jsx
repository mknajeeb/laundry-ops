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

function fmtTs(v) {
  if (!v) return "—";
  const s = String(v);
  return s.length > 19 ? s.slice(0, 19).replace("T", " ") : s.replace("T", " ");
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
  const [closeConfirmation, setCloseConfirmation] = useState(null);

  const refreshFailed =
    Boolean(day.step1_refresh_failed)
    || String(day.step1_refresh_status || "").toUpperCase() === "FAILED";

  useEffect(() => {
    setGateValidation(validation || null);
    setCloseConfirmation(validation?.close_archive?.confirmation || null);
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
  const confirmation =
    closeConfirmation
    || gateValidation?.close_archive?.confirmation
    || {
      completed: totals.completed ?? 0,
      unfinished:
        (Number(totals.pending) || 0)
        + (Number(totals.review_required) || 0),
    };
  const canConfirmClose = !notStarted && status !== "CLOSED";

  const refreshCloseGate = async () => {
    try {
      const res = await getVeewashStep1DayStatus({ date: selectedDateEt });
      if (res?.data?.validation) {
        setGateValidation(res.data.validation);
      }
      if (res?.data?.close_confirmation) {
        setCloseConfirmation(res.data.close_confirmation);
      } else if (res?.data?.validation?.close_archive?.confirmation) {
        setCloseConfirmation(res.data.validation.close_archive.confirmation);
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
      setError("Shift has not started — nothing to close.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const res = await closeVeewashStep1Day({
        date: selectedDateEt,
        reason: reason || undefined,
        // Advisory dialog counts — backend recomputes and may 409 on mismatch.
        expected_completed: confirmation.completed ?? undefined,
        expected_unfinished: confirmation.unfinished ?? undefined,
      });
      if (!res?.data?.ok) {
        const data = res?.data || {};
        if (data.error === "close_confirmation_stale" && data.confirmation) {
          setCloseConfirmation(data.confirmation);
          setError(
            data.message
              || "Counts changed since this dialog opened. Review the updated summary and confirm again.",
          );
          return;
        }
        setError(data.message || data.error || "Close and archive failed");
        return;
      }
      setCloseOpen(false);
      setReason("");
      onChanged?.();
    } catch (e) {
      const data = e?.response?.data || {};
      if (data.error === "close_confirmation_stale" && data.confirmation) {
        setCloseConfirmation(data.confirmation);
        setError(
          data.message
            || "Counts changed since this dialog opened. Review the updated summary and confirm again.",
        );
      } else {
        setError(data.message || data.error || e?.message || "Close and archive failed");
      }
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
              Close Batch
            </Button>
          )}
        </Stack>
      </Stack>

      <Dialog open={closeOpen} onClose={() => !busy && setCloseOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Close and archive · {selectedDateEt}</DialogTitle>
        <DialogContent dividers>
          {error ? (
            <Alert severity="error" sx={{ mb: 1 }} onClose={() => setError("")}>
              {error}
            </Alert>
          ) : null}
          <Alert severity="info" sx={{ mb: 1.25 }}>
            Close and archive this day? Unfinished orders become Unfinished at Close.
            The next day starts only from that day&apos;s Rinse scrapes — nothing is carried over.
          </Alert>
          <Box sx={{ mt: 0.5, p: 1.25, bgcolor: "#f8fafc", borderRadius: 1 }}>
            <Typography variant="subtitle2" fontWeight={800} sx={{ mb: 0.75 }}>
              Confirmation summary
            </Typography>
            <Stack spacing={0.5}>
              <Stack direction="row" justifyContent="space-between">
                <Typography variant="body2">Completed</Typography>
                <Typography variant="body2" fontWeight={800}>
                  {confirmation.completed ?? 0}
                </Typography>
              </Stack>
              <Stack direction="row" justifyContent="space-between">
                <Typography variant="body2">Unfinished</Typography>
                <Typography variant="body2" fontWeight={800}>
                  {confirmation.unfinished ?? 0}
                </Typography>
              </Stack>
            </Stack>
            <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: "block" }}>
              Pending and Review Required become Unfinished at Close. Completed stays Completed.
              This day will be frozen; tomorrow is not seeded from these rows.
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
            {busy ? "Closing…" : "Close and archive this day"}
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
