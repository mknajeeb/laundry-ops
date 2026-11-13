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

export default function SupervisorAdjustmentDialog({
  open,
  onClose,
  dateEt,
  busy,
  initial,
  onSave,
}) {
  const [employeeName, setEmployeeName] = useState("");
  const [employeeUserId, setEmployeeUserId] = useState("");
  const [targetSessionId, setTargetSessionId] = useState("");
  const [bagIds, setBagIds] = useState("");
  const [rawOrders, setRawOrders] = useState("");
  const [rawLbs, setRawLbs] = useState("");
  const [rawHours, setRawHours] = useState("");
  const [correctedOrders, setCorrectedOrders] = useState("");
  const [correctedLbs, setCorrectedLbs] = useState("");
  const [correctedHours, setCorrectedHours] = useState("");
  const [approvedRate, setApprovedRate] = useState("");
  const [reason, setReason] = useState("");
  const [notes, setNotes] = useState("");

  useEffect(() => {
    if (!open) return;
    setEmployeeName(initial?.employee_name || initial?.employee || "");
    setEmployeeUserId(initial?.employee_user_id != null ? String(initial.employee_user_id) : "");
    setTargetSessionId(initial?.target_session_id || "");
    setBagIds("");
    setRawOrders(initial?.raw_orders != null ? String(initial.raw_orders) : "");
    setRawLbs(initial?.raw_lbs != null ? String(initial.raw_lbs) : "");
    setRawHours(initial?.raw_hours != null ? String(initial.raw_hours) : "");
    setCorrectedOrders(initial?.corrected_orders != null ? String(initial.corrected_orders) : "");
    setCorrectedLbs(initial?.corrected_lbs != null ? String(initial.corrected_lbs) : "");
    setCorrectedHours(initial?.corrected_hours != null ? String(initial.corrected_hours) : "");
    setApprovedRate(
      initial?.approved_lbs_per_hour != null ? String(initial.approved_lbs_per_hour) : ""
    );
    setReason(initial?.reason || "");
    setNotes(initial?.notes || "");
  }, [open, initial]);

  const num = (value) => (value === "" ? null : Number(value));

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} fullWidth maxWidth="sm">
      <DialogTitle>Supervisor performance adjustment</DialogTitle>
      <DialogContent>
        <Stack spacing={1.25} sx={{ mt: 0.5 }}>
          <Typography variant="body2" color="text.secondary">
            {dateEt}. Raw figures stay the recorded evidence. Corrected and approved
            figures are stored separately and do not rewrite scans, shift sessions, or payroll.
            A reason is required, including when the approved score is below target.
          </Typography>
          <TextField label="Employee name" value={employeeName} onChange={(e) => setEmployeeName(e.target.value)} size="small" />
          <TextField label="Employee user id" value={employeeUserId} onChange={(e) => setEmployeeUserId(e.target.value)} size="small" />
          <TextField label="Existing session id (optional)" value={targetSessionId} onChange={(e) => setTargetSessionId(e.target.value)} size="small" />
          <TextField
            label="Bag ids to attribute"
            value={bagIds}
            onChange={(e) => setBagIds(e.target.value)}
            size="small"
            helperText="Comma-separated. Each bag is credited once per processing cycle."
          />
          <Stack direction="row" spacing={1}>
            <TextField label="Raw bags" value={rawOrders} onChange={(e) => setRawOrders(e.target.value)} size="small" />
            <TextField label="Raw lb" value={rawLbs} onChange={(e) => setRawLbs(e.target.value)} size="small" />
            <TextField label="Raw hours" value={rawHours} onChange={(e) => setRawHours(e.target.value)} size="small" />
          </Stack>
          <Stack direction="row" spacing={1}>
            <TextField label="Corrected bags" value={correctedOrders} onChange={(e) => setCorrectedOrders(e.target.value)} size="small" />
            <TextField label="Corrected lb" value={correctedLbs} onChange={(e) => setCorrectedLbs(e.target.value)} size="small" />
            <TextField label="Corrected hours" value={correctedHours} onChange={(e) => setCorrectedHours(e.target.value)} size="small" />
          </Stack>
          <TextField
            label="Approved lb/hr"
            value={approvedRate}
            onChange={(e) => setApprovedRate(e.target.value)}
            size="small"
            helperText="May be below the folding target when the reason supports it."
          />
          <TextField label="Reason" required value={reason} onChange={(e) => setReason(e.target.value)} size="small" />
          <TextField label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} size="small" multiline minRows={2} />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button
          variant="contained"
          disabled={busy || !reason.trim() || !employeeName.trim() || !employeeUserId.trim()}
          onClick={() =>
            onSave({
              date_et: dateEt,
              employee_name: employeeName.trim(),
              employee_user_id: Number(employeeUserId),
              target_session_id: targetSessionId.trim() || null,
              bags: bagIds
                .split(",")
                .map((id) => id.trim())
                .filter(Boolean)
                .map((bag_id) => ({ bag_id, replace_existing: true })),
              raw_orders: num(rawOrders),
              raw_lbs: num(rawLbs),
              raw_hours: num(rawHours),
              corrected_orders: num(correctedOrders),
              corrected_lbs: num(correctedLbs),
              corrected_hours: num(correctedHours),
              approved_lbs_per_hour: num(approvedRate),
              reason: reason.trim(),
              notes: notes.trim() || null,
              adjustment_key: initial?.adjustment_key || null,
            })
          }
        >
          {busy ? "Saving…" : "Save adjustment"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
