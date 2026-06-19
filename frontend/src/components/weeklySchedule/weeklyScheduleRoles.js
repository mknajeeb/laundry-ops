import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

export const WEEKLY_SCHEDULE_ROLES = [
  { value: "sort", label: "Sort" },
  { value: "wash", label: "Wash" },
  { value: "fold", label: "Fold" },
];

/** Subtle role accents — left-bar + chip tint, not full card fills. */
export const ROLE_STYLES = {
  sort: {
    accent: VEEWASH_DASHBOARD.primaryBlueDark,
    bg: "#ffffff",
    chipBg: "#f0f9fb",
    border: "rgba(0, 122, 145, 0.22)",
    label: "Sort",
  },
  wash: {
    accent: VEEWASH_DASHBOARD.rushCopper,
    bg: "#ffffff",
    chipBg: "#fffaf3",
    border: "rgba(180, 83, 9, 0.22)",
    label: "Wash",
  },
  fold: {
    accent: VEEWASH_DASHBOARD.tealDark,
    bg: "#ffffff",
    chipBg: "#f2faf8",
    border: "rgba(0, 143, 127, 0.22)",
    label: "Fold",
  },
  folder: {
    accent: VEEWASH_DASHBOARD.tealDark,
    bg: "#ffffff",
    chipBg: "#f2faf8",
    border: "rgba(0, 143, 127, 0.22)",
    label: "Fold",
  },
  operator: {
    accent: VEEWASH_DASHBOARD.rushCopper,
    bg: "#ffffff",
    chipBg: "#fffaf3",
    border: "rgba(180, 83, 9, 0.22)",
    label: "Wash",
  },
};

export function parseEntryRoles(entry) {
  if (Array.isArray(entry?.roles) && entry.roles.length) {
    return entry.roles;
  }
  const raw = String(entry?.role || "fold");
  return raw
    .split(",")
    .map((r) => r.trim())
    .filter(Boolean);
}

export function primaryRoleStyle(entry) {
  const roles = parseEntryRoles(entry);
  const key = roles[0] || "fold";
  return ROLE_STYLES[key] || ROLE_STYLES.fold;
}

export function roleLabels(roles) {
  return roles.map((r) => ROLE_STYLES[r]?.label || r).join(" · ");
}
