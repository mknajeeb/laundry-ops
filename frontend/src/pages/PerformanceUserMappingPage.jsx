import { Box, Typography } from "@mui/material";
import FoldingMaintenancePanel from "../components/folding/FoldingMaintenancePanel";

export default function PerformanceUserMappingPage() {
  return (
    <Box sx={{ p: { xs: 2, md: 3 }, maxWidth: 1200, mx: "auto" }}>
      <Typography variant="h4" fontWeight={800} gutterBottom>Performance User Mapping</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Map Rinse operators to clock/payroll users. Unmapped users still appear in dashboards as Unmapped.
      </Typography>
      <FoldingMaintenancePanel sections={["user_mapping", "excluded_users"]} />
    </Box>
  );
}
