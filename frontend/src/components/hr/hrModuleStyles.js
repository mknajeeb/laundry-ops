import { alpha } from "@mui/material/styles";

/**
 * Shared layout tokens for HR Documents + Forms hub (dashboard-style density, consistent radii).
 */
export const hrModule = {
  pageCanvas: (theme) => ({
    minHeight: "100%",
    bgcolor: theme.palette.mode === "dark" ? theme.palette.background.default : theme.palette.grey[50],
    pb: { xs: 3, md: 5 },
  }),
  contentMax: { maxWidth: 1280, mx: "auto", px: { xs: 1.5, sm: 2, md: 3 }, pt: { xs: 2, md: 3 } },
  hero: (theme) => ({
    position: "relative",
    borderRadius: 3,
    p: { xs: 2.5, md: 3.5 },
    mb: 2.5,
    overflow: "hidden",
    color: theme.palette.primary.contrastText,
    background: `linear-gradient(135deg, ${theme.palette.primary.dark} 0%, ${theme.palette.primary.main} 48%, ${alpha(
      theme.palette.primary.light,
      0.92,
    )} 100%)`,
    boxShadow:
      theme.palette.mode === "dark"
        ? "0 12px 40px rgba(0,0,0,0.35)"
        : "0 12px 40px rgba(15, 23, 42, 0.12)",
  }),
  heroOverline: {
    fontWeight: 700,
    letterSpacing: "0.12em",
    opacity: 0.9,
    fontSize: "0.7rem",
    textTransform: "uppercase",
  },
  heroTitle: {
    fontWeight: 800,
    letterSpacing: "-0.03em",
    lineHeight: 1.15,
    my: 0.5,
  },
  heroSubtitle: { opacity: 0.92, maxWidth: 720, lineHeight: 1.6 },
  filterBar: (theme) => ({
    p: 2,
    borderRadius: 3,
    border: `1px solid ${theme.palette.divider}`,
    bgcolor: theme.palette.background.paper,
    boxShadow: theme.palette.mode === "dark" ? "none" : "0 1px 3px rgba(15,23,42,0.06)",
  }),
  tableCard: (theme) => ({
    borderRadius: 3,
    border: `1px solid ${theme.palette.divider}`,
    bgcolor: theme.palette.background.paper,
    overflow: "hidden",
    boxShadow: theme.palette.mode === "dark" ? "none" : "0 1px 3px rgba(15,23,42,0.06)",
  }),
  tableHeadCell: (theme) => ({
    fontWeight: 700,
    fontSize: "0.75rem",
    letterSpacing: "0.04em",
    textTransform: "uppercase",
    color: theme.palette.text.secondary,
    bgcolor: theme.palette.mode === "dark" ? "rgba(255,255,255,0.04)" : theme.palette.grey[100],
    borderBottom: `2px solid ${theme.palette.divider}`,
    py: 1.25,
    whiteSpace: "nowrap",
  }),
  rowHover: {
    transition: "background-color 0.15s ease",
    "&:hover": { bgcolor: "action.hover" },
  },
  tabs: (theme) => ({
    minHeight: 48,
    px: 1,
    bgcolor: theme.palette.mode === "dark" ? "rgba(255,255,255,0.03)" : theme.palette.grey[50],
    borderBottom: `1px solid ${theme.palette.divider}`,
    "& .MuiTab-root": { fontWeight: 600, textTransform: "none", fontSize: "0.95rem" },
  }),
  statChip: (theme) => ({
    bgcolor: "rgba(255,255,255,0.18)",
    color: "inherit",
    fontWeight: 600,
    border: "1px solid rgba(255,255,255,0.35)",
  }),
};
