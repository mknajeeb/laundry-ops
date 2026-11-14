import { useEffect, useMemo, useState } from "react";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Autocomplete,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { fmtHours, fmtLbs, fmtRate, recordedDay } from "./performanceFormat";

export default function SupervisorAdjustmentDialog({
  open,
  onClose,
  dateEt,
  busy,
  initial,
  employees = [],
  onSave,
}) {
  const options = useMemo(() => {
    const byId = new Map();
    for (const employee of employees || []) {
      const name = String(employee?.employee || employee?.employee_name || "").trim();
      const userId = employee?.user_id ?? employee?.employee_user_id;
      if (!name || userId == null || userId === "") continue;
      byId.set(String(userId), {
        userId: Number(userId),
        name,
        recorded: recordedDay(employee),
      });
    }
    return [...byId.values()].sort((a, b) => a.name.localeCompare(b.name));
  }, [employees]);

  const [employee, setEmployee] = useState(null);
  const [approvedRate, setApprovedRate] = useState("");
  const [reason, setReason] = useState("");
  const [targetSessionId, setTargetSessionId] = useState("");
  const [bagIds, setBagIds] = useState("");
  const [rawOrders, setRawOrders] = useState("");
  const [rawLbs, setRawLbs] = useState("");
  const [rawHours, setRawHours] = useState("");
  const [correctedOrders, setCorrectedOrders] = useState("");
  const [correctedLbs, setCorrectedLbs] = useState("");
  const [correctedHours, setCorrectedHours] = useState("");
  const [notes, setNotes] = useState("");

  useEffect(() => {
    if (!open) return;
    const userId = initial?.user_id ?? initial?.employee_user_id;
    const name = initial?.employee || initial?.employee_name || "";
    const match =
      options.find((option) => userId != null && option.userId === Number(userId)) ||
      options.find((option) => name && option.name === name) ||
      null;
    setEmployee(match);
    setApprovedRate(
      initial?.approved_lbs_per_hour != null ? String(initial.approved_lbs_per_hour) : ""
    );
    setReason(initial?.reason || "");
    setTargetSessionId(initial?.target_session_id || "");
    setBagIds("");
    setRawOrders("");
    setRawLbs("");
    setRawHours("");
    setCorrectedOrders("");
    setCorrectedLbs("");
    setCorrectedHours("");
    setNotes(initial?.notes || "");
  }, [open, initial, options]);

  const recorded = employee?.recorded || (initial ? recordedDay(initial) : null);
  const proposed = approvedRate === "" ? null : Number(approvedRate);
  const num = (value) => (value === "" ? null : Number(value));
  const canSave =
    !busy &&
    employee?.userId != null &&
    reason.trim() &&
    proposed != null &&
    !Number.isNaN(proposed);

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} fullWidth maxWidth="sm">
      <DialogTitle>Adjust performance</DialogTitle>
      <DialogContent>
        <Stack spacing={1.25} sx={{ mt: 0.5 }}>
          <Typography variant="body2" color="text.secondary">
            {dateEt || "Selected date"}. Recorded folding stays unchanged. This saves an
            approved speed and a reason. It does not create bags, weights, hours, or sessions.
          </Typography>
          <Autocomplete
            options={options}
            value={employee}
            onChange={(_event, value) => setEmployee(value)}
            getOptionLabel={(option) => option?.name || ""}
            isOptionEqualToValue={(option, value) => option.userId === value.userId}
            renderInput={(params) => (
              <TextField {...params} label="Employee" size="small" required />
            )}
          />
          <Typography variant="body2">
            Recorded combined day:{" "}
            {recorded
              ? `${recorded.bags} bags · ${fmtLbs(recorded.pounds, { compact: true })} · ${fmtHours(
                  recorded.hours
                )} · ${fmtRate(recorded.rate)} lb/hr`
              : "Select an employee"}
          </Typography>
          <TextField
            label="Approved folding speed (lb/hr)"
            value={approvedRate}
            onChange={(e) => setApprovedRate(e.target.value)}
            size="small"
            required
            type="number"
            inputProps={{ min: 0, step: 0.1, "aria-label": "Approved folding speed" }}
            helperText={
              proposed != null && !Number.isNaN(proposed)
                ? `Proposed approved speed ${fmtRate(proposed)} lb/hr`
                : "Required. This is the speed that will be published."
            }
          />
          <TextField
            label="Reason for adjustment"
            required
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            size="small"
          />
          <Accordion disableGutters elevation={0} sx={{ border: "1px solid", borderColor: "divider" }}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="body2">Advanced</Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Stack spacing={1.25}>
                <TextField
                  label="Existing session ID"
                  value={targetSessionId}
                  onChange={(e) => setTargetSessionId(e.target.value)}
                  size="small"
                />
                <TextField
                  label="Bag attribution"
                  value={bagIds}
                  onChange={(e) => setBagIds(e.target.value)}
                  size="small"
                  helperText="Optional. Comma-separated bag IDs. Each bag is credited once per processing cycle."
                />
                <Stack direction="row" spacing={1}>
                  <TextField label="Raw bags" value={rawOrders} onChange={(e) => setRawOrders(e.target.value)} size="small" />
                  <TextField label="Raw pounds" value={rawLbs} onChange={(e) => setRawLbs(e.target.value)} size="small" />
                  <TextField label="Raw hours" value={rawHours} onChange={(e) => setRawHours(e.target.value)} size="small" />
                </Stack>
                <Stack direction="row" spacing={1}>
                  <TextField label="Corrected bags" value={correctedOrders} onChange={(e) => setCorrectedOrders(e.target.value)} size="small" />
                  <TextField label="Corrected pounds" value={correctedLbs} onChange={(e) => setCorrectedLbs(e.target.value)} size="small" />
                  <TextField label="Corrected hours" value={correctedHours} onChange={(e) => setCorrectedHours(e.target.value)} size="small" />
                </Stack>
                <TextField
                  label="Notes"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  size="small"
                  multiline
                  minRows={2}
                />
              </Stack>
            </AccordionDetails>
          </Accordion>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button
          variant="contained"
          disabled={!canSave}
          onClick={() =>
            onSave({
              date_et: dateEt,
              employee_name: employee.name,
              employee_user_id: employee.userId,
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
              approved_lbs_per_hour: proposed,
              reason: reason.trim(),
              notes: notes.trim() || null,
              adjustment_key: initial?.adjustment_key || null,
            })
          }
        >
          {busy ? "Saving…" : "Save and approve"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
