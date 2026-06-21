import {
  Autocomplete,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import PayPeriodSelect from "./PayPeriodSelect";
import { normPayPeriodYmd } from "../payroll/payPeriodOptions";

export function formatAccountantBatchLabel(batch) {
  if (!batch) return "";
  const name = batch.batch_name || `W2-${batch.id}`;
  return `${batch.pay_period_start} – ${batch.pay_period_end} · ${name}`;
}

/**
 * Shared accountant filter bar: view by employee or by batch.
 */
export default function AccountantScopeFilters({
  viewMode,
  onViewModeChange,
  batches = [],
  selectedBatchId = "",
  onBatchChange,
  workers = [],
  selectedWorker = null,
  onWorkerChange,
  workerLabel = "Employee",
  category = "w2",
  onCategoryChange,
  categoryOptions = [],
  range = "this_year",
  onRangeChange,
  rangeOptions = [],
  weekStartsOn = 0,
  periodStart = "",
  periodEnd = "",
  onPeriodChange,
  batchStatusLabel,
}) {
  const selectedBatch =
    batches.find((b) => String(b.id) === String(selectedBatchId)) || null;

  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Tabs
        value={viewMode}
        onChange={(_, v) => onViewModeChange(v)}
        sx={{ mb: 2, minHeight: 36, "& .MuiTab-root": { minHeight: 36, py: 0.5 } }}
      >
        <Tab label="By employee" value="employee" />
        <Tab label="By batch" value="batch" />
      </Tabs>

      {viewMode === "employee" ? (
        <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems={{ md: "flex-start" }}>
          {categoryOptions.length ? (
            <FormControl size="small" sx={{ minWidth: 180 }}>
              <InputLabel id="accountant-scope-category">Category</InputLabel>
              <Select
                labelId="accountant-scope-category"
                label="Category"
                value={category}
                onChange={(e) => onCategoryChange?.(e.target.value)}
              >
                {categoryOptions.map((o) => (
                  <MenuItem key={o.value} value={o.value}>
                    {o.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          ) : null}
          <Autocomplete
            sx={{ flex: 1, minWidth: 220 }}
            options={workers}
            value={selectedWorker}
            onChange={(_, v) => onWorkerChange(v)}
            getOptionLabel={(o) => o?.label || ""}
            renderInput={(params) => (
              <TextField {...params} label={workerLabel} size="small" placeholder="Search by name" />
            )}
          />
          {rangeOptions.length ? (
            <FormControl size="small" sx={{ minWidth: 180 }}>
              <InputLabel>Pay periods</InputLabel>
              <Select label="Pay periods" value={range} onChange={(e) => onRangeChange?.(e.target.value)}>
                {rangeOptions.map((o) => (
                  <MenuItem key={o.value} value={o.value}>
                    {o.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          ) : null}
          <FormControl size="small" sx={{ minWidth: 280 }}>
            <InputLabel id="accountant-employee-batch">Batch (optional)</InputLabel>
            <Select
              labelId="accountant-employee-batch"
              label="Batch (optional)"
              value={selectedBatchId || ""}
              onChange={(e) => onBatchChange(e.target.value || null)}
            >
              <MenuItem value="">
                <em>All batches</em>
              </MenuItem>
              {batches.map((b) => (
                <MenuItem key={b.id} value={String(b.id)}>
                  {formatAccountantBatchLabel(b)}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </Stack>
      ) : (
        <Stack spacing={1.5}>
          <FormControl size="small" sx={{ minWidth: 320, maxWidth: 520 }}>
            <InputLabel id="accountant-batch-select">Batch</InputLabel>
            <Select
              labelId="accountant-batch-select"
              label="Batch"
              value={selectedBatchId || ""}
              onChange={(e) => onBatchChange(e.target.value || null)}
            >
              <MenuItem value="">
                <em>Select a batch</em>
              </MenuItem>
              {batches.map((b) => (
                <MenuItem key={b.id} value={String(b.id)}>
                  {formatAccountantBatchLabel(b)}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          {onPeriodChange ? (
            <PayPeriodSelect
              weekStartsOn={weekStartsOn}
              batches={batches}
              start={periodStart}
              end={periodEnd}
              batchStatusLabel={batchStatusLabel}
              batchOnly
              onChange={({ start, end, batchId }) => {
                onPeriodChange({ start, end, batchId });
                if (batchId) onBatchChange(String(batchId));
              }}
            />
          ) : null}
          {selectedBatch ? (
            <Typography variant="caption" color="text.secondary">
              {formatAccountantBatchLabel(selectedBatch)}
            </Typography>
          ) : (
            <Typography variant="body2" color="text.secondary">
              Choose a pay period batch to view employees and paystubs.
            </Typography>
          )}
          {selectedBatch && workers.length ? (
            <Autocomplete
              sx={{ maxWidth: 420 }}
              options={workers}
              value={selectedWorker}
              onChange={(_, v) => onWorkerChange(v)}
              getOptionLabel={(o) => o?.label || ""}
              renderInput={(params) => (
                <TextField
                  {...params}
                  label="Employee in batch (optional)"
                  size="small"
                  placeholder="All employees"
                />
              )}
            />
          ) : null}
        </Stack>
      )}
    </Paper>
  );
}

export function batchMatchesPeriod(batch, start, end) {
  if (!batch || !start || !end) return true;
  return (
    normPayPeriodYmd(batch.pay_period_start) === normPayPeriodYmd(start) &&
    normPayPeriodYmd(batch.pay_period_end) === normPayPeriodYmd(end)
  );
}
