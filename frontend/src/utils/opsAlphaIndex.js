/**
 * Shared A–Z section styling for checkout / orders lists: color rotation + empty dimming.
 * Keep logic here so pages stay lean and updates stay one place.
 */

export const OPS_ALPHA_PALETTE = [
  { rowBg: "#eff6ff", chipBg: "#1d4ed8", chipColor: "#ffffff", border: "#93c5fd" },
  { rowBg: "#fffbeb", chipBg: "#b45309", chipColor: "#ffffff", border: "#fcd34d" },
  { rowBg: "#f0fdf4", chipBg: "#15803d", chipColor: "#ffffff", border: "#86efac" },
  { rowBg: "#fdf4ff", chipBg: "#a21caf", chipColor: "#ffffff", border: "#e879f9" },
  { rowBg: "#fff7ed", chipBg: "#c2410c", chipColor: "#ffffff", border: "#fdba74" },
  { rowBg: "#ecfeff", chipBg: "#0e7490", chipColor: "#ffffff", border: "#5eead4" },
  { rowBg: "#f5f3ff", chipBg: "#5b21b6", chipColor: "#ffffff", border: "#c4b5fd" },
  { rowBg: "#fef2f2", chipBg: "#b91c1c", chipColor: "#ffffff", border: "#fca5a5" },
];

export function getOpsAlphaPalette(index) {
  const n = OPS_ALPHA_PALETTE.length;
  return OPS_ALPHA_PALETTE[((index % n) + n) % n];
}

/** Strong dim for sections with zero bags — fast (no extra DOM). */
export function opsAlphaEmptySectionSx(count) {
  if (count > 0) return {};
  return {
    opacity: 0.14,
    filter: "grayscale(1)",
    pointerEvents: "auto",
  };
}
