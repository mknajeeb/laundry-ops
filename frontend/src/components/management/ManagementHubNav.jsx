import { NavLink, useNavigate } from "react-router-dom";
import { Box } from "@mui/material";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

/** Hub compartments. Only Rinse WF (+ transitional Today landing) are live. */
export const HUB_DESTINATIONS = [
  { to: "/management", id: "today", label: "Today", enabled: true },
  { to: "/management/rinse-wf", id: "rinse_wf", label: "Rinse WF", enabled: true },
  { to: "/management/rinse-hd", id: "rinse_hd", label: "Rinse HD", enabled: true },
  { to: "/management/performance", id: "performance", label: "Performance", enabled: true },
  { to: "/management/labor", id: "labor", label: "Labor", enabled: false },
  { to: "/management/revenue", id: "revenue", label: "Revenue", enabled: false },
  { to: "/management/rinse-flow", id: "rinse_flow", label: "Rinse Flow", enabled: false },
  { to: "/management/analysis", id: "analysis", label: "Analysis", enabled: false },
  { to: "/management/bag-search", id: "bag_search", label: "Bag Search", enabled: false },
];

export const MANAGEMENT_BUCKETS = ["rinse_wf", "rinse_hd", "non_rinse"];

export default function ManagementHubNav({ activeId = "today" }) {
  const navigate = useNavigate();
  return (
    <Box
      component="nav"
      sx={{
        position: "sticky",
        top: 0,
        zIndex: 8,
        bgcolor: "#fff",
        borderBottom: "1px solid #e5e7eb",
        mx: { xs: -1.5, sm: -2 },
        px: { xs: 1, sm: 1.5 },
      }}
    >
      <Box
        sx={{
          display: "flex",
          gap: 0.5,
          overflowX: "auto",
          py: 0.75,
          WebkitOverflowScrolling: "touch",
          "&::-webkit-scrollbar": { display: "none" },
        }}
      >
        {HUB_DESTINATIONS.map((item) => {
          const selected = item.id === activeId;
          const sx = {
            flex: "0 0 auto",
            px: 1.25,
            py: 0.75,
            borderRadius: 999,
            fontSize: 13,
            fontWeight: selected ? 800 : 600,
            letterSpacing: 0.2,
            textDecoration: "none",
            whiteSpace: "nowrap",
            border: "1px solid",
            borderColor: selected ? VEEWASH_DASHBOARD.primaryBlue : "#e5e7eb",
            color: item.enabled
              ? selected
                ? VEEWASH_DASHBOARD.primaryBlueDark
                : "#334155"
              : "#94a3b8",
            bgcolor: selected ? VEEWASH_DASHBOARD.primaryBlueLight : item.enabled ? "#fff" : "#f8fafc",
            cursor: item.enabled ? "pointer" : "default",
            pointerEvents: item.enabled ? "auto" : "none",
          };
          if (!item.enabled) {
            return (
              <Box key={item.id} component="span" sx={sx} aria-disabled="true">
                {item.label}
              </Box>
            );
          }
          return (
            <Box
              key={item.id}
              component={NavLink}
              to={item.to}
              onClick={(e) => {
                e.preventDefault();
                navigate(item.to);
              }}
              sx={sx}
            >
              {item.label}
            </Box>
          );
        })}
      </Box>
    </Box>
  );
}
