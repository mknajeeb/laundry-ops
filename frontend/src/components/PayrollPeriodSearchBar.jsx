import { useCallback, useEffect, useState } from "react";
import {
  Box,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
} from "@mui/material";
import { getPayrollPeriodSettings } from "../api";
import PayPeriodSelect from "./PayPeriodSelect";
import { PayrollDateField } from "./PayrollDateTimeField";
import {
  defaultPayPeriodRange,
  defaultRangeSearchDates,
  PAYROLL_SEARCH_MODES,
} from "../payroll/payPeriodDefaults";
import { normPayPeriodYmd } from "../payroll/payPeriodOptions";
import { weekEndFromStart } from "../utils/businessTime";

/**
 * Shared payroll date search: weekly pay period dropdown or free range (default today).
 */
export default function PayrollPeriodSearchBar({ value, onChange, batches = [] }) {
  const mode = value?.mode || "pay_period";
  const start = value?.start || "";
  const end = value?.end || "";
  const category = value?.category || "all";

  const [weekStartsOn, setWeekStartsOn] = useState(0);
  const [settingsLoaded, setSettingsLoaded] = useState(false);
  const [periodExpanded, setPeriodExpanded] = useState(false);

  useEffect(() => {
    getPayrollPeriodSettings()
      .then((res) => {
        const ws = Number(res.data?.week_starts_on ?? 0);
        setWeekStartsOn(Number.isFinite(ws) ? ws : 0);
      })
      .catch(() => setWeekStartsOn(0))
      .finally(() => setSettingsLoaded(true));
  }, []);

  const applyModeDefaults = useCallback(
    (nextMode, ws) => {
      if (nextMode === "pay_period") {
        const r = defaultPayPeriodRange(ws);
        onChange?.({ mode: nextMode, start: r.start, end: r.end, category });
        return;
      }
      const r = defaultRangeSearchDates();
      onChange?.({ mode: nextMode, start: r.start, end: r.end, category });
    },
    [category, onChange],
  );

  useEffect(() => {
    if (!settingsLoaded || start) return;
    applyModeDefaults(mode, weekStartsOn);
  }, [settingsLoaded, start, mode, weekStartsOn, applyModeDefaults]);

  const patch = (p) => onChange?.({ mode, start, end, category, ...p });

  return (
    <Paper sx={{ p: 2, mb: 2 }} className="no-print">
      <Stack
        direction={{ xs: "column", md: "row" }}
        spacing={2}
        alignItems={{ xs: "stretch", md: "flex-end" }}
        flexWrap="wrap"
        useFlexGap
      >
        <FormControl size="small" sx={{ minWidth: 200 }}>
          <InputLabel>Search by</InputLabel>
          <Select
            label="Search by"
            value={mode}
            onChange={(e) => applyModeDefaults(e.target.value, weekStartsOn)}
          >
            {PAYROLL_SEARCH_MODES.map((o) => (
              <MenuItem key={o.id} value={o.id}>
                {o.label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        {mode === "pay_period" ? (
          <Box sx={{ flex: 1, minWidth: 240 }}>
            <PayPeriodSelect
              weekStartsOn={weekStartsOn}
              batches={batches}
              start={start}
              end={end}
              expanded={periodExpanded}
              onExpandedChange={setPeriodExpanded}
              onChange={({ start: s, end: e }) => patch({ start: s, end: e })}
            />
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mt: 1 }}>
              <PayrollDateField
                label="Week start"
                value={start}
                onChange={(v) => {
                  const nextEnd = v ? weekEndFromStart(v) : end;
                  patch({ start: v, end: nextEnd || v });
                }}
              />
              <PayrollDateField
                label="Week end"
                value={end}
                onChange={(v) => patch({ end: v })}
              />
            </Stack>
          </Box>
        ) : (
          <Stack spacing={1} sx={{ flex: 1 }}>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
              <PayrollDateField label="From" value={start} onChange={(v) => patch({ start: v })} />
              <PayrollDateField label="To" value={end} onChange={(v) => patch({ end: v })} />
            </Stack>
          </Stack>
        )}
      </Stack>
    </Paper>
  );
}
