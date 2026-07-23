/** Helpers for Maintenance Task List UI. */

export const MTL_STATUS = {
  IN_PROGRESS: "in_progress",
  COMPLETED: "completed",
  SUBMITTED: "submitted", // legacy alias for completed
  NOT_STARTED: "not_started",
};

export const MTL_FREQUENCIES = [
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "Weekly" },
  { value: "as_needed", label: "As Needed" },
];

export const MTL_WEEKDAYS = [
  { value: 0, label: "Mon" },
  { value: 1, label: "Tue" },
  { value: 2, label: "Wed" },
  { value: 3, label: "Thu" },
  { value: 4, label: "Fri" },
  { value: 5, label: "Sat" },
  { value: 6, label: "Sun" },
];

const SESSION_KEY = "washpro_mtl_pin_session";

export function loadMtlPinSession() {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed?.token || !parsed?.employee_id) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function saveMtlPinSession(session) {
  try {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
  } catch {
    /* ignore */
  }
}

export function clearMtlPinSession() {
  try {
    sessionStorage.removeItem(SESSION_KEY);
  } catch {
    /* ignore */
  }
}

export function isCompletedStatus(status) {
  return status === MTL_STATUS.COMPLETED || status === MTL_STATUS.SUBMITTED;
}

export function statusLabel(status) {
  if (isCompletedStatus(status)) return "Completed";
  if (status === MTL_STATUS.IN_PROGRESS) return "In Progress";
  if (status === MTL_STATUS.NOT_STARTED) return "Not Started";
  return status || "—";
}

/** True when every assigned item is checked (Submit Checklist may enable). */
export function allTasksChecked(list) {
  const items = list?.items || [];
  if (!items.length) return false;
  return items.every((i) => !!i.completed);
}

export function formatTimeEt(value) {
  if (!value) return "—";
  try {
    const d = typeof value === "string" || value instanceof Date ? new Date(value) : null;
    if (!d || Number.isNaN(d.getTime())) {
      const s = String(value);
      const m = s.match(/(\d{1,2}:\d{2})/);
      return m ? m[1] : s;
    }
    return d.toLocaleTimeString("en-US", {
      timeZone: "America/New_York",
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return String(value);
  }
}

export function formatDateShort(isoDate) {
  if (!isoDate) return "—";
  try {
    const [y, m, d] = String(isoDate).slice(0, 10).split("-").map(Number);
    const dt = new Date(Date.UTC(y, m - 1, d, 12));
    return dt.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
  } catch {
    return String(isoDate);
  }
}

/** Mobile layout guard: sticky footer + content padding must avoid horizontal overflow. */
export function mtlEmployeePageSx() {
  return {
    minHeight: "100dvh",
    width: "100%",
    maxWidth: "100vw",
    overflowX: "hidden",
    boxSizing: "border-box",
    bgcolor: "#f8fafc",
    pb: "calc(96px + env(safe-area-inset-bottom))",
  };
}

export function canAccessMaintenanceTaskReports(tier, hasPerm) {
  if (typeof hasPerm === "function") {
    if (hasPerm("maintenance.tasks.reports")) return true;
    if (hasPerm("maintenance.tasks.manage")) return true;
    const catalogPresent =
      hasPerm("maintenance.tasks.view") ||
      hasPerm("maintenance.tasks.update") ||
      hasPerm("maintenance.tasks.submit") ||
      hasPerm("maintenance.tasks.manage") ||
      hasPerm("maintenance.tasks.reopen") ||
      hasPerm("maintenance.tasks.reports");
    if (catalogPresent) {
      return hasPerm("maintenance.tasks.reports") || hasPerm("maintenance.tasks.manage");
    }
  }
  return tier === "admin" || tier === "ops" || tier === "supervisor";
}

export function canManageMaintenanceTaskSettings(tier, hasPerm) {
  if (typeof hasPerm === "function") {
    if (hasPerm("maintenance.tasks.manage")) return true;
    const catalogPresent =
      hasPerm("maintenance.tasks.view") ||
      hasPerm("maintenance.tasks.update") ||
      hasPerm("maintenance.tasks.submit") ||
      hasPerm("maintenance.tasks.manage") ||
      hasPerm("maintenance.tasks.reopen") ||
      hasPerm("maintenance.tasks.reports");
    if (catalogPresent) return false;
  }
  return tier === "admin";
}

export function getMaintenanceRoleTier(user) {
  const roles = new Set((user?.roles || []).map((r) => String(r).toUpperCase()));
  if (roles.has("ADMIN") || roles.has("SUPER_ADMIN") || roles.has("PLATFORM_ADMIN")) {
    return "admin";
  }
  if (roles.has("OPS")) return "ops";
  return "floor";
}

export function reorderIds(ids, fromIndex, toIndex) {
  const next = [...ids];
  if (fromIndex < 0 || toIndex < 0 || fromIndex >= next.length || toIndex >= next.length) {
    return next;
  }
  const [moved] = next.splice(fromIndex, 1);
  next.splice(toIndex, 0, moved);
  return next;
}
