import { Typography } from "@mui/material";

export default function SaveStatusChip({ state, labels }) {
  const text =
    state === "saving"
      ? labels?.saving || "Saving…"
      : state === "saved"
        ? labels?.saved || "Saved ✓"
        : state === "error"
          ? labels?.error || "Error"
          : "";
  if (!text) return null;
  const color =
    state === "saved" ? "#0f766e" : state === "error" ? "#b91c1c" : "#64748b";
  return (
    <Typography sx={{ fontSize: 13, fontWeight: 700, color }} aria-live="polite">
      {text}
    </Typography>
  );
}
