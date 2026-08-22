import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import { DateTimePicker } from "@mui/x-date-pickers/DateTimePicker";
import { LocalizationProvider } from "@mui/x-date-pickers/LocalizationProvider";
import { AdapterDayjs } from "@mui/x-date-pickers/AdapterDayjs";
import { Stack, TextField, Typography } from "@mui/material";
import dayjs from "dayjs";
import { formatFriendlyEtWall } from "../utils/rinseTimeFormat";

function toDayjs(val) {
  if (!val) return null;
  const s = String(val).trim().replace(" ", "T");
  const d = dayjs(s);
  return d.isValid() ? d : null;
}

function toDatetimeLocal(d) {
  if (!d || !d.isValid()) return "";
  return d.format("YYYY-MM-DDTHH:mm");
}

export function PayrollDateField({ label, value, onChange, size = "small", sx }) {
  return (
    <LocalizationProvider dateAdapter={AdapterDayjs}>
      <DatePicker
        label={label}
        value={toDayjs(value ? `${value}T12:00` : "")}
        onChange={(d) => onChange(d?.isValid() ? d.format("YYYY-MM-DD") : "")}
        slotProps={{
          textField: { size, fullWidth: true, sx },
          openPickerButton: { "aria-label": `Choose ${label}` },
        }}
      />
    </LocalizationProvider>
  );
}

export function PayrollDateTimeField({
  label,
  value,
  onChange,
  size = "small",
  disabled,
  clearable = false,
}) {
  return (
    <LocalizationProvider dateAdapter={AdapterDayjs}>
      <DateTimePicker
        label={label}
        value={toDayjs(value)}
        onChange={(d) => onChange(toDatetimeLocal(d))}
        disabled={disabled}
        ampm
        closeOnSelect={false}
        slotProps={{
          textField: { size, fullWidth: true },
          field: clearable ? { clearable: true } : undefined,
          openPickerButton: { "aria-label": `Choose ${label}` },
        }}
      />
    </LocalizationProvider>
  );
}

/** Compact date + time inputs with minute precision (no 5-minute snapping). */
export function CompactEtDateTimeField({
  label,
  value,
  onChange,
  disabled = false,
}) {
  const datePart = value ? String(value).slice(0, 10) : "";
  const timePart = value && String(value).length >= 16 ? String(value).slice(11, 16) : "";

  const emit = (nextDate, nextTime) => {
    if (!nextDate) {
      onChange("");
      return;
    }
    onChange(`${nextDate}T${nextTime || "12:00"}`);
  };

  const friendly =
    value && formatFriendlyEtWall(value)
      ? formatFriendlyEtWall(value)
      : value
        ? String(value).replace("T", " ")
        : "";

  return (
    <Stack spacing={0.75}>
      {label ? (
        <Typography variant="caption" color="text.secondary" fontWeight={600}>
          {label}
        </Typography>
      ) : null}
      {friendly ? (
        <Typography variant="body2" fontWeight={700} sx={{ color: "#0f172a" }}>
          {friendly}
        </Typography>
      ) : null}
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
        <TextField
          type="date"
          size="small"
          label="Date"
          value={datePart}
          disabled={disabled}
          onChange={(e) => emit(e.target.value, timePart)}
          InputLabelProps={{ shrink: true }}
          sx={{ flex: 1 }}
        />
        <TextField
          type="time"
          size="small"
          label="Time"
          value={timePart}
          disabled={disabled}
          onChange={(e) => emit(datePart, e.target.value)}
          inputProps={{ step: 60 }}
          InputLabelProps={{ shrink: true }}
          sx={{ flex: 1 }}
        />
      </Stack>
    </Stack>
  );
}

/** Fallback export for places that still need raw string conversion. */
export { toDayjs, toDatetimeLocal };
