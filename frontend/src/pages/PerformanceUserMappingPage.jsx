import { Box, Stack, Typography } from "@mui/material";
import { Link as RouterLink } from "react-router-dom";
import FoldingMaintenancePanel from "../components/folding/FoldingMaintenancePanel";

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
        <Typography key={to} component={RouterLink} to={to} variant="body2" sx={{ textDecoration: "none" }}>
          {label}
        </Typography>
      ))}
    </Stack>
  );
}

export default function PerformanceUserMappingPage() {
  return (
    <Box sx={{ p: { xs: 2, md: 3 }, maxWidth: 1200, mx: "auto" }}>
      <Typography variant="h4" fontWeight={800} gutterBottom>User Mapping &amp; Excluded Users</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Map Rinse scan operators to clock/payroll users, set each worker&apos;s employer (Rinse · VeeWash · Both) on
        their scheduling profile, and manage excluded users for leaderboard / TV scoring.
      </Typography>
      <SettingsNav />
      <FoldingMaintenancePanel sections={["employer_affiliation", "user_mapping", "excluded_users"]} />
    </Box>
  );
}
