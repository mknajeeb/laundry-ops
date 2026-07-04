import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import {
  getJobTrackingUserForceCheckoutWaiver,
  postJobTrackingAllowContinuation,
  postJobTrackingOverrideForceCheckoutTime,
  postJobTrackingUserForceCheckoutWaiver,
  postJobTrackingWaiveSessionForceCheckout,
} from "../api";
import { PayrollDateTimeField } from "./PayrollDateTimeField";

function toDatetimeLocal(val) {
  if (!val) return "";
  return String(val).trim().replace(" ", "T").slice(0, 16);
}

export default function JobTrackingAdminDialog({ open, onClose, record, onSaved }) {
  const [waived, setWaived] = useState(!!record?.force_checkout_waived);
  const [forceCheckoutAt, setForceCheckoutAt] = useState(
    toDatetimeLocal(record?.force_checkout_at || record?.scheduled_end_at),
  );
  const [remarks, setRemarks] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [employeeWaiver, setEmployeeWaiver] = useState(false);

  useEffect(() => {
    if (!open || !record?.user_id) return;
    getJobTrackingUserForceCheckoutWaiver(record.user_id)
      .then((res) => setEmployeeWaiver(!!res.data?.force_checkout_waiver))
      .catch(() => setEmployeeWaiver(false));
  }, [open, record?.user_id]);

  if (!record) return null;

  const run = async (fn) => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await fn();
      setMessage("Saved.");
      onSaved?.();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Action failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={() => !busy && onClose()} fullWidth maxWidth="sm">
      <DialogTitle>Shift task controls</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            Shift #{record.id} — {[record.first_name, record.last_name].filter(Boolean).join(" ")}
          </Typography>
          {error ? <Alert severity="error">{error}</Alert> : null}
          {message ? <Alert severity="success">{message}</Alert> : null}

          <FormControlLabel
            control={
              <Switch
                checked={employeeWaiver}
                onChange={(e) => setEmployeeWaiver(e.target.checked)}
              />
            }
            label="Employee-level force check-out waiver (all shifts)"
          />
          <Button
            variant="outlined"
            disabled={busy || !record.user_id}
            onClick={() =>
              run(() =>
                postJobTrackingUserForceCheckoutWaiver(record.user_id, {
                  waived: employeeWaiver,
                  remarks,
                }),
              )
            }
          >
            Save employee waiver
          </Button>

          <FormControlLabel
            control={<Switch checked={waived} onChange={(e) => setWaived(e.target.checked)} />}
            label="Waive forced check-out for this shift"
          />
          <Button
            variant="outlined"
            disabled={busy}
            onClick={() =>
              run(() =>
                postJobTrackingWaiveSessionForceCheckout(record.id, {
                  waived,
                  remarks,
                }),
              )
            }
          >
            Save shift waiver
          </Button>

          <PayrollDateTimeField
            label="Override force check-out time"
            value={forceCheckoutAt}
            onChange={setForceCheckoutAt}
          />
          <Button
            variant="outlined"
            disabled={busy || !forceCheckoutAt}
            onClick={() =>
              run(() =>
                postJobTrackingOverrideForceCheckoutTime(record.id, {
                  force_checkout_at: forceCheckoutAt.replace("T", " "),
                  remarks,
                }),
              )
            }
          >
            Save force check-out override
          </Button>

          {record.force_checked_out_at || record.was_force_checked_out ? (
            <Button
              variant="contained"
              color="warning"
              disabled={busy}
              onClick={() =>
                run(() =>
                  postJobTrackingAllowContinuation(record.id, { remarks }),
                )
              }
            >
              Allow employee to continue this shift
            </Button>
          ) : null}

          <TextField
            label="Reason / comment (audit trail)"
            value={remarks}
            onChange={(e) => setRemarks(e.target.value)}
            fullWidth
            multiline
            minRows={2}
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>
          Close
        </Button>
      </DialogActions>
    </Dialog>
  );
}
