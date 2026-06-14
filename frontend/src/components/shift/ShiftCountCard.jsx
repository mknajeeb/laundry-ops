import { Paper, Typography } from "@mui/material";
import { KPI_VARIANT_STYLES, VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

const SIZE_STYLES = {
  kpi: {
    p: 1.75,
    minHeight: 94,
    valueVariant: "h4",
    labelVariant: "caption",
  },
  default: {
    p: 1.2,
    minHeight: 70,
    valueVariant: "h5",
    labelVariant: "caption",
  },
  snapshot: {
    p: 0.9,
    minHeight: 58,
    valueVariant: "h6",
    labelVariant: "caption",
  },
};

export default function ShiftCountCard({
  label,
  value,
  sub,
  onClick,
  active,
  warn,
  compact,
  disabled,
  subPreLine,
  variant = "default",
  large = false,
  size,
}) {
  if (disabled) return null;
  const display = value ?? "—";
  const vStyle = KPI_VARIANT_STYLES[variant] || KPI_VARIANT_STYLES.snapshot;
  const accent = warn ? "error.main" : vStyle.accent;
  const borderColor = active ? VEEWASH_DASHBOARD.primaryBlue : warn ? "error.main" : vStyle.border;
  const bg = active ? VEEWASH_DASHBOARD.primaryBlueLight : vStyle.bg;
  const resolvedSize = size || (large ? "kpi" : compact ? "snapshot" : "default");
  const sz = SIZE_STYLES[resolvedSize] || SIZE_STYLES.default;
  const borderWidth = vStyle.borderWidth || 2;

  return (
    <Paper
      elevation={0}
      onClick={onClick}
      sx={{
        p: sz.p,
        borderRadius: 2.5,
        border: `${borderWidth}px solid`,
        borderColor,
        cursor: onClick ? "pointer" : "default",
        bgcolor: bg,
        minHeight: sz.minHeight,
        minWidth: 0,
        boxShadow: resolvedSize === "kpi" ? "0 2px 10px rgba(0, 60, 80, 0.1)" : VEEWASH_DASHBOARD.cardShadow,
        transition: "border-color 0.15s ease, box-shadow 0.15s ease, transform 0.15s ease",
        "&:hover": onClick
          ? {
              boxShadow: "0 4px 14px rgba(0, 60, 80, 0.14)",
              borderColor: variant === "pending" ? VEEWASH_DASHBOARD.pendingDark : VEEWASH_DASHBOARD.primaryBlue,
              transform: resolvedSize === "kpi" ? "translateY(-1px)" : undefined,
            }
          : undefined,
      }}
    >
      <Typography
        variant={sz.valueVariant}
        fontWeight={800}
        lineHeight={1.05}
        color={accent}
        sx={{ fontSize: resolvedSize === "kpi" ? { xs: "1.55rem", sm: "1.75rem" } : undefined }}
      >
        {display}
      </Typography>
      <Typography
        variant={sz.labelVariant}
        fontWeight={700}
        display="block"
        sx={{ mt: 0.5, color: variant === "pending" ? VEEWASH_DASHBOARD.pendingDark : "text.secondary", fontWeight: 600 }}
      >
        {label}
      </Typography>
      {sub ? (
        <Typography
          variant="caption"
          color="text.secondary"
          display="block"
          sx={{ mt: 0.25, whiteSpace: subPreLine ? "pre-line" : undefined, lineHeight: 1.35 }}
        >
          {sub}
        </Typography>
      ) : null}
    </Paper>
  );
}
