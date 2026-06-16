import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Box,
  Button,
  Chip,
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
import {
  addDaysYmd,
  businessTodayYmd,
  formatDateShortLabel,
  formatWeekRangeLabel,
  weekEndFromStart,
  weekStartFromDate,
} from "../utils/businessTime";

/**
 * Shared payroll date search: weekly pay period (Mon–Sun from maintenance) or free range (default today).
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

  const periodLabel = useMemo(() => {
    if (mode !== "pay_period" || !start || !end) return null;
    return formatWeekRangeLabel(start, end);
  }, [mode, start, end]);

  const patch = (p) => onChange?.({ mode, start, end, category, ...p });

  const shiftPayPeriod = (weeks) => {
    if (!start) return;
    const nextStart = weekStartFromDate(addDaysYmd(start, weeks * 7), weekStartsOn);
    patch({ start: nextStart, end: weekEndFromStart(nextStart) });
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
          <Box sx={{ flex: 1, minWidth: 200 }}>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
              Current pay period
              {periodLabel ? `: ${periodLabel}` : ""}
            </Typography>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
              <Button size="small" variant="outlined" onClick={() => shiftPayPeriod(-1)}>
                Previous week
              </Button>
              <Chip
                size="small"
                label="Current week"
                clickable
                onClick={() => applyModeDefaults("pay_period", weekStartsOn)}
              />
              <Button size="small" variant="outlined" onClick={() => shiftPayPeriod(1)}>
                Next week
              </Button>
            </Stack>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mt: 1 }}>
              <PayrollDateField
                label="Week start"
                value={start}
                onChange={(v) => patch({ start: v, end: end || v })}
              />
              <PayrollDateField
                label="Week end"
                value={end}
                onChange={(v) => patch({ end: v })}
              />
            </Stack>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
              Weekly cycle aligned to maintenance settings (Monday–Sunday by default).
            </Typography>
          </Box>
        ) : (
          <Stack spacing={1} sx={{ flex: 1 }}>
            <Chip
              size="small"
              label={`Today (${formatDateShortLabel(businessTodayYmd())})`}
              clickable
              onClick={() => applyModeDefaults("range", weekStartsOn)}
              sx={{ alignSelf: "flex-start" }}
            />
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
