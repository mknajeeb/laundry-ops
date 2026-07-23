import { useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  Checkbox,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { closeVeewashStep1Day, reopenVeewashStep1Day } from "../../api";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

const CHECKLIST_ITEMS = [
  ["workload_reconciled", "Workload reconciled"],
  ["completed_reviewed", "Completed reviewed"],
  ["pending_confirmed", "Pending confirmed"],
  ["review_required_cleared", "Review Required cleared"],
  ["wf_zero_weight_resolved", "WF zero/post-weight issues resolved"],
  ["completed_without_entry_resolved", "Completed-without-entry issues resolved"],
  ["disappeared_reviewed", "Disappeared bags reviewed"],
  ["bulk_workitems_reviewed", "Bulk Workitems Reviewed"],
];

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
}) {
  const day = shiftDay || {};
  const status = String(day.status || "OPEN").toUpperCase();
  const readOnly = Boolean(day.read_only || status === "CLOSED");
  const reviewN = day.review_required_count ?? validation?.review_required_count ?? 0;
  const [closeOpen, setCloseOpen] = useState(false);
  const [reopenOpen, setReopenOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [allowUnresolved, setAllowUnresolved] = useState(false);
  const [checks, setChecks] = useState(() =>
    Object.fromEntries(CHECKLIST_ITEMS.map(([k]) => [k, true])),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const statusColor = useMemo(() => {
    if (status === "CLOSED") return "default";
    if (status === "READY_TO_CLOSE") return "success";
    if (status === "REOPENED") return "warning";
    return "info";
  }, [status]);

  const totals = validation?.totals || {};

  const submitClose = async () => {
    setBusy(true);
    setError("");
    try {
      const res = await closeVeewashStep1Day({
        date: selectedDateEt,
        reason: reason || undefined,
        allow_unresolved_reviews: allowUnresolved,
        checklist: checks,
      });
      if (!res?.data?.ok) {
        setError(res?.data?.error || "Close failed");
        return;
      }
      setCloseOpen(false);
      setReason("");
      onChanged?.();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Close failed");
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
            <Chip size="small" color={statusColor} label={status.replaceAll("_", " ")} />
            {isToday ? <Chip size="small" variant="outlined" label="Live" /> : null}
            {readOnly ? <Chip size="small" variant="outlined" label="Read-only" /> : null}
          </Stack>
          <Typography variant="caption" color="text.secondary">
            Opened {fmtTs(day.opened_at)} · Last sync {fmtTs(day.last_sync_at)} · Review Required {reviewN}
            {day.closed_by_display_name
              ? ` · Closed by ${day.closed_by_display_name} @ ${fmtTs(day.closed_at)}`
              : ""}
          </Typography>
          {dataFreshness && dataFreshness.status && dataFreshness.status !== "ok" ? (
            <Typography variant="caption" color="warning.main" display="block">
              Scan data freshness: {String(dataFreshness.status).replaceAll("_", " ")}
              {dataFreshness.stale_chronology_bag_count
                ? ` · ${dataFreshness.stale_chronology_bag_count} bag(s) behind portal last-seen`
                : ""}
              {!dataFreshness.trust_pending_from_missing_completion
                ? " · Pending not trusted from missing completion"
                : ""}
            </Typography>
          ) : null}
        </Stack>
        <Stack direction="row" spacing={1}>
          {readOnly ? (
            <Button size="small" variant="outlined" onClick={() => setReopenOpen(true)}>
              Reopen Shift
            </Button>
          ) : (
            <Button
              size="small"
              variant="contained"
              onClick={() => setCloseOpen(true)}
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
          <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 0.75 }}>
            Checklist
          </Typography>
          <Stack>
            {CHECKLIST_ITEMS.map(([key, label]) => (
              <FormControlLabel
                key={key}
                control={
                  <Checkbox
                    checked={Boolean(checks[key])}
                    onChange={(e) => setChecks((c) => ({ ...c, [key]: e.target.checked }))}
                    size="small"
                  />
                }
                label={<Typography variant="body2">{label}</Typography>}
              />
            ))}
          </Stack>
          <Box sx={{ mt: 1.5, p: 1, bgcolor: "#f8fafc", borderRadius: 1 }}>
            <Typography variant="caption" display="block" fontWeight={700}>
              Final totals
            </Typography>
            <Typography variant="caption" display="block">
              TOTAL Active {totals.active ?? "—"} · Completed {totals.completed ?? "—"} · Pending{" "}
              {totals.pending ?? "—"} · Review {totals.review_required ?? reviewN}
            </Typography>
            <Typography variant="caption" display="block">
              WF Total {totals.wf?.total ?? "—"} / Done {totals.wf?.completed ?? "—"} / Pending{" "}
              {totals.wf?.pending ?? "—"} / Review {totals.wf?.review_required ?? "—"}
            </Typography>
            <Typography variant="caption" display="block">
              HD Available {totals.hd?.total ?? "—"} / Recorded {totals.hd?.completed ?? "—"} / Missing{" "}
              {totals.hd?.pending ?? "—"} / Review {totals.hd?.review_required ?? "—"}
            </Typography>
          </Box>
          {reviewN > 0 ? (
            <FormControlLabel
              sx={{ mt: 1 }}
              control={
                <Checkbox
                  checked={allowUnresolved}
                  onChange={(e) => setAllowUnresolved(e.target.checked)}
                  size="small"
                />
              }
              label={
                <Typography variant="body2">
                  Close with unresolved reviews ({reviewN}) — requires reason
                </Typography>
              }
            />
          ) : null}
          <TextField
            sx={{ mt: 1.25 }}
            fullWidth
            size="small"
            label={allowUnresolved ? "Override reason *" : "Close note (optional)"}
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
          <Button variant="contained" onClick={submitClose} disabled={busy}>
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
