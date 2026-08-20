import { Box, Button, Stack, TextField, Typography } from "@mui/material";
import PlanningDatePicker from "../datetime/PlanningDatePicker";
import MoneyAmountField from "./MoneyAmountField";
import { fmtMoney } from "./revenueFormat";

/**
 * Cash payout form — payout business date required and editable.
 */
export default function CashPayoutForm({
  payoutDate,
  purpose,
  amount,
  note,
  onChange,
  onSubmit,
  onCancel,
  busy,
  labels = {},
}) {
  const canSave =
    Boolean(payoutDate) &&
    Boolean(String(purpose || "").trim()) &&
    amount != null &&
    String(amount).trim() !== "" &&
    Number(amount) > 0;

  return (
    <Stack spacing={1.5}>
      <Typography sx={{ fontSize: 13, color: "#64748b", fontWeight: 600 }}>
        {labels.payoutDateHelp ||
          "Payout Date is the business day this cash-out belongs to — not when you enter it."}
      </Typography>
      <PlanningDatePicker
        label={labels.payoutDate || "Payout Date (required)"}
        value={payoutDate || ""}
        onChange={(v) => onChange?.({ payoutDate: v })}
      />
      <TextField
        label={labels.purpose || "Purpose"}
        value={purpose || ""}
        onChange={(e) => onChange?.({ purpose: e.target.value })}
        fullWidth
        sx={{ "& .MuiInputBase-root": { minHeight: 56 } }}
      />
      <MoneyAmountField
        label={labels.amount || "Amount"}
        value={amount}
        onChange={(v) => onChange?.({ amount: v })}
      />
      <TextField
        label={labels.noteOptional || "Note (optional)"}
        value={note || ""}
        onChange={(e) => onChange?.({ note: e.target.value })}
        fullWidth
        multiline
        minRows={2}
      />
      <Stack direction="row" spacing={1}>
        {onCancel ? (
          <Button fullWidth variant="outlined" disabled={busy} onClick={onCancel} sx={{ textTransform: "none" }}>
            {labels.cancel || "Cancel"}
          </Button>
        ) : null}
        <Button
          fullWidth
          variant="contained"
          disabled={busy || !canSave}
          onClick={onSubmit}
          sx={{ textTransform: "none", fontWeight: 800, minHeight: 52 }}
        >
          {busy ? labels.saving || "Saving…" : labels.save || "Save"}
        </Button>
      </Stack>
    </Stack>
  );
}

export function CashPayoutList({ payouts, onDelete, labels = {} }) {
  if (!payouts?.length) {
    return (
      <Typography sx={{ fontSize: 13, color: "#64748b" }}>
        {labels.noPayouts || "No payouts for this day."}
      </Typography>
    );
  }
  return (
    <Stack spacing={1}>
      {payouts.map((p) => (
        <Box
          key={p.id}
          sx={{
            p: 1.25,
            borderRadius: 2,
            border: "1px solid #e5e7eb",
            bgcolor: "#fff",
            display: "flex",
            justifyContent: "space-between",
            gap: 1,
            alignItems: "center",
          }}
        >
          <Box>
            <Typography sx={{ fontWeight: 800 }}>{p.purpose}</Typography>
            <Typography sx={{ fontSize: 12, color: "#64748b" }}>
              {p.payout_business_date || p.date_et}
              {p.entered_by ? ` · ${p.entered_by}` : ""}
            </Typography>
          </Box>
          <Box sx={{ textAlign: "right" }}>
            <Typography sx={{ fontWeight: 900, color: "#b91c1c" }}>{fmtMoney(p.amount)}</Typography>
            {onDelete ? (
              <Button size="small" color="error" onClick={() => onDelete(p.id)} sx={{ textTransform: "none" }}>
                {labels.delete || "Delete"}
              </Button>
            ) : null}
          </Box>
        </Box>
      ))}
    </Stack>
  );
}
