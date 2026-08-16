import { useNavigate } from "react-router-dom";
import { Box, Button, Typography } from "@mui/material";
import ManagementHubNav, { HUB_DESTINATIONS } from "../components/management/ManagementHubNav";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";

/**
 * Transitional Management landing only.
 * Do not add KPI cards or business logic here — compartments are the source of truth.
 */
export default function ManagementHubPage() {
  const navigate = useNavigate();
  const live = HUB_DESTINATIONS.filter((d) => d.enabled && d.id !== "today");

  return (
    <Box
      className="page"
      sx={{
        maxWidth: 720,
        mx: "auto",
        width: "100%",
        px: { xs: 1.5, sm: 2 },
        pb: 3,
        bgcolor: VEEWASH_DASHBOARD.pageBackground,
        minHeight: "100%",
      }}
    >
      <ManagementHubNav activeId="today" />

      <Box sx={{ mt: 2.5 }}>
        <Typography sx={{ fontSize: 22, fontWeight: 800, lineHeight: 1.1 }}>Today</Typography>
        <Typography sx={{ mt: 0.75, fontSize: 14, color: "#64748b", fontWeight: 600, maxWidth: 520 }}>
          Transitional landing. Operating work lives in the compartments below. A management
          dashboard summary will come later — after each compartment is proven.
        </Typography>
      </Box>

      <Box sx={{ mt: 2.5, display: "grid", gap: 1 }}>
        {live.map((item) => (
          <Box
            key={item.id}
            sx={{
              p: 1.5,
              borderRadius: 2,
              border: "1px solid",
              borderColor: VEEWASH_DASHBOARD.snapshotBorder,
              bgcolor: "#fff",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 1,
            }}
          >
            <Box>
              <Typography sx={{ fontSize: 15, fontWeight: 800 }}>{item.label}</Typography>
              <Typography sx={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>
                {item.id === "rinse_wf"
                  ? "Workload · Completed · Pending · Review · Specialty"
                  : "Coming next"}
              </Typography>
            </Box>
            <Button
              size="small"
              variant="contained"
              onClick={() => navigate(item.to)}
              sx={{
                textTransform: "none",
                fontWeight: 700,
                bgcolor: VEEWASH_DASHBOARD.primaryBlue,
                "&:hover": { bgcolor: VEEWASH_DASHBOARD.primaryBlueDark },
              }}
            >
              Open
            </Button>
          </Box>
        ))}

        <Box
          sx={{
            p: 1.5,
            borderRadius: 2,
            border: "1px dashed #cbd5e1",
            bgcolor: "#f8fafc",
          }}
        >
          <Typography sx={{ fontSize: 13, fontWeight: 700, color: "#64748b" }}>
            Next compartments
          </Typography>
          <Typography sx={{ mt: 0.35, fontSize: 12, color: "#94a3b8", fontWeight: 600 }}>
            Rinse HD · Performance · Labor · Revenue · Rinse Flow · Analysis · Bag Search
          </Typography>
        </Box>
      </Box>
    </Box>
  );
}
