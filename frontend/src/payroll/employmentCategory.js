/** Employment category helpers for Employee Profile and payroll UI. */

export const WORKER_CATEGORY_OPTIONS = [
  { value: "w2", label: "W-2" },
  { value: "contractor_1099", label: "1099" },
  { value: "temp", label: "Temp / One Time" },
  { value: "tryout", label: "Try Out" },
];

export const VENDOR_RECEIPT_CATEGORIES = new Set(["temp", "contractor_1099", "tryout"]);
export const CONVERT_TRYOUT_TARGETS = ["temp", "w2", "contractor_1099"];

export function classifyEmploymentCategory(cat) {
  const code = String(cat?.code || "").toUpperCase();
  const name = String(cat?.name || "").toLowerCase();
  if (code === "EC_SYSTEM") return "system";
  if (
    code === "EC_TRYOUT" ||
    code.includes("TRYOUT") ||
    code.includes("TRY_OUT") ||
    /\btry\s*out\b|\btryout\b/.test(name)
  ) {
    return "tryout";
  }
  if (code === "EC_TEMP" || (/\btemp\b|temporary|seasonal/.test(name) && !/\btry\s*out\b/.test(name))) {
    return "temp";
  }
  if (
    code === "EC_1099" ||
    code.includes("1099") ||
    name.includes("1099") ||
    name.includes("contractor")
  ) {
    return "contractor_1099";
  }
  return "w2";
}

export function categoryLabel(kind, fallback = "") {
  const found = WORKER_CATEGORY_OPTIONS.find((o) => o.value === kind);
  return found?.label || fallback || kind || "";
}

export function catalogLabel(cat) {
  if (!cat) return "";
  return categoryLabel(classifyEmploymentCategory(cat), cat.name || "");
}

export function isVendorReceiptCategory(kind) {
  return VENDOR_RECEIPT_CATEGORIES.has(String(kind || ""));
}

export function parseYmd(value) {
  const s = String(value || "").slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return "";
  return s;
}

export function formatYmdFriendly(value) {
  const s = parseYmd(value);
  if (!s) return "—";
  const [y, m, d] = s.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  if (Number.isNaN(dt.getTime())) return s;
  return dt.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export function currentAssignment(rows, onYmd) {
  const today =
    parseYmd(onYmd) ||
    (() => {
      const d = new Date();
      const y = d.getFullYear();
      const m = String(d.getMonth() + 1).padStart(2, "0");
      const day = String(d.getDate()).padStart(2, "0");
      return `${y}-${m}-${day}`;
    })();
  const covering = (rows || []).filter((r) => {
    const start = parseYmd(r.effective_from);
    const end = parseYmd(r.effective_to);
    if (start && start > today) return false;
    if (end && end < today) return false;
    return true;
  });
  const list = covering.length ? covering : rows || [];
  return [...list].sort((a, b) => {
    const as = parseYmd(a.effective_from);
    const bs = parseYmd(b.effective_from);
    if (as !== bs) return bs.localeCompare(as);
    return Number(b.id || 0) - Number(a.id || 0);
  })[0] || null;
}

export function previousAssignments(rows, current) {
  return (rows || []).filter((r) => r !== current && (r.employment_category_id || r.id));
}

export function validateTryOutDates(start, end) {
  const s = parseYmd(start);
  const e = parseYmd(end);
  if (!s || !e) return "Try Out requires a start date and an end date.";
  if (e < s) return "Try Out end date cannot be earlier than start date.";
  return null;
}

export function startDateLabel(kind) {
  if (kind === "w2") return "W-2 Start Date";
  if (kind === "contractor_1099") return "1099 Start Date";
  if (kind === "temp") return "Temp / One Time Start Date";
  if (kind === "tryout") return "Try Out Start Date";
  return "Start Date";
}

export function paymentVendorDisplayName(name) {
  const key = String(name || "").toLowerCase();
  if (key.includes("veewash")) return "VeeWash";
  if (key.includes("washmate")) return "Washmate";
  return String(name || "").trim();
}

export function emptyAssignmentRow() {
  return { employment_category_id: "", effective_from: "", effective_to: "" };
}

export function mapAssignmentRow(a) {
  return {
    id: a?.id,
    employment_category_id: a?.employment_category_id || "",
    effective_from: parseYmd(a?.effective_from),
    effective_to: parseYmd(a?.effective_to),
    code: a?.code || "",
    name: a?.name || "",
    worker_category: a?.worker_category || classifyEmploymentCategory(a),
  };
}
