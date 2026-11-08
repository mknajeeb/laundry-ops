export const LOST_FOUND_ACTIVITY_CODE = "custom_lost_found_reconciliation";

export function veewashIssueCatalog() {
  const range = (prefix, count) => Array.from({ length: count }, (_, index) => `${prefix}${index + 1}`);
  return {
    washers: range("W", 44),
    dryers: range("D", 40),
    folding_tables: range("F", 20),
    dehumidifiers: [],
    redry_pockets: [],
  };
}

export const FOUND_LOCATION_KINDS = [
  "washer",
  "dryer",
  "folding_table",
  "floor",
  "cart",
  "other",
];

const NUMBER_REQUIRED = new Set(["washer", "dryer", "folding_table"]);

export function locationNumberMode(kind) {
  if (NUMBER_REQUIRED.has(kind)) return "required";
  if (kind === "cart") return "optional";
  if (kind === "other") return "detail";
  return "none";
}

export function identifierChoices(kind, choices) {
  if (kind === "washer") return choices?.washers || [];
  if (kind === "dryer") return choices?.dryers || [];
  if (kind === "folding_table") return choices?.folding_tables || [];
  if (kind === "dehumidifier") return choices?.dehumidifiers || [];
  return [];
}

export function filterIdentifiers(options, query) {
  const needle = String(query || "").trim().toLowerCase();
  const list = options || [];
  if (!needle) return list;
  return list.filter((id) => String(id).toLowerCase().includes(needle));
}

let photoSeq = 0;

export function addReportPhotos(current, incoming, limit = 6) {
  const next = Array.isArray(current) ? [...current] : [];
  for (const file of Array.from(incoming || [])) {
    if (!file || file.size <= 0) continue;
    if (file.type && !String(file.type).startsWith("image/")) continue;
    photoSeq += 1;
    next.push({ id: `photo-${photoSeq}`, file });
    if (next.length >= limit) break;
  }
  return next.slice(0, limit);
}

export function removeReportPhoto(current, id) {
  return (current || []).filter((photo) => photo.id !== id);
}

export function replaceReportPhoto(current, id, file) {
  if (!file || file.size <= 0) return current || [];
  if (file.type && !String(file.type).startsWith("image/")) return current || [];
  return (current || []).map((photo) => (photo.id === id ? { ...photo, file } : photo));
}

export function validateFoundLocation({ kind, number, detail }) {
  const token = String(number || "").trim();
  const note = String(detail || "").trim();
  if (!FOUND_LOCATION_KINDS.includes(kind)) return "invalid_location";
  if (NUMBER_REQUIRED.has(kind) && !token) return "location_number_required";
  if (kind === "other" && note.length < 2) return "location_detail_required";
  return "";
}

export function displayFoundLocation(item, t) {
  const kind = String(item?.location_kind || "");
  const number = String(item?.location_number || "").trim();
  const detail = String(item?.location_detail || "").trim();
  const stored = String(item?.location_label || "");
  if (typeof t !== "function" || !kind) return stored;
  const name = t(`lostFound.location.${kind}`);
  if (!name || name === `lostFound.location.${kind}`) return stored;
  if (kind === "other") return detail || stored;
  if (kind === "floor" || !number) return name;
  return `${name} ${number}`;
}

export function displayFoundEvent(eventType, t) {
  const code = String(eventType || "");
  const key = `lostFound.event.${code}`;
  if (typeof t !== "function" || !code) return code;
  const label = t(key);
  return label && label !== key ? label : code;
}

export function foundLocationLabel({ kind, number, detail }) {
  const token = String(number || "").trim();
  const note = String(detail || "").trim();
  const titles = {
    washer: "Washer",
    dryer: "Dryer",
    folding_table: "Folding Table",
    floor: "Floor",
    cart: "Cart",
    other: note,
  };
  if (kind === "other") return note;
  if (!token || kind === "floor") return titles[kind] || "";
  return `${titles[kind]} ${token}`;
}
