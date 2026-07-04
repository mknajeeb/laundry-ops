import {
  Box,
  Button,
  Checkbox,
  Collapse,
  FormControlLabel,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { VEEWASH_BRAND } from "../theme/veewashBrand";
import {
  PAYROLL_REGISTER_EMPLOYEE_TAX_FIELDS,
  PAYROLL_REGISTER_EMPLOYER_TAX_FIELDS,
  sumEmployeeRegisterTaxes,
} from "../payroll/payrollRegisterTaxFields";

const PAYMENT_METHODS = [
  { value: "direct_deposit", label: "Direct Deposit" },
  { value: "check", label: "Check" },
  { value: "cash", label: "Cash" },
  { value: "zelle", label: "Zelle" },
  { value: "other", label: "Other" },
];

function num(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function money(v) {
  return `$${num(v).toFixed(2)}`;
}

export default function FinancePayrollFinalizeRow({
  ln,
  draft,
  totals,
  method,
  isReceiptMode,
  advancedOpen,
  onToggleAdvanced,
  onUpdateDraft,
  onUpdateLineFlag,
}) {
  const totalTax = sumEmployeeRegisterTaxes(draft.employee_deductions);

  return (
    <Stack spacing={1.5}>
      {!isReceiptMode ? (
        <Paper
          variant="outlined"
          sx={{
            p: 1.5,
            borderLeft: `4px solid ${VEEWASH_BRAND.primary}`,
            bgcolor: "rgba(25, 118, 210, 0.04)",
          }}
        >
          <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 0.5 }}>
            Employee taxes (from payroll register)
          </Typography>
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
            Enter amounts from the accountant payroll register after payroll is confirmed.
          </Typography>
          <Stack direction="row" flexWrap="wrap" gap={1}>
            {PAYROLL_REGISTER_EMPLOYEE_TAX_FIELDS.map((f) => (
              <TextField
                key={f.key}
                size="small"
                label={f.label}
                type="number"
                value={draft.employee_deductions?.[f.key] ?? ""}
                onChange={(e) => onUpdateDraft(ln.id, "employee_deductions", f.key, e.target.value)}
                helperText={f.helper}
                sx={{ width: 130 }}
                inputProps={{ style: { fontWeight: 600 } }}
              />
            ))}
            <Box sx={{ ml: 1, pt: 0.5 }}>
              <Typography variant="caption" color="text.secondary">Total withheld</Typography>
              <Typography variant="h6" fontWeight={700}>{money(totalTax)}</Typography>
            </Box>
            <Box sx={{ pt: 0.5 }}>
              <Typography variant="caption" color="text.secondary">Net pay</Typography>
              <Typography variant="h6" fontWeight={700} color="success.main">
                {money(totals.net)}
              </Typography>
            </Box>
          </Stack>
        </Paper>
      ) : null}

      {!isReceiptMode ? (
        <Paper variant="outlined" sx={{ p: 1.5 }}>
          <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
            Employer taxes (from payroll register)
          </Typography>
          <Stack direction="row" flexWrap="wrap" gap={1}>
            {PAYROLL_REGISTER_EMPLOYER_TAX_FIELDS.map((f) => (
              <TextField
                key={f.key}
                size="small"
                label={f.label}
                type="number"
                value={draft.employer_taxes?.[f.key] ?? ""}
                onChange={(e) => onUpdateDraft(ln.id, "employer_taxes", f.key, e.target.value)}
                sx={{ width: 120 }}
              />
            ))}
          </Stack>
        </Paper>
      ) : null}

      <Paper variant="outlined" sx={{ p: 1.5 }}>
        <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
          Payment details
        </Typography>
        <Stack direction="row" flexWrap="wrap" gap={1}>
          <TextField
            size="small"
            select
            label="Method"
            value={method}
            onChange={(e) => onUpdateDraft(ln.id, "payment", "method", e.target.value)}
            SelectProps={{ native: true }}
            sx={{ minWidth: 140 }}
          >
            {PAYMENT_METHODS.map((m) => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </TextField>
          <TextField
            size="small"
            type="date"
            label="Payment date"
            value={draft.payment?.date || ""}
            onChange={(e) => onUpdateDraft(ln.id, "payment", "date", e.target.value)}
            InputLabelProps={{ shrink: true }}
            sx={{ minWidth: 150 }}
          />
          <TextField
            size="small"
            label="Check #"
            value={draft.payment?.check_number || ""}
            onChange={(e) => onUpdateDraft(ln.id, "payment", "check_number", e.target.value)}
          />
          <TextField
            size="small"
            label="Reference"
            value={draft.payment?.reference || ""}
            onChange={(e) => onUpdateDraft(ln.id, "payment", "reference", e.target.value)}
          />
          <TextField
            size="small"
            label="Employee note"
            value={draft.employee_note || ""}
            onChange={(e) => onUpdateLineFlag(ln.id, "employee_note", e.target.value)}
            sx={{ minWidth: 180 }}
          />
        </Stack>
        {method === "cash" ? (
          <Stack direction="row" flexWrap="wrap" gap={1} sx={{ mt: 1 }}>
            <TextField
              size="small"
              type="number"
              label="Cash amount"
              value={draft.payment?.cash_amount ?? ""}
              onChange={(e) => onUpdateDraft(ln.id, "payment", "cash_amount", e.target.value)}
            />
            <TextField
              size="small"
              label="Paid by"
              value={draft.payment?.paid_by || ""}
              onChange={(e) => onUpdateDraft(ln.id, "payment", "paid_by", e.target.value)}
            />
            <TextField
              size="small"
              label="Receipt number"
              value={draft.payment?.receipt_number || ""}
              onChange={(e) => onUpdateDraft(ln.id, "payment", "receipt_number", e.target.value)}
            />
            <TextField
              size="small"
              label="Employee signature"
              value={draft.payment?.employee_signature || ""}
              onChange={(e) => onUpdateDraft(ln.id, "payment", "employee_signature", e.target.value)}
            />
          </Stack>
        ) : null}
      </Paper>

      <Button
        size="small"
        color="inherit"
        onClick={onToggleAdvanced}
        endIcon={
          <ExpandMoreIcon sx={{ transform: advancedOpen ? "rotate(180deg)" : "none", transition: "0.2s" }} />
        }
        sx={{ alignSelf: "flex-start", color: "text.secondary" }}
      >
        {advancedOpen ? "Hide" : "Show"} advanced options
      </Button>

      <Collapse in={advancedOpen}>
        <Stack spacing={1.5}>
          <Paper variant="outlined" sx={{ p: 1.5, bgcolor: "action.hover" }}>
            <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 1 }}>
              Settlement & prior balances
            </Typography>
            <Stack direction="row" flexWrap="wrap" gap={1}>
              <TextField
                size="small"
                type="number"
                label="Withheld this period"
                value={draft.settlement?.withheld_from_payment ?? ""}
                onChange={(e) =>
                  onUpdateDraft(
                    ln.id,
                    "settlement",
                    "withheld_from_payment",
                    e.target.value === "" ? null : e.target.value,
                  )
                }
                disabled={Boolean(draft.settlement?.paid_full_gross_without_withholding)}
                helperText="Actual tax taken from this pay"
                sx={{ minWidth: 150 }}
              />
              <TextField
                size="small"
                type="number"
                label="Catch-up withholding"
                value={draft.settlement?.catch_up_withholding ?? ""}
                onChange={(e) => onUpdateDraft(ln.id, "settlement", "catch_up_withholding", e.target.value)}
                disabled={Boolean(draft.settlement?.paid_full_gross_without_withholding)}
                sx={{ minWidth: 140 }}
              />
              <TextField
                size="small"
                type="number"
                label="Prior tax balance"
                value={draft.settlement?.prior_unpaid_taxes ?? ""}
                onChange={(e) => onUpdateDraft(ln.id, "settlement", "prior_unpaid_taxes", e.target.value)}
                sx={{ minWidth: 140 }}
              />
              <TextField
                size="small"
                type="number"
                label="Prior-period adj."
                value={draft.settlement?.prior_period_adjustment ?? ""}
                onChange={(e) => onUpdateDraft(ln.id, "settlement", "prior_period_adjustment", e.target.value)}
                sx={{ minWidth: 140 }}
              />
              <TextField
                size="small"
                type="number"
                label="Remaining balance"
                value={draft.tax_summary?.remaining_balance ?? ""}
                InputProps={{ readOnly: true }}
                sx={{ minWidth: 140 }}
              />
              <TextField
                size="small"
                type="number"
                label="This period unpaid"
                value={draft.settlement?.tax_balance_owed ?? ""}
                InputProps={{ readOnly: true }}
                sx={{ minWidth: 140 }}
              />
            </Stack>
            <Stack direction="row" flexWrap="wrap" gap={1} sx={{ mt: 1 }}>
              <FormControlLabel
                control={
                  <Checkbox
                    size="small"
                    checked={Boolean(draft.settlement?.paid_full_gross_without_withholding)}
                    onChange={(e) =>
                      onUpdateDraft(ln.id, "settlement", "paid_full_gross_without_withholding", e.target.checked)
                    }
                  />
                }
                label="Paid full gross (no withholding)"
              />
              <FormControlLabel
                control={
                  <Checkbox
                    size="small"
                    checked={Boolean(draft.show_tax_payment_section)}
                    onChange={(e) => onUpdateLineFlag(ln.id, "show_tax_payment_section", e.target.checked)}
                  />
                }
                label="Show tax balance on paystub"
              />
            </Stack>
          </Paper>

        </Stack>
      </Collapse>
    </Stack>
  );
}
