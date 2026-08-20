import { Box, Typography } from "@mui/material";
import { fmtMoney } from "./revenueFormat";

/** Compact DHS account row for account-first list. */
export default function DhsAccountRow({ account, onClick, needsEntryLabel = "Needs entry" }) {
  const entered = Boolean(account?.entered);
  const lbs = account?.volume;
  const rev = account?.revenue;
  const proc = account?.processing_date;

  let secondary = needsEntryLabel;
  if (entered) {
    const parts = [];
    if (lbs != null) parts.push(`${Number(lbs).toLocaleString()} lb`);
    parts.push(fmtMoney(rev));
    secondary = parts.join(" · ");
  }

  return (
    <Box
      component="button"
      type="button"
      onClick={onClick}
      sx={{
        display: "block",
        width: "100%",
        textAlign: "left",
        m: 0,
        p: 1.5,
        borderRadius: 2,
        border: "1px solid #e5e7eb",
        bgcolor: "#fff",
        cursor: "pointer",
        appearance: "none",
        fontFamily: "inherit",
        "&:active": { bgcolor: "#F6FAFB" },
      }}
    >
      <Typography sx={{ fontWeight: 900, fontSize: 16 }}>{account?.name}</Typography>
      <Typography sx={{ mt: 0.35, fontSize: 13, fontWeight: 600, color: entered ? "#0f766e" : "#d97706" }}>
        {secondary}
      </Typography>
      {entered && proc ? (
        <Typography sx={{ mt: 0.2, fontSize: 12, color: "#64748b" }}>
          Processing {proc}
        </Typography>
      ) : null}
    </Box>
  );
}
