const VERIFIED = new Set(["approved", "verified"]);
const AWAITING = new Set(["pending_approval", "completed"]);
const REJECTED = new Set(["rejected"]);

export const SECTION_LABELS = {
  verified: "Verified",
  needs_correction: "Needs Correction",
  pending_verification: "Waiting for Verification",
  in_progress: "In Progress",
};

function recordStatuses(item) {
  return (item?.records || []).map((record) => String(record?.status || "").trim().toLowerCase());
}

export function itemSectionBucket(item) {
  if (item?.required === false) return null;
  const status = String(item?.status || "").trim().toLowerCase();
  const records = recordStatuses(item);
  if (item?.needs_correction || REJECTED.has(status) || records.some((value) => REJECTED.has(value))) {
    return "rejected";
  }
  if (VERIFIED.has(status) || (records.length && records.every((value) => VERIFIED.has(value)))) {
    return "verified";
  }
  const awaiting = AWAITING.has(status) || Boolean(item?.checked_off) || records.some((value) => AWAITING.has(value));
  if (awaiting) {
    if (item?.verification_required === false && status === "completed" && !records.includes("pending_approval")) {
      return "verified";
    }
    return "awaiting";
  }
  return "incomplete";
}

export function pendingSectionActivityIds(items) {
  const ids = [];
  const seen = new Set();
  for (const item of items || []) {
    if (item?.required === false) continue;
    const candidates = [];
    for (const record of item?.records || []) {
      if (String(record?.status || "") === "pending_approval") candidates.push(record.activity_id);
    }
    if (String(item?.status || "") === "pending_approval") {
      candidates.push(item.child_activity_id || item.id);
    }
    for (const raw of candidates) {
      if (raw == null || raw === "") continue;
      const id = Number(raw);
      if (!seen.has(id)) {
        seen.add(id);
        ids.push(id);
      }
    }
  }
  return ids;
}

export function sectionRollups(items) {
  const groups = new Map();
  for (const item of items || []) {
    const label = String(item?.section_label || "").trim() || "Checklist";
    const order = Number(item?.section_order || 0);
    const key = `${order}::${label}`;
    if (!groups.has(key)) groups.set(key, { label, order, items: [] });
    groups.get(key).items.push(item);
  }
  return [...groups.values()]
    .sort((a, b) => a.order - b.order || a.label.localeCompare(b.label))
    .map((group) => {
      const buckets = group.items.map(itemSectionBucket).filter(Boolean);
      let status = "verified";
      if (!buckets.length) status = "verified";
      else if (buckets.includes("rejected")) status = "needs_correction";
      else if (buckets.includes("incomplete")) status = "in_progress";
      else if (buckets.includes("awaiting")) status = "pending_verification";
      return {
        section_label: group.label,
        section_order: group.order,
        status,
        status_label: SECTION_LABELS[status],
        pending_activity_ids: pendingSectionActivityIds(group.items),
      };
    });
}
