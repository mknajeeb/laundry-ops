/**
 * VeeWash brand tokens — UI + print/PDF forms.
 * Aligns with dashboard teal (#0097b2) and logo gold accent.
 */
export const VEEWASH_BRAND = {
  primary: "#0097b2",
  primaryDark: "#007a91",
  primaryLight: "#e6f5f8",
  primaryMuted: "rgba(0, 151, 178, 0.12)",
  teal: "#00a896",
  gold: "#c4a052",
  goldLight: "#f5eed8",
  ink: "#0f172a",
  inkMuted: "#475569",
  inkSoft: "#64748b",
  border: "rgba(0, 151, 178, 0.22)",
  borderSoft: "#e2e8f0",
  surface: "#ffffff",
  pageBg: "#f6fafb",
  gradient: "linear-gradient(135deg, #0097b2 0%, #007a91 55%, #005f73 100%)",
  shadow: "0 4px 24px rgba(0, 95, 115, 0.12)",
  radius: "10px",
  radiusSm: "6px",
};

/** Stable public URL for bundled VeeWash logo (print, PDF, kiosk, fallbacks). */
export const VEEWASH_LOGO_URL = "/assets/veewash-logo.png";

/** CSS custom properties block for print forms. */
export function veewashPrintCssVars() {
  const b = VEEWASH_BRAND;
  return `
    --vw-primary: ${b.primary};
    --vw-primary-dark: ${b.primaryDark};
    --vw-primary-light: ${b.primaryLight};
    --vw-teal: ${b.teal};
    --vw-gold: ${b.gold};
    --vw-ink: ${b.ink};
    --vw-ink-muted: ${b.inkMuted};
    --vw-border: ${b.border};
  `;
}
