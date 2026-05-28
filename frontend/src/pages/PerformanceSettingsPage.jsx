import { Box, Stack, Typography } from "@mui/material";
import { Link as RouterLink } from "react-router-dom";
import FoldingBenchmarksPanel from "../components/folding/FoldingBenchmarksPanel";
import FoldingExceptionRulesPanel from "../components/folding/FoldingExceptionRulesPanel";
import ProcessingSettingsPanel from "../components/folding/ProcessingSettingsPanel";

function SettingsNav() {
  const links = [
    { to: "/performance/settings", label: "Settings" },
    { to: "/performance/user-mapping", label: "User mapping & excluded users" },
    { to: "/performance/backfill", label: "Backfill / recompute" },
    { to: "/performance", label: "Dashboard" },
  ];
  return (
    <Stack direction="row" spacing={2} flexWrap="wrap" sx={{ mb: 3 }}>
      {links.map(({ to, label }) => (
        <Typography key={to} component={RouterLink} to={to} variant="body2" sx={{ textDecoration: "none" }}>
          {label}
        </Typography>
      ))}
    </Stack>
  );
}

export default function PerformanceSettingsPage() {
  return (
    <Box sx={{ p: { xs: 2, md: 3 }, maxWidth: 1200, mx: "auto" }}>
      <Typography variant="h4" fontWeight={800} gutterBottom>Performance Settings</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Exception thresholds, processing assumptions, reject limits, and performance benchmarks.
      </Typography>
      <SettingsNav />
      <Stack spacing={3}>
        <ProcessingSettingsPanel />
        <FoldingExceptionRulesPanel />
        <FoldingBenchmarksPanel />
      </Stack>
    </Box>
  );
}
