import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Box,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Typography,
} from "@mui/material";
import { getPayrollPeriodSettings } from "../api";
import { PayrollDateField } from "./PayrollDateTimeField";
import {
  defaultPayPeriodRange,
  defaultRangeSearchDates,
  PAYROLL_SEARCH_MODES,
} from "../payroll/payPeriodDefaults";
import { buildPayPeriodOptions } from "../payroll/payPeriodOptions";
import {
  businessTodayYmd,
  formatDateShortLabel,
  formatWeekRangeLabel,
  weekEndFromStart,
} from "../utils/businessTime";

/**
 * Shared payroll date search: weekly pay period dropdown or free range (default today).
 */
export default function PayrollPeriodSearchBar({ value, onChange }) {
  const mode = value?.mode || "pay_period";
  const start = value?.start || "";
  const end = value?.end || "";
  const category = value?.category || "all";

  const [weekStartsOn, setWeekStartsOn] = useState(0);
  const [settingsLoaded, setSettingsLoaded] = useState(false);

  useEffect(() => {
    getPayrollPeriodSettings()
      .then((res) => {
        const ws = Number(res.data?.week_starts_on ?? 0);
        setWeekStartsOn(Number.isFinite(ws) ? ws : 0);
      })
      .catch(() => setWeekStartsOn(0))
      .finally(() => setSettingsLoaded(true));
  }, []);

  const periodOptions = useMemo(
    () => buildPayPeriodOptions(weekStartsOn),
    [weekStartsOn],
  );

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

  const periodKey = start && end ? `${start}|${end}` : "";
  const periodLabel = useMemo(() => {
    if (mode !== "pay_period" || !start || !end) return null;
    return formatWeekRangeLabel(start, end);
  }, [mode, start, end]);

  const patch = (p) => onChange?.({ mode, start, end, category, ...p });

  const onPeriodPick = (key) => {
    const opt = periodOptions.find((o) => o.key === key);
    if (!opt) return;
    patch({ start: opt.start, end: opt.end });
  };

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
            <FormControl size="small" fullWidth sx={{ minWidth: 280 }}>
              <InputLabel>Pay period</InputLabel>
              <Select
                label="Pay period"
                value={periodKey}
                onChange={(e) => onPeriodPick(e.target.value)}
              >
                {periodOptions.map((o) => (
                  <MenuItem key={o.key} value={o.key}>
                    {o.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            {periodLabel ? (
              <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.75 }}>
                {start} – {end} · weekly cycle (Mon–Sun by default)
              </Typography>
            ) : null}
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mt: 1 }}>
              <PayrollDateField
                label="Week start"
                value={start}
                onChange={(v) => {
                  const nextEnd = v ? weekEndFromStart(v) : end;
                  patch({ start: v, end: nextEnd || v });
                }}
              />
              <PayrollDateField label="Week end" value={end} onChange={(v) => patch({ end: v })} />
            </Stack>
          </Box>
        ) : (
          <Stack spacing={1} sx={{ flex: 1 }}>
            <Typography variant="caption" color="text.secondary">
              Today: {formatDateShortLabel(businessTodayYmd())}
            </Typography>
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
