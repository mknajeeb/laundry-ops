import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

export const WEEKLY_SCHEDULE_ROLES = [
  { value: "sort", label: "Sort" },
  { value: "wash", label: "Wash" },
  { value: "fold", label: "Fold" },
];

/** Role accents — distinct card fills, borders, and chip tints. */
export const ROLE_STYLES = {
  sort: {
    accent: VEEWASH_DASHBOARD.primaryBlueDark,
    bg: VEEWASH_DASHBOARD.primaryBlueLight,
    hoverBg: "#d9f0f5",
    chipBg: "#e0f4f8",
    border: VEEWASH_DASHBOARD.primaryBlueBorder,
    label: "Sort",
  },
  wash: {
    accent: VEEWASH_DASHBOARD.rushCopper,
    bg: VEEWASH_DASHBOARD.pendingLight,
    hoverBg: "#ffe8cc",
    chipBg: "#fff4e0",
    border: VEEWASH_DASHBOARD.pendingBorder,
    label: "Wash",
  },
  fold: {
    accent: VEEWASH_DASHBOARD.tealDark,
    bg: VEEWASH_DASHBOARD.tealLight,
    hoverBg: "#d4f2ed",
    chipBg: "#e4f7f3",
    border: VEEWASH_DASHBOARD.tealBorder,
    label: "Fold",
  },
  folder: {
    accent: VEEWASH_DASHBOARD.tealDark,
    bg: VEEWASH_DASHBOARD.tealLight,
    hoverBg: "#d4f2ed",
    chipBg: "#e4f7f3",
    border: VEEWASH_DASHBOARD.tealBorder,
    label: "Fold",
  },
  operator: {
    accent: VEEWASH_DASHBOARD.rushCopper,
    bg: VEEWASH_DASHBOARD.pendingLight,
    hoverBg: "#ffe8cc",
    chipBg: "#fff4e0",
    border: VEEWASH_DASHBOARD.pendingBorder,
    label: "Wash",
  },
};

export function parseEntryRoles(entry) {
  if (Array.isArray(entry?.roles) && entry.roles.length) {
    return entry.roles.map((r) => (r === "folder" ? "fold" : r));
  }
  const raw = String(entry?.role || "fold");
  return raw
    .split(",")
    .map((r) => r.trim())
    .map((r) => (r === "folder" ? "fold" : r))
    .filter(Boolean);
}

export function primaryRoleStyle(entry) {
  const roles = parseEntryRoles(entry);
  const key = roles[0] || "fold";
  return ROLE_STYLES[key] || ROLE_STYLES.fold;
}

export function roleStripeGradient(roles) {
  const keys = roles.length ? roles : ["fold"];
  const colors = keys.map((k) => (ROLE_STYLES[k] || ROLE_STYLES.fold).accent);
  if (colors.length === 1) return colors[0];
  const step = 100 / colors.length;
  const stops = colors.map((c, i) => `${c} ${i * step}%, ${c} ${(i + 1) * step}%`).join(", ");
  return `linear-gradient(180deg, ${stops})`;
}

export function roleLabels(roles) {
  return roles.map((r) => ROLE_STYLES[r]?.label || r).join(" · ");
}
