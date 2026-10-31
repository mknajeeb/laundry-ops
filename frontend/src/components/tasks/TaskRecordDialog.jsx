import { useEffect, useState } from "react";
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

/**
 * Edit times / business date, or soft-void an activity.
 * mode: "edit" | "void" | "add" (add uses parent manual dialog typically)
 */
export default function TaskRecordDialog({
  open,
  mode = "edit",
  activity,
  assignmentLabel,
  employeeName,
  onClose,
  onSubmit,
  busy,
}) {
  const [startedAt, setStartedAt] = useState("");
  const [endedAt, setEndedAt] = useState("");
  const [businessDate, setBusinessDate] = useState("");
  const [reason, setReason] = useState("");
  const [remarks, setRemarks] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setReason("");
    setRemarks("");
    setError("");
    const start = String(activity?.started_at || "").replace("T", " ").slice(0, 16);
    const end = String(activity?.ended_at || "").replace("T", " ").slice(0, 16);
    setStartedAt(start);
    setEndedAt(end);
    setBusinessDate(String(activity?.business_date || "").slice(0, 10));
  }, [open, activity]);

  const title =
    mode === "void"
      ? "Remove from reporting"
      : mode === "add"
        ? "Add activity"
        : "Edit activity times";

  const submit = async () => {
    if (String(reason || "").trim().length < 3) {
      setError("Enter a reason (at least 3 characters).");
      return;
    }
    setError("");
    try {
      await onSubmit({
        mode,
        activity_id: activity?.id,
        started_at: startedAt ? `${startedAt}:00` : undefined,
        ended_at: endedAt ? `${endedAt}:00` : undefined,
        business_date: businessDate || undefined,
        reason: reason.trim(),
        remarks: remarks.trim() || undefined,
      });
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Save failed");
    }
  };

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} fullWidth maxWidth="sm">
      <DialogTitle sx={{ fontWeight: 800, color: VEEWASH_DASHBOARD.wfCharcoal }}>
        {title}
      </DialogTitle>
      <DialogContent>
        <Stack spacing={1.5} sx={{ pt: 0.5 }}>
          <Typography variant="body2" color="text.secondary">
            {assignmentLabel || "Assignment"}
            {employeeName ? ` · ${employeeName}` : ""}
            {activity?.id ? ` · #${activity.id}` : ""}
          </Typography>
          {mode !== "void" ? (
            <>
              <TextField
                label="Start (ET)"
                type="datetime-local"
                size="small"
                value={startedAt}
                onChange={(e) => setStartedAt(e.target.value)}
                InputLabelProps={{ shrink: true }}
                fullWidth
              />
              <TextField
                label="End (ET)"
                type="datetime-local"
                size="small"
                value={endedAt}
                onChange={(e) => setEndedAt(e.target.value)}
                InputLabelProps={{ shrink: true }}
                fullWidth
              />
              <TextField
                label="Business date"
                type="date"
                size="small"
                value={businessDate}
                onChange={(e) => setBusinessDate(e.target.value)}
                InputLabelProps={{ shrink: true }}
                fullWidth
                helperText="Does not change payroll or attendance punches."
              />
            </>
          ) : (
            <Typography variant="body2">
              This soft-removes the activity from operational reporting. The record and audit
              history are kept. Historical verification approvals are not deleted.
            </Typography>
          )}
          <TextField
            label="Reason (required)"
            size="small"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            fullWidth
            required
            multiline
            minRows={2}
          />
          <TextField
            label="Notes (optional)"
            size="small"
            value={remarks}
            onChange={(e) => setRemarks(e.target.value)}
            fullWidth
            multiline
            minRows={2}
          />
          {error ? (
            <Typography variant="body2" color="error">
              {error}
            </Typography>
          ) : null}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button
          variant="contained"
          onClick={submit}
          disabled={busy}
          color={mode === "void" ? "error" : "primary"}
          sx={
            mode === "void"
              ? undefined
              : {
                  bgcolor: VEEWASH_DASHBOARD.primaryBlue,
                  "&:hover": { bgcolor: VEEWASH_DASHBOARD.primaryBlueDark },
                }
          }
        >
          {mode === "void" ? "Remove" : "Save"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
