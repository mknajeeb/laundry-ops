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

const MODES = [
  { id: "wf", label: "Wash & Fold" },
  { id: "hd", label: "Hang Dry" },
];

/**
 * Management → Performance — mobile-first operational productivity.
 */
export default function ManagementPerformancePage() {
  const [dateEt, setDateEt] = useState(todayEtIso);
  const [mode, setMode] = useState("wf");

  return (
    <Box
      sx={{
        minHeight: "100dvh",
        bgcolor: VEEWASH_DASHBOARD.pageBackground,
        pb: 5,
      }}
    >
      <ManagementHubNav activeId="performance" />

      <Box
        sx={{
          px: { xs: 1.5, sm: 2, md: 3 },
          pt: 1.25,
          maxWidth: 960,
          mx: "auto",
          width: "100%",
        }}
      >
        <Stack
          direction={{ xs: "column", sm: "row" }}
          justifyContent="space-between"
          alignItems={{ xs: "stretch", sm: "center" }}
          spacing={1.25}
          sx={{ mb: 1.75 }}
        >
          <Typography sx={{ fontSize: { xs: 22, sm: 24 }, fontWeight: 800, lineHeight: 1.1 }}>
            Performance
          </Typography>
          <TextField
            size="small"
            type="date"
            value={dateEt}
            onChange={(e) => setDateEt(e.target.value)}
            inputProps={{ "aria-label": "Business date ET" }}
            sx={{
              width: { xs: "100%", sm: 168 },
              bgcolor: "#fff",
              "& .MuiOutlinedInput-root": { borderRadius: 2 },
            }}
          />
        </Stack>

        <Box
          role="tablist"
          aria-label="Performance operation"
          sx={{
            display: "flex",
            p: 0.4,
            mb: 2,
            borderRadius: 2.5,
            bgcolor: "#e8f3f6",
            boxShadow: "inset 0 1px 2px rgba(0, 60, 80, 0.06)",
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
                  borderRadius: 2,
                  py: 1,
                  px: 1,
                  fontSize: { xs: 13, sm: 14 },
                  fontWeight: 800,
                  cursor: "pointer",
                  fontFamily: "inherit",
                  color: active ? "#fff" : VEEWASH_DASHBOARD.primaryBlueDark,
                  bgcolor: active ? VEEWASH_DASHBOARD.primaryBlue : "transparent",
                  boxShadow: active ? VEEWASH_DASHBOARD.cardShadow : "none",
                  transition: "background-color 0.15s ease, color 0.15s ease",
                }}
              >
                {m.label}
              </Box>
            );
          })}
        </Box>

        <Box role="tabpanel" hidden={mode !== "wf"} sx={{ display: mode === "wf" ? "block" : "none" }}>
          {mode === "wf" ? <ManagementWfFolderPerformanceSection dateEt={dateEt} /> : null}
        </Box>
        <Box role="tabpanel" hidden={mode !== "hd"} sx={{ display: mode === "hd" ? "block" : "none" }}>
          {mode === "hd" ? <ManagementHdPerformanceSection dateEt={dateEt} /> : null}
        </Box>
      </Box>
    </Box>
  );
}
