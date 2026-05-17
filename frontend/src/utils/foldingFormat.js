export function formatFoldingDuration(seconds) {
  const s = Number(seconds);
  if (!Number.isFinite(s) || s <= 0) return "—";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

export function formatFoldingHours(seconds) {
  const s = Number(seconds);
  if (!Number.isFinite(s) || s <= 0) return "—";
  return (s / 3600).toFixed(2);
}

export function formatRate(val, digits = 2) {
  if (val == null || val === "") return "—";
  const n = Number(val);
  if (!Number.isFinite(n)) return "—";
  return n.toFixed(digits);
}

export function formatLbs(val) {
  if (val == null || val === "") return "—";
  const n = Number(val);
  if (!Number.isFinite(n)) return "—";
  return n.toFixed(1);
}

export function formatDateTime(val) {
  if (!val) return "—";
  const d = new Date(val);
  if (Number.isNaN(d.getTime())) return String(val);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function isoDateInput(d = new Date()) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function targetStatusChipColor(status) {
  const s = String(status || "").toLowerCase();
  if (s === "above") return "success";
  if (s === "below") return "error";
  if (s === "mixed") return "warning";
  return "default";
}
