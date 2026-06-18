import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

export const WEEKLY_SCHEDULE_ROLES = [
  { value: "sort", label: "Sort" },
  { value: "wash", label: "Wash" },
  { value: "fold", label: "Fold" },
];

export const ROLE_STYLES = {
  sort: {
    accent: VEEWASH_DASHBOARD.rushCopper,
    bg: VEEWASH_DASHBOARD.rushBg,
    border: VEEWASH_DASHBOARD.rushBorder,
    label: "Sort",
  },
  wash: {
    accent: VEEWASH_DASHBOARD.primaryBlue,
    bg: VEEWASH_DASHBOARD.primaryBlueLight,
    border: VEEWASH_DASHBOARD.primaryBlueBorder,
    label: "Wash",
  },
  fold: {
    accent: VEEWASH_DASHBOARD.teal,
    bg: VEEWASH_DASHBOARD.tealLight,
    border: VEEWASH_DASHBOARD.tealBorder,
    label: "Fold",
  },
  // Legacy aliases for older stored rows
  folder: {
    accent: VEEWASH_DASHBOARD.teal,
    bg: VEEWASH_DASHBOARD.tealLight,
    border: VEEWASH_DASHBOARD.tealBorder,
    label: "Fold",
  },
  operator: {
    accent: VEEWASH_DASHBOARD.primaryBlue,
    bg: VEEWASH_DASHBOARD.primaryBlueLight,
    border: VEEWASH_DASHBOARD.primaryBlueBorder,
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
