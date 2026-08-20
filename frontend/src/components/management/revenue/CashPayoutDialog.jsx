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
import PlanningDatePicker from "../../datetime/PlanningDatePicker";
import { VEEWASH_DASHBOARD } from "../../../theme/veewashDashboard";
import { parseMoneyInput } from "./revenueFormat";

export default function CashPayoutDialog({
  open,
  busy,
  payoutDate,
  purpose,
  amount,
  note,
  onChange,
  onClose,
  onSubmit,
}) {
  const canSave = Boolean(payoutDate) && Boolean(String(purpose || "").trim()) && parseMoneyInput(amount) != null && parseMoneyInput(amount) > 0;

  return (
    <Dialog open={open} onClose={() => !busy && onClose?.()} fullWidth maxWidth="xs">
      <DialogTitle sx={{ fontWeight: 800 }}>Cash Paid Out</DialogTitle>
      <DialogContent>
        <Stack spacing={1.5} sx={{ pt: 0.5 }}>
          <Typography sx={{ fontSize: 12, color: "#64748b" }}>
            Payout Date is the business day this cash-out belongs to — not when you enter it.
          </Typography>
          <PlanningDatePicker
            value={payoutDate}
            onChange={(v) => onChange?.({ payoutDate: v })}
            label="Payout Date (required)"
          />
          <TextField
            label="Purpose"
            value={purpose}
            onChange={(e) => onChange?.({ purpose: e.target.value })}
            fullWidth
            required
          />
          <TextField
            label="Amount"
            value={amount}
            onChange={(e) => onChange?.({ amount: e.target.value })}
            fullWidth
            inputMode="decimal"
            required
            placeholder=""
          />
          <TextField
            label="Note (optional)"
            value={note}
            onChange={(e) => onChange?.({ note: e.target.value })}
            fullWidth
            multiline
            minRows={2}
          />
          <Typography sx={{ fontSize: 12, color: "#94a3b8" }}>Entered by is recorded automatically.</Typography>
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 2, pb: 2 }}>
        <Button onClick={onClose} disabled={busy} sx={{ textTransform: "none" }}>
          Cancel
        </Button>
        <Button
          variant="contained"
          onClick={onSubmit}
          disabled={busy || !canSave}
          sx={{
            textTransform: "none",
            fontWeight: 800,
            bgcolor: VEEWASH_DASHBOARD.primaryBlue,
            "&:hover": { bgcolor: VEEWASH_DASHBOARD.primaryBlueDark },
          }}
        >
          {busy ? "Saving…" : "Save Payout"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
