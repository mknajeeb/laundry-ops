import { useMemo } from "react";
import {
  Button,
  FormControl,
  InputLabel,
  ListSubheader,
  MenuItem,
  Select,
  Stack,
  Typography,
} from "@mui/material";
import {
  accountantBatchOptionKey,
  buildPayrollPeriodChoices,
  groupPayPeriodOptionsByYear,
  normPayPeriodYmd,
} from "../payroll/payPeriodOptions";

/**
 * Pay period dropdown — recent weeks by default, optional expand for full history.
 * Merges payout batch periods so accountants see periods with existing batches.
 * Period labels are week identity only (no Paid/Pending/Draft suffix).
 */
export default function PayPeriodSelect({
  weekStartsOn = 0,
  batches = [],
  start,
  end,
  batchId,
  onChange,
  batchStatusLabel,
  analysisAvailableKeys = null,
  expanded = false,
  onExpandedChange,
  minWidth = 280,
  size = "small",
  showExpand = true,
  batchOnly = false,
}) {
  const options = useMemo(
    () =>
      buildPayrollPeriodChoices(weekStartsOn, batches, {
        expanded,
        batchStatusLabel,
        batchOnly,
        analysisAvailableKeys,
      }),
    [weekStartsOn, batches, expanded, batchStatusLabel, batchOnly, analysisAvailableKeys],
  );

  const groups = useMemo(() => groupPayPeriodOptionsByYear(options), [options]);

  const selectedKey = batchOnly
    ? batchId != null && batchId !== ""
      ? accountantBatchOptionKey(batchId)
      : ""
    : start && end
      ? `${normPayPeriodYmd(start)}|${normPayPeriodYmd(end)}`
      : "";

  const handleChange = (key) => {
    const opt = options.find((o) => o.key === key);
    if (!opt) return;
    onChange?.({ start: opt.start, end: opt.end, batchId: opt.batchId });
  };

  return (
    <Stack spacing={0.75}>
      <FormControl size={size} sx={{ minWidth }}>
        <InputLabel>{batchOnly ? "Batch" : "Pay period"}</InputLabel>
        <Select
          label={batchOnly ? "Batch" : "Pay period"}
          value={options.some((o) => o.key === selectedKey) ? selectedKey : ""}
          onChange={(e) => handleChange(e.target.value)}
        >
          {groups.map((g) => [
            <ListSubheader key={`y-${g.year}`}>{g.year}</ListSubheader>,
            ...g.items.map((o) => (
              <MenuItem key={o.key} value={o.key}>
                {o.label}
              </MenuItem>
            )),
          ])}
        </Select>
      </FormControl>
      {showExpand && !batchOnly ? (
        <Button
          size="small"
          variant="text"
          sx={{ alignSelf: "flex-start", py: 0, minHeight: 28 }}
          onClick={() => onExpandedChange?.(!expanded)}
        >
          {expanded ? "Show fewer periods" : "Show more periods…"}
        </Button>
      ) : null}
      {start && end ? (
        <Typography variant="caption" color="text.secondary">
          {normPayPeriodYmd(start)} – {normPayPeriodYmd(end)}
        </Typography>
      ) : null}
    </Stack>
  );
}
