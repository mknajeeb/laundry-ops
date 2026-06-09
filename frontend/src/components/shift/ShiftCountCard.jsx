import { Paper, Typography } from "@mui/material";

const ACCENT = "#0097b2";

export default function ShiftCountCard({ label, value, sub, onClick, active, warn, compact, disabled, subPreLine }) {
  if (disabled) return null;
  const display = value ?? "—";
  return (
    <Paper
      elevation={0}
      onClick={onClick}
      sx={{
        p: compact ? 1 : 1.25,
        borderRadius: 2,
        border: "2px solid",
        borderColor: active ? ACCENT : warn ? "error.main" : "divider",
        cursor: onClick ? "pointer" : "default",
        bgcolor: active ? "rgba(0,151,178,0.06)" : "background.paper",
        minHeight: compact ? 72 : 80,
        opacity: onClick ? 1 : 0.95,
      }}
    >
      <Typography variant={compact ? "h6" : "h5"} fontWeight={800} lineHeight={1.1} color={warn ? "error.main" : ACCENT}>
        {display}
      </Typography>
      <Typography variant="caption" fontWeight={700} display="block" sx={{ mt: 0.25 }}>
        {label}
      </Typography>
      {sub ? (
        <Typography variant="caption" color="text.secondary" display="block" sx={{ whiteSpace: subPreLine ? "pre-line" : undefined }}>
          {sub}
        </Typography>
      ) : null}
    </Paper>
  );
}
