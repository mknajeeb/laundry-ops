import { Box, Button, Chip, Paper, Stack, Typography } from "@mui/material";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import Tooltip from "@mui/material/Tooltip";
import {
  displayStatusColor,
  displayStatusLabel,
  formatPayrollMoney,
  payrollSummary,
  primaryAction,
} from "../payroll/payrollBatchStatus";

export default function PayrollBatchSummaryCard({
  batch,
  onPrimaryAction,
  primaryLoading = false,
  compact = false,
}) {
  if (!batch) return null;
  const summary = payrollSummary(batch);
  const action = primaryAction(batch);
  const period =
    batch.pay_period_start && batch.pay_period_end
      ? `${batch.pay_period_start} – ${batch.pay_period_end}`
      : null;

  return (
    <Paper variant="outlined" sx={{ p: compact ? 1.25 : 1.5 }}>
      <Stack
        direction={{ xs: "column", md: "row" }}
        justifyContent="space-between"
        alignItems={{ xs: "stretch", md: "center" }}
        spacing={1}
      >
        <Box sx={{ minWidth: 0 }}>
          <Stack direction="row" alignItems="center" spacing={1} flexWrap="wrap" useFlexGap>
            <Typography variant="subtitle1" fontWeight={700} noWrap>
              {batch.batch_name || "Payroll batch"}
            </Typography>
            <Chip
              size="small"
              label={displayStatusLabel(batch)}
              color={displayStatusColor(batch)}
            />
            {period ? (
              <Typography variant="caption" color="text.secondary">
                {period}
                {batch.worker_category_label ? ` · ${batch.worker_category_label}` : ""}
              </Typography>
            ) : null}
          </Stack>
          <Stack
            direction="row"
            flexWrap="wrap"
            useFlexGap
            spacing={2}
            sx={{ mt: 1, "& > *": { minWidth: 88 } }}
          >
            <Box>
              <Typography variant="caption" color="text.secondary">Employees</Typography>
              <Typography variant="body2" fontWeight={600}>{summary.employee_count ?? 0}</Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">Gross</Typography>
              <Typography variant="body2" fontWeight={600}>
                {formatPayrollMoney(summary.gross_payroll)}
              </Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">Tax withheld</Typography>
              <Typography variant="body2" fontWeight={600}>
                {formatPayrollMoney(summary.tax_withheld)}
              </Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">Net payroll</Typography>
              <Typography variant="body2" fontWeight={600}>
                {formatPayrollMoney(summary.net_payroll)}
              </Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">Paid</Typography>
              <Typography variant="body2" fontWeight={600}>
                {formatPayrollMoney(summary.paid_amount)}
              </Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">Outstanding</Typography>
              <Typography variant="body2" fontWeight={600}>
                {formatPayrollMoney(summary.outstanding_amount)}
              </Typography>
            </Box>
          </Stack>
        </Box>
        {action && onPrimaryAction ? (
          <Stack direction="row" alignItems="center" spacing={0.5}>
            <Button
              variant="contained"
              size="small"
              disabled={primaryLoading}
              onClick={() => onPrimaryAction(action.action, batch)}
            >
              {action.label}
            </Button>
            {action.action === "approve_hours" ? (
              <Tooltip title="Locks hours and advances payroll to the next step.">
                <InfoOutlinedIcon fontSize="small" color="action" sx={{ opacity: 0.6 }} />
              </Tooltip>
            ) : null}
          </Stack>
        ) : null}
      </Stack>
    </Paper>
  );
}
