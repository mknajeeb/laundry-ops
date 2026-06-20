import { Box, Button, Chip, Paper, Stack, Typography } from "@mui/material";
import PayrollBatchSummaryCard from "./PayrollBatchSummaryCard";
import { normPayPeriodYmd } from "../payroll/payPeriodOptions";
import { displayStatusLabel, displayStatusColor } from "../payroll/payrollBatchStatus";

export default function PayrollDashboard({
  payPeriodStart,
  payPeriodEnd,
  batches = [],
  onPrimaryAction,
  onOpenBatches,
  primaryLoading = false,
}) {
  const ps = normPayPeriodYmd(payPeriodStart);
  const pe = normPayPeriodYmd(payPeriodEnd);
  const periodBatches = batches.filter(
    (b) =>
      normPayPeriodYmd(b.pay_period_start) === ps && normPayPeriodYmd(b.pay_period_end) === pe,
  );

  const primaryBatch =
    periodBatches.find((b) => b.payroll_display?.display_status !== "paid") ||
    periodBatches[0] ||
    null;

  const periodLabel =
    payPeriodStart && payPeriodEnd ? `${payPeriodStart} – ${payPeriodEnd}` : "Current pay period";

  return (
    <Paper sx={{ p: 1.5, mb: 2 }}>
      <Stack
        direction={{ xs: "column", sm: "row" }}
        justifyContent="space-between"
        alignItems={{ xs: "stretch", sm: "center" }}
        spacing={1}
        sx={{ mb: 1.5 }}
      >
        <Box>
          <Typography variant="subtitle1" fontWeight={700}>Current Payroll Period</Typography>
          <Typography variant="body2" color="text.secondary">{periodLabel}</Typography>
        </Box>
        {onOpenBatches ? (
          <Button size="small" variant="text" onClick={onOpenBatches}>
            All batches
          </Button>
        ) : null}
      </Stack>

      {primaryBatch ? (
        <PayrollBatchSummaryCard
          batch={primaryBatch}
          onPrimaryAction={onPrimaryAction}
          primaryLoading={primaryLoading}
          compact
        />
      ) : (
        <Box sx={{ py: 1 }}>
          <Chip size="small" label="Draft" color={displayStatusColor({})} sx={{ mb: 1 }} />
          <Typography variant="body2" color="text.secondary">
            No payout batch for this period. Create one on Payout Batches after approving time.
          </Typography>
          {onOpenBatches ? (
            <Button size="small" sx={{ mt: 1 }} onClick={onOpenBatches}>
              Open Payout Batches
            </Button>
          ) : null}
        </Box>
      )}

      {periodBatches.length > 1 ? (
        <Stack direction="row" flexWrap="wrap" gap={0.5} sx={{ mt: 1.5 }}>
          {periodBatches.map((b) => (
            <Chip
              key={b.id}
              size="small"
              variant="outlined"
              label={`${b.worker_category_label || b.worker_category}: ${displayStatusLabel(b)}`}
            />
          ))}
        </Stack>
      ) : null}
    </Paper>
  );
}
