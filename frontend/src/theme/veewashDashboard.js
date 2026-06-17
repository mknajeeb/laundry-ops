/** VeeWash Shift Monitor dashboard color tokens — keep in sync across modules. */
export const VEEWASH_DASHBOARD = {
  primaryBlue: "#0097b2",
  primaryBlueDark: "#007a91",
  primaryBlueLight: "#e6f5f8",
  primaryBlueBorder: "rgba(0, 151, 178, 0.35)",
  teal: "#00a896",
  tealDark: "#008f7f",
  tealLight: "#e6f7f5",
  tealBorder: "rgba(0, 168, 150, 0.35)",
  pending: "#d97706",
  pendingDark: "#92400e",
  pendingLight: "#ffedd5",
  pendingBorder: "rgba(217, 119, 6, 0.65)",
  pageBackground: "#F6FAFB",
  workloadHeaderBg: "#0097B2",
  snapshotBg: "#f3f8fa",
  snapshotBorder: "rgba(0, 151, 178, 0.2)",
  monitoringBg: "#f4f4f5",
  monitoringBorder: "#e4e4e7",
  monitoringText: "#71717a",
  neutralTotal: "#0097b2",
  cardShadow: "0 1px 3px rgba(0, 60, 80, 0.08)",
  /** Wash & Fold — neutral black accent */
  wfCharcoal: "#1c1c1e",
  wfBg: "#f7f7f8",
  wfBorder: "rgba(28, 28, 30, 0.18)",
  /** Home Delivery — VeeWash teal */
  hdTeal: "#00a896",
  hdBg: "#e6f7f5",
  hdBorder: "rgba(0, 168, 150, 0.35)",
  /** Rush — warm copper accent, restrained */
  rushCopper: "#b45309",
  rushBg: "#fffbeb",
  rushBorder: "rgba(180, 83, 9, 0.38)",
};

export const KPI_VARIANT_STYLES = {
  total: {
    accent: VEEWASH_DASHBOARD.neutralTotal,
    bg: VEEWASH_DASHBOARD.primaryBlueLight,
    border: VEEWASH_DASHBOARD.primaryBlueBorder,
  },
  pending: {
    accent: VEEWASH_DASHBOARD.pending,
    bg: VEEWASH_DASHBOARD.pendingLight,
    border: VEEWASH_DASHBOARD.pendingBorder,
    borderWidth: 3,
  },
  completed: {
    accent: VEEWASH_DASHBOARD.teal,
    bg: VEEWASH_DASHBOARD.tealLight,
    border: VEEWASH_DASHBOARD.tealBorder,
    borderWidth: 2,
  },
  snapshot: {
    accent: VEEWASH_DASHBOARD.primaryBlueDark,
    bg: "#ffffff",
    border: VEEWASH_DASHBOARD.snapshotBorder,
  },
  info: {
    accent: VEEWASH_DASHBOARD.monitoringText,
    bg: VEEWASH_DASHBOARD.snapshotBg,
    border: VEEWASH_DASHBOARD.snapshotBorder,
  },
  monitoring: {
    accent: VEEWASH_DASHBOARD.monitoringText,
    bg: VEEWASH_DASHBOARD.monitoringBg,
    border: VEEWASH_DASHBOARD.monitoringBorder,
  },
  wf: {
    accent: VEEWASH_DASHBOARD.wfCharcoal,
    bg: VEEWASH_DASHBOARD.wfBg,
    border: VEEWASH_DASHBOARD.wfBorder,
    borderWidth: 2,
  },
  hd: {
    accent: VEEWASH_DASHBOARD.hdTeal,
    bg: VEEWASH_DASHBOARD.hdBg,
    border: VEEWASH_DASHBOARD.hdBorder,
    borderWidth: 2,
  },
  rush: {
    accent: VEEWASH_DASHBOARD.rushCopper,
    bg: VEEWASH_DASHBOARD.rushBg,
    border: VEEWASH_DASHBOARD.rushBorder,
    borderWidth: 2,
  },
};
