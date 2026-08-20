import { Box, Button, Stack, Typography } from "@mui/material";

const STATUS_TONE = {
  entered: "#0f766e",
  no_activity: "#64748b",
  missing: "#d97706",
};

function labelFor(status) {
  if (status === "entered") return "✓";
  if (status === "no_activity") return "No Activity";
  return "Missing";
}

/**
 * Daily completeness strip (SS / Drop Off / WF / HD).
 */
export default function DailyCompletenessStrip({
  completeness,
  onOpenSection,
  onNoActivity,
}) {
  const sections = completeness?.sections || [];
  if (!sections.length) return null;
  return (
    <Box
      sx={{
        p: 1.5,
        borderRadius: 2,
        border: "1px solid rgba(0,151,178,0.28)",
        bgcolor: "#fff",
      }}
    >
      <Typography sx={{ fontSize: 11, fontWeight: 800, letterSpacing: 0.5, color: "#64748b", textTransform: "uppercase" }}>
        Daily Entry · {completeness.processing_date_et}
      </Typography>
      <Typography sx={{ mt: 0.25, fontWeight: 900, fontSize: 16, color: "#0f172a" }}>
        {completeness.label} complete
      </Typography>
      <Stack spacing={0.75} sx={{ mt: 1 }}>
        {sections.map((s) => (
          <Box
            key={s.key}
            sx={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: 1,
            }}
          >
            <Button
              size="small"
              onClick={() => onOpenSection?.(s)}
              sx={{ textTransform: "none", fontWeight: 800, color: "#0f172a", justifyContent: "flex-start" }}
            >
              {s.label}
            </Button>
            <Stack direction="row" spacing={0.75} alignItems="center">
              <Typography sx={{ fontSize: 12, fontWeight: 800, color: STATUS_TONE[s.status] || "#64748b" }}>
                {labelFor(s.status)}
              </Typography>
              {s.status === "missing" && onNoActivity ? (
                <Button
                  size="small"
                  variant="text"
                  onClick={() => onNoActivity?.(s)}
                  sx={{ textTransform: "none", fontSize: 11 }}
                >
                  No Activity
                </Button>
              ) : null}
            </Stack>
          </Box>
        ))}
      </Stack>
    </Box>
  );
}
