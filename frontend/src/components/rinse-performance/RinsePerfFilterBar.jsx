import {
  Box,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import { VEEWASH_BRAND } from "../../theme/veewashBrand";
import { COMPARES, METRICS, PERIODS, VIEWS } from "./rinsePerfFormat";

export default function RinsePerfFilterBar({
  view,
  onView,
  period,
  onPeriod,
  compare,
  onCompare,
  metric,
  onMetric,
  customStart,
  customEnd,
  onCustomStart,
  onCustomEnd,
  resolvedLabel,
  showRole,
  roleKey,
  onRole,
  showEmployee,
  employees,
  employeeId,
  onEmployee,
  showDate,
  dailyDate,
  onDailyDate,
}) {
  return (
    <Box
      sx={{
        position: "sticky",
        top: 0,
        zIndex: 8,
        bgcolor: "rgba(246, 250, 251, 0.92)",
        backdropFilter: "blur(8px)",
        borderBottom: `1px solid ${VEEWASH_BRAND.borderSoft}`,
        px: { xs: 1.5, md: 2 },
        py: 1.25,
        mb: 2,
      }}
    >
      <Stack spacing={1.25}>
        <Stack
          direction={{ xs: "column", md: "row" }}
          spacing={1}
          alignItems={{ md: "center" }}
          justifyContent="space-between"
        >
          <Box>
            <Typography variant="h6" fontWeight={800} sx={{ color: VEEWASH_BRAND.ink, lineHeight: 1.2 }}>
              Rinse Performance
            </Typography>
            {resolvedLabel ? (
              <Typography variant="caption" sx={{ color: VEEWASH_BRAND.inkMuted }}>
                {resolvedLabel}
              </Typography>
            ) : null}
          </Box>
          <ToggleButtonGroup
            exclusive
            size="small"
            value={view}
            onChange={(_, v) => v && onView(v)}
            sx={{ bgcolor: "#fff", borderRadius: 2 }}
          >
            {VIEWS.map((v) => (
              <ToggleButton key={v.key} value={v.key} sx={{ textTransform: "none", px: 1.5 }}>
                {v.label}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
        </Stack>

        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          {view !== "daily" ? (
            <FormControl size="small" sx={{ minWidth: 140 }}>
              <InputLabel id="rp-period">Period</InputLabel>
              <Select
                labelId="rp-period"
                label="Period"
                value={period}
                onChange={(e) => onPeriod(e.target.value)}
              >
                {PERIODS.map((p) => (
                  <MenuItem key={p.key} value={p.key}>
                    {p.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          ) : null}

          {view !== "daily" && period === "custom" ? (
            <>
              <TextField
                size="small"
                type="date"
                label="Start"
                InputLabelProps={{ shrink: true }}
                value={customStart || ""}
                onChange={(e) => onCustomStart(e.target.value)}
                sx={{ width: 150 }}
              />
              <TextField
                size="small"
                type="date"
                label="End"
                InputLabelProps={{ shrink: true }}
                value={customEnd || ""}
                onChange={(e) => onCustomEnd(e.target.value)}
                sx={{ width: 150 }}
              />
            </>
          ) : null}

          {view === "daily" ? (
            <TextField
              size="small"
              type="date"
              label="Business Date"
              InputLabelProps={{ shrink: true }}
              value={dailyDate || ""}
              onChange={(e) => onDailyDate(e.target.value)}
              sx={{ width: 170 }}
            />
          ) : null}

          {view !== "daily" ? (
            <FormControl size="small" sx={{ minWidth: 160 }}>
              <InputLabel id="rp-compare">Compare to</InputLabel>
              <Select
                labelId="rp-compare"
                label="Compare to"
                value={compare}
                onChange={(e) => onCompare(e.target.value)}
              >
                {COMPARES.map((c) => (
                  <MenuItem key={c.key} value={c.key}>
                    {c.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          ) : null}

          <FormControl size="small" sx={{ minWidth: 150 }}>
            <InputLabel id="rp-metric">Metric</InputLabel>
            <Select
              labelId="rp-metric"
              label="Metric"
              value={metric}
              onChange={(e) => onMetric(e.target.value)}
            >
              {METRICS.map((m) => (
                <MenuItem key={m.key} value={m.key}>
                  {m.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          {showRole ? (
            <FormControl size="small" sx={{ minWidth: 120 }}>
              <InputLabel id="rp-role">Role</InputLabel>
              <Select
                labelId="rp-role"
                label="Role"
                value={roleKey}
                onChange={(e) => onRole?.(e.target.value)}
              >
                <MenuItem value="FOLDER">Folder</MenuItem>
              </Select>
            </FormControl>
          ) : null}

          {showEmployee ? (
            <FormControl size="small" sx={{ minWidth: 200 }}>
              <InputLabel id="rp-emp">Employee</InputLabel>
              <Select
                labelId="rp-emp"
                label="Employee"
                value={employeeId || ""}
                onChange={(e) => onEmployee?.(e.target.value || null)}
                displayEmpty
              >
                <MenuItem value="">
                  <em>Select employee</em>
                </MenuItem>
                {(employees || []).map((e) => (
                  <MenuItem key={e.employee_id} value={e.employee_id}>
                    {e.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          ) : null}
        </Stack>
      </Stack>
    </Box>
  );
}
