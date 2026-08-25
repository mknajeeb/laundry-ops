import { useState } from "react";
import { Box, Stack, TextField, Typography } from "@mui/material";
import ManagementHubNav from "../components/management/ManagementHubNav";
import ManagementHdPerformanceSection from "../components/management/ManagementHdPerformanceSection";
import ManagementWfFolderPerformanceSection from "../components/management/ManagementWfFolderPerformanceSection";
import { PERF_TYPE, PERF_UI } from "../components/management/performance/performanceTokens";

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

const MODES = [
  { id: "wf", label: "Wash & Fold" },
  { id: "hd", label: "Hang Dry" },
];

export default function ManagementPerformancePage() {
  const [dateEt, setDateEt] = useState(todayEtIso);
  const [mode, setMode] = useState("wf");

  return (
    <Box sx={{ minHeight: "100dvh", bgcolor: PERF_UI.pageBg, pb: 4 }}>
      <ManagementHubNav activeId="performance" />

      <Box
        sx={{
          px: { xs: 1.25, sm: 2, md: 3 },
          pt: 1,
          maxWidth: 960,
          mx: "auto",
          width: "100%",
        }}
      >
        <Stack
          direction={{ xs: "column", sm: "row" }}
          justifyContent="space-between"
          alignItems={{ xs: "stretch", sm: "center" }}
          spacing={1}
          sx={{ mb: 1.25 }}
        >
          <Typography sx={PERF_TYPE.pageTitle}>Performance</Typography>
          <TextField
            size="small"
            type="date"
            value={dateEt}
            onChange={(e) => setDateEt(e.target.value)}
            inputProps={{ "aria-label": "Business date ET" }}
            sx={{
              width: { xs: "100%", sm: 156 },
              bgcolor: PERF_UI.rowBg,
              "& .MuiOutlinedInput-root": {
                borderRadius: 1.25,
                fontSize: 13,
                fontWeight: 500,
                "& fieldset": { borderColor: PERF_UI.rowBorder },
              },
            }}
          />
        </Stack>

        <Box
          role="tablist"
          aria-label="Performance operation"
          sx={{
            display: "flex",
            p: 0.3,
            mb: 1.25,
            borderRadius: 1.5,
            bgcolor: PERF_UI.segmentTrack,
          }}
        >
          {MODES.map((m) => {
            const active = mode === m.id;
            return (
              <Box
                key={m.id}
                role="tab"
                aria-selected={active}
                component="button"
                type="button"
                onClick={() => setMode(m.id)}
                sx={{
                  flex: 1,
                  appearance: "none",
                  border: "none",
                  borderRadius: 1.15,
                  py: { xs: 0.55, sm: 0.6 },
                  px: 0.75,
                  fontSize: { xs: 12, sm: 13 },
                  fontWeight: active ? 600 : 500,
                  cursor: "pointer",
                  fontFamily: "inherit",
                  color: active ? "#fff" : PERF_UI.segmentInactive,
                  bgcolor: active ? PERF_UI.teal : "transparent",
                  transition: "background-color 0.15s ease, color 0.15s ease",
                }}
              >
                {m.label}
              </Box>
            );
          })}
        </Box>

        <Box
          sx={{
            borderRadius: 1.5,
            bgcolor: PERF_UI.contentTint,
            px: { xs: 0.75, sm: 1 },
            py: { xs: 0.75, sm: 1 },
          }}
        >
          <Box role="tabpanel" hidden={mode !== "wf"} sx={{ display: mode === "wf" ? "block" : "none" }}>
            {mode === "wf" ? <ManagementWfFolderPerformanceSection dateEt={dateEt} /> : null}
          </Box>
          <Box role="tabpanel" hidden={mode !== "hd"} sx={{ display: mode === "hd" ? "block" : "none" }}>
            {mode === "hd" ? <ManagementHdPerformanceSection dateEt={dateEt} /> : null}
          </Box>
        </Box>
      </Box>
    </Box>
  );
}
