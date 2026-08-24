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
 * WF Folder + HD wash/fold attribution dashboard.
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
      <Box sx={{ px: { xs: 1.5, sm: 2, lg: 3 }, pt: 1.25, maxWidth: 1280, mx: "auto", width: "100%" }}>
        <Stack
          direction={{ xs: "column", sm: "row" }}
          justifyContent="space-between"
          alignItems={{ xs: "stretch", sm: "center" }}
          spacing={1}
          sx={{ mb: 1.5 }}
        >
          <Box>
            <Typography sx={{ fontSize: 22, fontWeight: 800, lineHeight: 1.1 }}>
              Performance
            </Typography>
            <Typography sx={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>
              WF folder productivity · HD wash/fold operation credit
            </Typography>
          </Box>
          <TextField
            size="small"
            type="date"
            value={dateEt}
            onChange={(e) => setDateEt(e.target.value)}
            inputProps={{ "aria-label": "Business date ET" }}
            sx={{ width: { xs: "100%", sm: 160 }, bgcolor: "#fff" }}
          />
        </Stack>

        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "1fr", lg: "1fr 1fr" },
            gap: 2,
            alignItems: "start",
          }}
        >
          <ManagementWfFolderPerformanceSection dateEt={dateEt} />
          <ManagementHdPerformanceSection dateEt={dateEt} />
        </Box>
      </Box>
    </Box>
  );
}
