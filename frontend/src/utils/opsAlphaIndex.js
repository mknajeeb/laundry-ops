/**
 * Shared A–Z section styling for checkout / orders lists.
 * Colors are keyed by LETTER so A is always the same hue (workers learn the color for their letter).
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

/** Same color for the same letter every time (A–Z); '#' maps to a stable slot. */
export function getOpsAlphaPaletteForLetter(alpha) {
  const u = String(alpha || "#").toUpperCase().trim();
  let slot = 0;
  if (u.length === 1 && u >= "A" && u <= "Z") {
    slot = u.charCodeAt(0) - 65;
  } else {
    slot = 7;
  }
  return getOpsAlphaPalette(slot);
}

/** Empty section: still clearly visible; only a light cue that there are zero bags. */
export function opsAlphaEmptySectionSx(count) {
  if (count > 0) return {};
  return {
    borderStyle: "dashed",
    bgcolor: "rgba(248, 250, 252, 0.75)",
  };
}
