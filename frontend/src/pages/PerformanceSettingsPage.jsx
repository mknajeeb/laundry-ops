import { Box, Divider, Stack, Typography } from "@mui/material";
import { Link as RouterLink } from "react-router-dom";
import FoldingBenchmarksPanel from "../components/folding/FoldingBenchmarksPanel";
import FoldingExceptionRulesPanel from "../components/folding/FoldingExceptionRulesPanel";
import ProcessingSettingsPanel from "../components/folding/ProcessingSettingsPanel";

function SettingsNav() {
  const links = [
    { to: "/performance", label: "Dashboard" },
    { to: "/performance/settings", label: "Settings" },
    { to: "/performance/user-mapping", label: "User mapping" },
    { to: "/performance/backfill", label: "Backfill" },
  ];
  return (
    <Stack direction="row" spacing={2} flexWrap="wrap" sx={{ mb: 3 }}>
      {links.map(({ to, label }) => (
        <Typography key={to} component={RouterLink} to={to} variant="body2" sx={{ textDecoration: "none", fontWeight: 600 }}>
          {label}
        </Typography>
      ))}
    </Stack>
  );
}

function SettingsSection({ title, description, children }) {
  return (
    <Box>
      <Typography variant="h6" fontWeight={700} gutterBottom>{title}</Typography>
      {description ? (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>{description}</Typography>
      ) : null}
      {children}
    </Box>
  );
}

export default function PerformanceSettingsPage() {
  return (
    <Box sx={{ p: { xs: 2, md: 3 }, maxWidth: 1200, mx: "auto" }}>
      <Typography variant="h4" fontWeight={800} gutterBottom>Performance Settings</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Parameters, benchmarks, exception thresholds, and lifecycle timing assumptions.
      </Typography>
      <SettingsNav />
      <Stack spacing={4} divider={<Divider flexItem />}>
        <SettingsSection
          title="Lifecycle timing & processing assumptions"
          description="Default wash/dry durations, reject windows, and per-bag processing time estimates."
        >
          <ProcessingSettingsPanel />
        </SettingsSection>
        <SettingsSection
          title="Exception thresholds"
          description="Rules for folding scan conflicts, clean-rack timing, and operational exceptions."
        >
          <FoldingExceptionRulesPanel />
        </SettingsSection>
        <SettingsSection
          title="Benchmarks & quality targets"
          description="Team speed targets and issue-free quality goals for scoring."
        >
          <FoldingBenchmarksPanel />
        </SettingsSection>
      </Stack>
    </Box>
  );
}
