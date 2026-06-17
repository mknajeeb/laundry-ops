import { Box, Typography } from "@mui/material";
import { formatLbs } from "../../utils/foldingFormat";
import { getBagWeightParts, shouldShowBagWeightSummary } from "../../utils/shiftMonitorHelpers";

function WeightSegment({ label, value, suffix = " lbs" }) {
  return (
    <>
      {label}:{" "}
      <Box component="span" fontWeight={600} color="text.primary">
        {value != null ? `${formatLbs(value)}${suffix}` : "—"}
      </Box>
    </>
  );
}

/** Inline pre-clean / post-clean / weight difference for bag list cards. */
export default function BagWeightSummary({ row, sx }) {
  if (!shouldShowBagWeightSummary(row)) return null;
  const { pre, post, delta } = getBagWeightParts(row);

  return (
    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, ...sx }}>
      <WeightSegment label="Pre-clean" value={pre} />
      {" · "}
      <WeightSegment label="Post-clean" value={post} />
      {" · "}
      <WeightSegment label="Diff" value={delta} />
    </Typography>
  );
}
