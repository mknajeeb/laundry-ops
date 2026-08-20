/**
 * Canonical Team Status / Mobile Ops role color mapping.
 *
 * Colors attach to semantic role keys (wash_dry / sort / fold / break),
 * never to translated display strings. Resolve via role_code or English
 * canonical labels (Wash-Dry, Sort, Fold) before localizing text.
 */

export const TEAM_ROLE_COLOR_KEYS = Object.freeze({
  WASH_DRY: "wash_dry",
  SORT: "sort",
  FOLD: "fold",
  BREAK: "break",
});

/** Accessible light-surface / dark-text pairs + accent for edges/dots. */
export const TEAM_ROLE_COLORS = Object.freeze({
  wash_dry: Object.freeze({
    key: "wash_dry",
    /** VeeWash blue family — brighter than OPS navy text (#16192b) for scan */
    accent: "#4865ee",
    bg: "#e8ecff",
    text: "#1e2f8a",
    border: "#a8b6f0",
  }),
  sort: Object.freeze({
    key: "sort",
    /** VeeWash gold family */
    accent: "#b0892d",
    bg: "#f5edd8",
    text: "#5c4510",
    border: "#e0c98a",
  }),
  fold: Object.freeze({
    key: "fold",
    /** Teal that fits VeeWash palette */
    accent: "#0f766e",
    bg: "#e4f3f0",
    text: "#0b4f49",
    border: "#9dcdc6",
  }),
  break: Object.freeze({
    key: "break",
    /** Neutral gray — not OT amber/red */
    accent: "#64748b",
    bg: "#eef1f4",
    text: "#334155",
    border: "#cbd5e1",
  }),
});

const FALLBACK = Object.freeze({
  key: "other",
  accent: "#64748b",
  bg: "#f1f5f9",
  text: "#334155",
  border: "#cbd5e1",
});

/** English + known aliases → semantic key (not locale-dependent). */
const LABEL_TO_KEY = Object.freeze({
  "wash-dry": "wash_dry",
  "wash dry": "wash_dry",
  wash_dry: "wash_dry",
  wash: "wash_dry",
  operator: "wash_dry",
  pt_washer: "wash_dry",
  sort: "sort",
  sorting: "sort",
  sorter: "sort",
  pt_sorter: "sort",
  fold: "fold",
  folder: "fold",
  folding: "fold",
  pt_folder: "fold",
  break: "break",
  "on break": "break",
  descanso: "break",
});

const CODE_TO_KEY = Object.freeze({
  OPERATOR: "wash_dry",
  SORT: "sort",
  FOLDER: "fold",
  FOLD: "fold",
});

/**
 * Resolve semantic role color key from codes/labels/kind.
 * Prefer role_code; fall back to English canonical label aliases.
 */
export function resolveTeamRoleColorKey({
  roleCode = null,
  roleLabel = null,
  kind = null,
  label = null,
} = {}) {
  const kindNorm = String(kind || "").trim().toLowerCase();
  if (kindNorm === "break" || kindNorm === "on_break") return TEAM_ROLE_COLOR_KEYS.BREAK;

  const code = String(roleCode || "").trim().toUpperCase();
  if (code && CODE_TO_KEY[code]) return CODE_TO_KEY[code];

  const raw = String(roleLabel || label || "").trim();
  if (!raw) return null;

  // "Wash-Dry | Rinse Wash & Fold" → first segment
  const head = raw.split("|")[0].trim().toLowerCase();
  if (LABEL_TO_KEY[head]) return LABEL_TO_KEY[head];

  // Multi-role chip strings like "Wash-Dry"
  const compact = head.replace(/\s+/g, " ");
  if (LABEL_TO_KEY[compact]) return LABEL_TO_KEY[compact];

  return null;
}

export function teamRoleColors(input = {}) {
  const key =
    typeof input === "string"
      ? resolveTeamRoleColorKey({ roleLabel: input })
      : resolveTeamRoleColorKey(input);
  if (key && TEAM_ROLE_COLORS[key]) return TEAM_ROLE_COLORS[key];
  return FALLBACK;
}

/** MUI sx helpers for compact chips. */
export function teamRoleChipSx(input = {}, { size = "sm" } = {}) {
  const c = teamRoleColors(input);
  const compact = size === "sm";
  return {
    height: compact ? 20 : 24,
    fontSize: compact ? "0.68rem" : "0.74rem",
    fontWeight: 850,
    bgcolor: c.bg,
    color: c.text,
    border: `1px solid ${c.border}`,
    "& .MuiChip-label": { px: compact ? 0.7 : 0.85 },
  };
}

export function teamRoleEdgeSx(input = {}) {
  const c = teamRoleColors(input);
  return {
    borderLeft: `3px solid ${c.accent}`,
  };
}
