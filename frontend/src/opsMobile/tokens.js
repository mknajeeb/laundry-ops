/** Shared tokens for Operations mobile (PIN hub, tasks, inventory, role). */

export const OPS_MOBILE = {
  navy: "#16192b",
  blue: "#2d3d9c",
  cobalt: "#4865ee",
  cream: "#faf6e9",
  mist: "#eef2ff",
  surface: "#ffffff",
  muted: "#64748b",
  success: "#0f766e",
  danger: "#b91c1c",
  border: "rgba(22, 25, 43, 0.12)",
  /** Minimum primary touch target (px). */
  touchMin: 56,
  /** Launcher tile height. Stays above the 56px touch minimum and fits a 320px menu in two columns. */
  tileMinHeight: 84,
  radius: {
    card: 16,
    tile: 20,
    button: 14,
  },
  space: {
    xs: 8,
    sm: 12,
    md: 16,
    lg: 24,
  },
  type: {
    identity: "1.125rem",
    tileLabel: "1.05rem",
    title: "1.35rem",
  },
  /** Safe-area helpers for sticky chrome. */
  safeTop: "env(safe-area-inset-top, 0px)",
  safeBottom: "env(safe-area-inset-bottom, 0px)",
  safeLeft: "env(safe-area-inset-left, 0px)",
  safeRight: "env(safe-area-inset-right, 0px)",
};

export const opsMobilePageSx = {
  height: "100dvh",
  maxHeight: "100dvh",
  minHeight: 0,
  width: "100%",
  boxSizing: "border-box",
  bgcolor: OPS_MOBILE.mist,
  background: `linear-gradient(165deg, ${OPS_MOBILE.mist} 0%, #e8eeff 45%, rgba(72,101,238,0.12) 100%)`,
  overflow: "hidden",
};
