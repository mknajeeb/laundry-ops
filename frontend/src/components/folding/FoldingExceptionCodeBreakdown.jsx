import { Box, Chip, Stack, Typography } from "@mui/material";

export const FOLDING_EXCEPTION_CODES = [
  "FOLDING_DURATION_TOO_SHORT",
  "FOLDING_DURATION_TOO_LONG",
  "MULTIPLE_FOLDING_SCANS",
  "MULTIPLE_CLEAN_SCANS",
  "MISSING_FOLDING",
  "MISSING_CLEAN",
  "CLEAN_BEFORE_FOLDING",
];

/** @param {Record<string, number>|undefined} counts */
export function countsFromRows(rows) {
  const out = Object.fromEntries(FOLDING_EXCEPTION_CODES.map((c) => [c, 0]));
  for (const r of rows || []) {
    const code = String(r.exception_code || "").trim();
    if (code && code in out) out[code] += 1;
    else if (code) out[code] = (out[code] || 0) + 1;
  }
  return out;
}

export default function FoldingExceptionCodeBreakdown({
  title = "Exception breakdown",
  counts,
  dense = false,
}) {
  const c = counts || {};
  const total = FOLDING_EXCEPTION_CODES.reduce((s, k) => s + (c[k] || 0), 0);
  if (!total) return null;

  return (
    <Box sx={{ mb: dense ? 1 : 2 }}>
      <Typography variant="subtitle2" fontWeight={700} gutterBottom>
        {title}
      </Typography>
      <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
        {FOLDING_EXCEPTION_CODES.map((code) => {
          const n = c[code] || 0;
          if (!n) return null;
          return (
            <Chip
              key={code}
              size="small"
              variant="outlined"
              label={`${code}: ${n}`}
              sx={{ fontFamily: "monospace", fontSize: 11 }}
            />
          );
        })}
      </Stack>
    </Box>
  );
}
