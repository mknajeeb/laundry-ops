import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { getPayrollEmployeePto, postPayrollEmployeePtoAdjust } from "../api";

/** W-2 sick leave balance / manual adjustment (internal tracking only). */
export default function PayrollPtoSection({ userId, canEdit }) {
  const [pto, setPto] = useState(null);
  const [error, setError] = useState("");
  const [adjustOpen, setAdjustOpen] = useState(false);
  const [hoursDelta, setHoursDelta] = useState("");
  const [adminNote, setAdminNote] = useState("");

  const load = useCallback(async () => {
    if (!userId) return;
    setError("");
    try {
      const res = await getPayrollEmployeePto(userId);
      setPto(res.data || null);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Could not load sick leave");
    }
  }, [userId]);

  useEffect(() => {
    load();
  }, [load]);

  const submitAdjust = async () => {
    if (!adminNote.trim()) {
      setError("Note required for manual sick leave adjustment");
      return;
    }
    try {
      await postPayrollEmployeePtoAdjust(userId, {
        hours_delta: Number(hoursDelta || 0),
        admin_note: adminNote.trim(),
      });
      setAdjustOpen(false);
      setHoursDelta("");
      setAdminNote("");
      await load();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Adjustment failed");
    }
  };

  if (!userId) return null;

  return (
    <Stack spacing={1.5} sx={{ mt: 2 }}>
      <Typography variant="subtitle2">Paid sick leave (W-2)</Typography>
      <Typography variant="caption" color="text.secondary" display="block">
        {pto?.policy_label || "NYC/NY Paid Sick Leave"} · Accrual:{" "}
        {pto?.accrual_rate_label || "1 hour per 30 hours worked"} · Annual cap:{" "}
        {pto?.annual_cap_hours ?? "40"} hours
      </Typography>
      {pto?.disclaimer ? (
        <Alert severity="info" variant="outlined">
          {pto.disclaimer}
        </Alert>
      ) : (
        <Alert severity="info" variant="outlined">
          Estimated/internal payroll tracking — verify with accountant/payroll provider.
        </Alert>
      )}
      {error ? (
        <Alert severity="error" onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
        <Typography variant="body2">
          <strong>Balance:</strong> {Number(pto?.balance_hours ?? 0).toFixed(2)} hrs
        </Typography>
        <Typography variant="body2">
          <strong>YTD accrued:</strong> {Number(pto?.ytd_accrued_hours ?? 0).toFixed(2)} hrs
        </Typography>
        <Typography variant="body2">
          <strong>YTD used:</strong> {Number(pto?.ytd_used_hours ?? 0).toFixed(2)} hrs
        </Typography>
      </Stack>
      {canEdit ? (
        <Button size="small" variant="outlined" onClick={() => setAdjustOpen(true)}>
          Manual adjustment
        </Button>
      ) : null}
      <Dialog open={adjustOpen} onClose={() => setAdjustOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Adjust sick leave balance</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label="Hours delta (+/-)"
              type="number"
              size="small"
              value={hoursDelta}
              onChange={(e) => setHoursDelta(e.target.value)}
            />
            <TextField
              label="Admin note (required)"
              size="small"
              multiline
              minRows={2}
              value={adminNote}
              onChange={(e) => setAdminNote(e.target.value)}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAdjustOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={submitAdjust}>
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
