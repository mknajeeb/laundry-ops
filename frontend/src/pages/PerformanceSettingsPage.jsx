import { Box, Stack, Typography } from "@mui/material";
import FoldingExceptionRulesPanel from "../components/folding/FoldingExceptionRulesPanel";
import ProcessingSettingsPanel from "../components/folding/ProcessingSettingsPanel";

export default function PerformanceSettingsPage() {
  return (
    <Box sx={{ p: { xs: 2, md: 3 }, maxWidth: 1200, mx: "auto" }}>
      <Typography variant="h4" fontWeight={800} gutterBottom>Performance Settings</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Exception rule thresholds and processing time assumptions.
      </Typography>
      <Stack spacing={3}>
        <FoldingExceptionRulesPanel />
        <ProcessingSettingsPanel />
      </Stack>
    </Box>
  );
}
