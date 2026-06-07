import { parseTimeToMinutes } from "../../payroll/schedulePlanner";

export const QUICK_TIME_CHIPS = [
  { label: "7 AM", value: "07:00" },
  { label: "8 AM", value: "08:00" },
  { label: "9 AM", value: "09:00" },
  { label: "3 PM", value: "15:00" },
  { label: "4 PM", value: "16:00" },
  { label: "11 PM", value: "23:00" },
];

export function normalizeTimeHm(value) {
  if (value == null || value === "") return "";
  const s = String(value).trim();
  const m = s.match(/^(\d{1,2}):(\d{2})/);
  if (!m) return "";
  const h = Math.min(23, Math.max(0, parseInt(m[1], 10)));
  const min = Math.min(59, Math.max(0, parseInt(m[2], 10)));
  return `${String(h).padStart(2, "0")}:${String(min).padStart(2, "0")}`;
}

export function formatTime12(hm) {
  const mins = parseTimeToMinutes(normalizeTimeHm(hm));
  if (mins == null) return "";
  const h24 = Math.floor(mins / 60) % 24;
  const minute = mins % 60;
  const ampm = h24 >= 12 ? "PM" : "AM";
  let h12 = h24 % 12;
  if (h12 === 0) h12 = 12;
  return `${h12}:${String(minute).padStart(2, "0")} ${ampm}`;
}

export function time12Parts(hm) {
  const mins = parseTimeToMinutes(normalizeTimeHm(hm));
  if (mins == null) return { hour12: 7, minute: 0, ampm: "AM" };
  const h24 = Math.floor(mins / 60) % 24;
  const minute = mins % 60;
  const ampm = h24 >= 12 ? "PM" : "AM";
  let hour12 = h24 % 12;
  if (hour12 === 0) hour12 = 12;
  return { hour12, minute, ampm };
}

export function hmFrom12Parts(hour12, minute, ampm) {
  let h = Number(hour12) % 12;
  if (ampm === "PM") h += 12;
  return `${String(h).padStart(2, "0")}:${String(Number(minute) || 0).padStart(2, "0")}`;
}

export const PICKER_FIELD_SX = {
  "& .MuiInputBase-root": {
    minHeight: 48,
    borderRadius: 2,
    fontSize: "1rem",
  },
  "& .MuiInputBase-input": {
    py: 1.25,
    cursor: "pointer",
  },
};
