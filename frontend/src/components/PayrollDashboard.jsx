import { useEffect, useMemo, useState } from "react";
import { Box, Button, Chip, Paper, Stack, Typography } from "@mui/material";
import PayrollBatchSummaryCard from "./PayrollBatchSummaryCard";
import {
  defaultDashboardBatchId,
  formatDashboardBatchChip,
  periodBatchesForDashboard,
  resolveDashboardBatch,
} from "../payroll/payrollDashboardNav";
import { displayStatusColor } from "../payroll/payrollBatchStatus";

export default function PayrollDashboard({
  payPeriodStart,
  payPeriodEnd,
  batches = [],
  onPrimaryAction,
  onOpenBatches,
  primaryLoading = false,
}) {
  const periodBatches = useMemo(
    () => periodBatchesForDashboard(batches, payPeriodStart, payPeriodEnd),
    [batches, payPeriodStart, payPeriodEnd],
  );
  const periodBatchIds = periodBatches.map((b) => b.id).join(",");
  const [selectedBatchId, setSelectedBatchId] = useState(null);

  useEffect(() => {
    setSelectedBatchId((prev) => {
      if (prev != null && periodBatches.some((b) => String(b.id) === String(prev))) {
        return prev;
      }
      return defaultDashboardBatchId(periodBatches);
    });
    // periodBatchIds captures membership; periodBatches is derived from the same inputs.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- avoid re-running on array identity
  }, [payPeriodStart, payPeriodEnd, periodBatchIds]);

  const selectedBatch =
    resolveDashboardBatch(periodBatches, selectedBatchId) ||
    resolveDashboardBatch(periodBatches, defaultDashboardBatchId(periodBatches));

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

      {selectedBatch ? (
        <PayrollBatchSummaryCard
          batch={selectedBatch}
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
          {periodBatches.map((b) => {
            const active = String(b.id) === String(selectedBatchId);
            return (
              <Chip
                key={b.id}
                size="small"
                color={active ? "primary" : "default"}
                variant={active ? "filled" : "outlined"}
                label={formatDashboardBatchChip(b)}
                onClick={() => setSelectedBatchId(b.id)}
              />
            );
          })}
        </Stack>
      ) : null}
    </Paper>
  );
}
