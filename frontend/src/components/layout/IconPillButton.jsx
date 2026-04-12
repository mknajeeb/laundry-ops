import { Button, Tooltip } from "@mui/material";

/** Large touch-friendly icon-first control (floor / PWA). */
export default function IconPillButton({ title, icon, label, onClick, variant = "outlined", color = "primary", disabled }) {
  const inner = (
    <Button
      variant={variant}
      color={color}
      disabled={disabled}
      onClick={onClick}
      startIcon={icon}
      sx={{
        textTransform: "none",
        borderRadius: 999,
        minHeight: 48,
        minWidth: label ? undefined : 52,
        px: label ? 2 : 1.25,
        fontWeight: 600,
        fontSize: label ? "0.9rem" : "0.85rem",
      }}
    >
      {label || ""}
    </Button>
  );
  return title ? <Tooltip title={title}>{inner}</Tooltip> : inner;
}
