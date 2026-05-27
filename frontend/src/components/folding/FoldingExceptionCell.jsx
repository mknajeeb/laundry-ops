import { Box, Typography } from "@mui/material";
import {
  formatExceptionDisplay,
  warningExceptionLabels,
} from "../../utils/foldingExceptionDisplay";
import { foldingExceptionLabel } from "../../utils/foldingExceptionLabels";

/** Primary exception code + optional secondary warnings for table cells. */
export default function FoldingExceptionCell({ row, compact = false }) {
  const { primary, warnings } = formatExceptionDisplay(row);
  if (!primary && warnings.length === 0) {
    return <Typography variant="body2" color="text.secondary">—</Typography>;
  }

  const warnLabels = warningExceptionLabels(row);

  return (
    <Box>
      {primary ? (
        <Typography variant="body2" fontWeight={600} sx={{ fontFamily: "monospace", fontSize: compact ? 11 : 12 }}>
          {foldingExceptionLabel(primary)}
        </Typography>
      ) : null}
      {warnLabels.length > 0 ? (
        <Typography
          variant="caption"
          color="text.secondary"
          display="block"
          sx={{ mt: primary ? 0.25 : 0, fontFamily: "monospace", fontSize: 10 }}
        >
          {primary ? "Warnings: " : ""}
          {warnLabels.map((w) => w.label).join(", ")}
        </Typography>
      ) : null}
    </Box>
  );
}
