/** Shared visual tokens for the scheduling planner. */
export const SCHEDULE_THEME = {
  pageGradient: "linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%)",
  card: {
    borderRadius: 3,
    boxShadow: "0 4px 24px rgba(15, 23, 42, 0.06)",
    border: "1px solid rgba(148, 163, 184, 0.25)",
    bgcolor: "#ffffff",
  },
  shiftCard: {
    borderRadius: 3,
    background: "linear-gradient(135deg, #ffffff 0%, #f8fafc 100%)",
    border: "1px solid rgba(99, 102, 241, 0.12)",
    boxShadow: "0 8px 32px rgba(99, 102, 241, 0.08)",
  },
  stickyBar: {
    backdropFilter: "blur(12px)",
    bgcolor: "rgba(255,255,255,0.92)",
    borderBottom: "1px solid rgba(148, 163, 184, 0.2)",
  },
  accent: "#6366f1",
  accentSoft: "rgba(99, 102, 241, 0.08)",
};

export const STATUS_BADGE = {
  scheduled: { label: "Scheduled", color: "primary" },
  clocked_in: { label: "Clocked In", color: "info" },
  completed: { label: "Completed", color: "success" },
  late: { label: "Late", color: "warning" },
  missing: { label: "Missing", color: "error" },
  sick: { label: "Sick", color: "warning" },
  absent: { label: "Absent", color: "error" },
  no_show: { label: "No Show", color: "error" },
  replaced: { label: "Replaced", color: "default" },
  cancelled: { label: "Cancelled", color: "default" },
};

export const BALANCE_BADGE = {
  "Overtime Risk": { color: "error", variant: "filled" },
  Heavy: { color: "warning", variant: "filled" },
  Underused: { color: "info", variant: "outlined" },
  Balanced: { color: "success", variant: "outlined" },
};

export function formatTime12(t) {
  if (!t) return "";
  const s = String(t).slice(0, 5);
  const [h, m] = s.split(":").map(Number);
  if (Number.isNaN(h)) return s;
  const ampm = h >= 12 ? "PM" : "AM";
  const hr = h % 12 || 12;
  return `${hr}:${String(m).padStart(2, "0")} ${ampm}`;
}
