import {
  Box,
  Button,
  Checkbox,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import { DAY_NAMES } from "../../payroll/workerSchedulingProfile";
import PlanningTimePicker from "../datetime/PlanningTimePicker";

export default function WorkerAvailabilityEditor({ value, onChange, shifts = [] }) {
  const rows = value?.length ? value : DAY_NAMES.map((_, dow) => ({ day_of_week: dow, unavailable_flag: true }));

  const updateRow = (dow, patch) => {
    onChange(
      rows.map((r) => (Number(r.day_of_week) === dow ? { ...r, ...patch, day_of_week: dow } : r)),
    );
  };

  const copyMondayWeekdays = () => {
    const mon = rows.find((r) => Number(r.day_of_week) === 0) || {};
    onChange(
      rows.map((r) => {
        const dow = Number(r.day_of_week);
        if (dow >= 1 && dow <= 4) {
          return {
            ...r,
            unavailable_flag: mon.unavailable_flag,
            available_from: mon.available_from,
            available_to: mon.available_to,
            preferred_shift_id: mon.preferred_shift_id,
          };
        }
        return r;
      }),
    );
  };

  const copyDayToAll = (fromDow) => {
    const src = rows.find((r) => Number(r.day_of_week) === fromDow) || {};
    onChange(
      rows.map((r) => ({
        ...r,
        unavailable_flag: src.unavailable_flag,
        available_from: src.available_from,
        available_to: src.available_to,
        preferred_shift_id: src.preferred_shift_id,
        notes: src.notes,
      })),
    );
  };

  const markWeekendsUnavailable = () => {
    onChange(
      rows.map((r) => {
        const dow = Number(r.day_of_week);
        if (dow >= 5) return { ...r, unavailable_flag: true, available_from: "", available_to: "" };
        return r;
      }),
    );
  };

  const clearAll = () => {
    onChange(DAY_NAMES.map((_, dow) => ({ day_of_week: dow, unavailable_flag: true, available_from: "", available_to: "", preferred_shift_id: "", notes: "" })));
  };

  return (
    <Box>
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 1.5 }}>
        <Button size="small" variant="outlined" onClick={copyMondayWeekdays}>
          Copy Mon → weekdays
        </Button>
        <Button size="small" variant="outlined" onClick={() => copyDayToAll(0)}>
          Copy Mon → all
        </Button>
        <Button size="small" variant="outlined" onClick={markWeekendsUnavailable}>
          Weekends unavailable
        </Button>
        <Button size="small" color="inherit" onClick={clearAll}>
          Clear availability
        </Button>
      </Stack>
      <Box className="table-wrapper">
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Day</TableCell>
              <TableCell>Available</TableCell>
              <TableCell>From</TableCell>
              <TableCell>To</TableCell>
              <TableCell>Preferred shift</TableCell>
              <TableCell>Notes</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {DAY_NAMES.map((name, dow) => {
              const row = rows.find((r) => Number(r.day_of_week) === dow) || { day_of_week: dow, unavailable_flag: true };
              const available = !row.unavailable_flag;
              return (
                <TableRow key={dow}>
                  <TableCell>{name}</TableCell>
                  <TableCell>
                    <Checkbox
                      size="small"
                      checked={available}
                      onChange={(e) => updateRow(dow, { unavailable_flag: !e.target.checked })}
                    />
                  </TableCell>
                  <TableCell>
                    <PlanningTimePicker
                      compact
                      disabled={!available}
                      value={(row.available_from || "").slice(0, 5)}
                      onChange={(available_from) => updateRow(dow, { available_from })}
                    />
                  </TableCell>
                  <TableCell>
                    <PlanningTimePicker
                      compact
                      disabled={!available}
                      value={(row.available_to || "").slice(0, 5)}
                      onChange={(available_to) => updateRow(dow, { available_to })}
                    />
                  </TableCell>
                  <TableCell>
                    <FormControl size="small" sx={{ minWidth: 120 }} disabled={!available}>
                      <InputLabel>Shift</InputLabel>
                      <Select
                        label="Shift"
                        value={row.preferred_shift_id || ""}
                        onChange={(e) => {
                          const preferred_shift_id = e.target.value || null;
                          const sh = shifts.find((s) => String(s.id) === String(preferred_shift_id));
                          updateRow(dow, {
                            preferred_shift_id,
                            ...(sh
                              ? {
                                  available_from: sh.start_time_default?.slice(0, 5),
                                  available_to: sh.end_time_default?.slice(0, 5),
                                }
                              : {}),
                          });
                        }}
                      >
                        <MenuItem value="">—</MenuItem>
                        {shifts.filter((s) => s.active).map((s) => (
                          <MenuItem key={s.id} value={s.id}>
                            {s.name}
                          </MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                  </TableCell>
                  <TableCell>
                    <TextField
                      size="small"
                      fullWidth
                      disabled={!available}
                      value={row.notes || ""}
                      onChange={(e) => updateRow(dow, { notes: e.target.value })}
                    />
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </Box>
      <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: "block" }}>
        Scheduling uses this grid to warn when shifts fall outside availability.
      </Typography>
    </Box>
  );
}
