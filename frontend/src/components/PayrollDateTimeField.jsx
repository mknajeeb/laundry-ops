import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import { DateTimePicker } from "@mui/x-date-pickers/DateTimePicker";
import { LocalizationProvider } from "@mui/x-date-pickers/LocalizationProvider";
import { AdapterDayjs } from "@mui/x-date-pickers/AdapterDayjs";
import dayjs from "dayjs";

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

/** Fallback export for places that still need raw string conversion. */
export { toDayjs, toDatetimeLocal };
