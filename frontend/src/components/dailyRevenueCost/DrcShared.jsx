import { Box, InputAdornment, Paper, Stack, TextField, Typography } from "@mui/material";
import { DRC_INPUT_SX, formatCurrency, formatPercent } from "../../utils/dailyRevenueCostHelpers";

export function SummaryRow({ label, value, emphasize, negative }) {
  return (
    <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ py: 0.75 }}>
      <Typography variant="body2" color={emphasize ? "text.primary" : "text.secondary"} fontWeight={emphasize ? 700 : 400}>
        {label}
      </Typography>
      <Typography
        variant="body2"
        fontWeight={emphasize ? 700 : 500}
        color={negative && Number(value) < 0 ? "error.main" : emphasize ? "primary.main" : "text.primary"}
      >
        {typeof value === "string" && value.endsWith("%") ? value : formatCurrency(value)}
      </Typography>
    </Stack>
  );
}

export function DailySummaryCard({ summary, title = "Daily Summary" }) {
  if (!summary) return null;
  return (
    <Paper elevation={0} sx={{ borderRadius: 2, p: 2, border: "1px solid", borderColor: "divider", bgcolor: "grey.50" }}>
      <Typography variant="subtitle1" fontWeight={700} gutterBottom>
        {title}
      </Typography>
      <SummaryRow label="Total Revenue" value={summary.total_revenue} />
      <SummaryRow label="Total Payroll" value={summary.payroll_total} />
      <SummaryRow label="Payroll Taxes" value={summary.payroll_tax_amount} />
      <SummaryRow label="Total Labor Cost" value={summary.labor_cost} />
      <SummaryRow label="Est. Operating Cost" value={summary.operating_cost} />
      {summary.fixed_cost != null ? <SummaryRow label="Fixed Costs" value={summary.fixed_cost} /> : null}
      {summary.variable_cost != null ? <SummaryRow label="Variable Costs" value={summary.variable_cost} /> : null}
      <Box sx={{ borderTop: "1px solid", borderColor: "divider", my: 1 }} />
      <SummaryRow label="Total Cost" value={summary.total_cost} emphasize />
      <SummaryRow label="Estimated Profit" value={summary.estimated_profit} emphasize negative />
      <SummaryRow label="Profit Margin" value={formatPercent(summary.profit_margin_pct)} emphasize />
    </Paper>
  );
}

export function SectionCard({ title, subtitle, children }) {
  return (
    <Paper elevation={0} sx={{ borderRadius: 2, p: { xs: 2, sm: 2.5 }, mb: 2, border: "1px solid", borderColor: "divider" }}>
      <Typography variant="h6" fontWeight={700} sx={{ fontSize: { xs: "1.05rem", sm: "1.15rem" }, mb: subtitle ? 0.5 : 1.5 }}>
        {title}
      </Typography>
      {subtitle ? (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          {subtitle}
        </Typography>
      ) : null}
      {children}
    </Paper>
  );
}

export function CurrencyField({ label, value, onChange, ...rest }) {
  return (
    <TextField
      label={label}
      value={value}
      onChange={onChange}
      type="number"
      inputMode="decimal"
      fullWidth
      size="medium"
      InputProps={{ startAdornment: <InputAdornment position="start">$</InputAdornment> }}
      sx={DRC_INPUT_SX}
      {...rest}
    />
  );
}

export function NumberField({ label, value, onChange, ...rest }) {
  return (
    <TextField
      label={label}
      value={value}
      onChange={onChange}
      type="number"
      inputMode="decimal"
      fullWidth
      size="medium"
      sx={DRC_INPUT_SX}
      {...rest}
    />
  );
}
