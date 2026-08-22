import { useState } from "react";
import { Box, Stack, TextField, Typography } from "@mui/material";
import ManagementHubNav from "../components/management/ManagementHubNav";
import ManagementHdPerformanceSection from "../components/management/ManagementHdPerformanceSection";
import ManagementWfFolderPerformanceSection from "../components/management/ManagementWfFolderPerformanceSection";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";

function todayEtIso() {
  try {
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: "America/New_York",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date());
  } catch {
    return new Date().toISOString().slice(0, 10);
  }
}

/**
 * Management → Performance compartment.
 * WF Folder + HD wash/fold attribution (mobile-first).
 */
export default function ManagementPerformancePage() {
  const [dateEt, setDateEt] = useState(todayEtIso);

  return (
    <Box
      sx={{
        minHeight: "100dvh",
        bgcolor: VEEWASH_DASHBOARD.pageBg || "#f8fafc",
        pb: 4,
      }}
    >
      <ManagementHubNav activeId="performance" />
      <Box sx={{ px: { xs: 1.5, sm: 2 }, pt: 1.25, maxWidth: 480, mx: "auto" }}>
        <Stack
          direction="row"
          justifyContent="space-between"
          alignItems="center"
          spacing={1}
          sx={{ mb: 1.25 }}
        >
          <Box>
            <Typography sx={{ fontSize: 20, fontWeight: 800, lineHeight: 1.1 }}>
              Performance
            </Typography>
            <Typography sx={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>
              WF Folder sessions · HD wash/fold by operation time
            </Typography>
          </Box>
          <TextField
            size="small"
            type="date"
            value={dateEt}
            onChange={(e) => setDateEt(e.target.value)}
            inputProps={{ "aria-label": "Business date ET" }}
            sx={{ width: 150, bgcolor: "#fff" }}
          />
        </Stack>

        <ManagementWfFolderPerformanceSection dateEt={dateEt} />
        <ManagementHdPerformanceSection dateEt={dateEt} />
      </Box>
    </Box>
  );
}
