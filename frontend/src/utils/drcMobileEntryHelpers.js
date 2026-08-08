/** Phase 5E — mobile Revenue & Cost helpers (presentation / validation only). */

export const DRC_MOBILE_CONFLICT_MESSAGE =
  "This Revenue & Cost entry was updated on another device. Review the latest saved values, then retry your changes.";

export function formatBusinessDateLong(isoDate) {
  if (!isoDate) return "";
  try {
    const d = new Date(`${String(isoDate).slice(0, 10)}T12:00:00`);
    return d.toLocaleDateString("en-US", {
      weekday: "long",
      month: "long",
      day: "numeric",
    });
  } catch {
    return String(isoDate);
  }
}

export function formatSubmittedTime(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    return d.toLocaleTimeString("en-US", {
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return String(iso);
  }
}

export function formatMoneyInput(value) {
  if (value === null || value === undefined || value === "") return "";
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function parseMoneyInput(raw) {
  if (raw === null || raw === undefined || raw === "") return { ok: true, value: null };
  const cleaned = String(raw).replace(/[$,\s]/g, "");
  if (cleaned === "") return { ok: true, value: null };
  if (!/^-?\d*\.?\d*$/.test(cleaned)) return { ok: false, error: "Enter a valid amount." };
  const n = Number(cleaned);
  if (!Number.isFinite(n)) return { ok: false, error: "Enter a valid amount." };
  if (n < 0) return { ok: false, error: "Value cannot be negative." };
  return { ok: true, value: n };
}

export function parseQtyInput(raw) {
  if (raw === null || raw === undefined || raw === "") return { ok: true, value: null };
  const cleaned = String(raw).replace(/[,\s]/g, "");
  if (cleaned === "") return { ok: true, value: null };
  if (!/^-?\d*\.?\d*$/.test(cleaned)) return { ok: false, error: "Enter a valid number." };
  const n = Number(cleaned);
  if (!Number.isFinite(n)) return { ok: false, error: "Enter a valid number." };
  if (n < 0) return { ok: false, error: "Value cannot be negative." };
  return { ok: true, value: n };
}

export function valuesStateFromPayload(payload) {
  const out = {};
  for (const sec of payload?.assigned_sections || []) {
    out[sec.section_key] = {
      values: { ...(sec.values || {}) },
      note: sec.note || "",
      draft_revision: Number(sec.draft_revision) || 0,
      status: String(sec.status || "draft").toLowerCase(),
      rejection_reason: sec.rejection_reason || sec.return_reason || "",
      return_reason: sec.return_reason || sec.rejection_reason || "",
      fields: sec.fields || [],
      section_label: sec.section_label,
      calculated: sec.calculated || {},
      submitted_at: sec.submitted_at,
    };
  }
  return out;
}

export function sectionIsLocked(status) {
  const st = String(status || "").toLowerCase();
  // Returned (legacy: rejected) reopens for employee correction.
  return st === "submitted" || st === "approved";
}

export function sectionIsReturned(status) {
  const st = String(status || "").toLowerCase();
  return st === "returned" || st === "rejected";
}

export function managerStatusLabel(status) {
  const st = String(status || "").toLowerCase();
  if (st === "submitted") return "Submitted";
  if (st === "approved") return "Approved";
  if (st === "returned" || st === "rejected") return "Returned";
  return st || "Draft";
}

export function allSectionsSubmitted(payload) {
  const secs = payload?.assigned_sections || [];
  return secs.length > 0 && secs.every((s) => sectionIsLocked(s.status));
}

export function compactProgress(valuesState) {
  const keys = Object.keys(valuesState || {});
  let done = 0;
  for (const k of keys) {
    const sec = valuesState[k];
    if (sectionIsLocked(sec.status)) {
      done += 1;
      continue;
    }
    const required = (sec.fields || []).filter((f) => f.required && f.kind !== "info");
    if (!required.length) continue;
    const complete = required.every((f) => {
      const v = sec.values?.[f.key];
      return v !== null && v !== undefined && v !== "";
    });
    if (complete) done += 1;
  }
  return { done, total: keys.length };
}
