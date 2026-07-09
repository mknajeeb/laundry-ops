import { useState } from "react";
import { Box, Tab, Tabs, Typography } from "@mui/material";
import EditNoteIcon from "@mui/icons-material/EditNote";
import SettingsIcon from "@mui/icons-material/Settings";
import AttachMoneyIcon from "@mui/icons-material/AttachMoney";
import BarChartIcon from "@mui/icons-material/BarChart";
import DailyEntryTab from "../components/dailyRevenueCost/DailyEntryTab";
import RevenueMaintenanceTab from "../components/dailyRevenueCost/RevenueMaintenanceTab";
import CostMaintenanceTab from "../components/dailyRevenueCost/CostMaintenanceTab";
import DashboardTab from "../components/dailyRevenueCost/DashboardTab";
import { DRC_NAV_SX } from "../utils/dailyRevenueCostHelpers";

const TABS = [
  { key: "entry", label: "Daily Entry", icon: EditNoteIcon },
  { key: "revenue", label: "Revenue Maintenance", icon: AttachMoneyIcon },
  { key: "cost", label: "Cost Maintenance", icon: SettingsIcon },
  { key: "dashboard", label: "Dashboard", icon: BarChartIcon },
];

export default function DailyRevenueCostPage() {
  const [tab, setTab] = useState(0);

  return (
    <Box className="page" sx={{ maxWidth: 720, mx: "auto", width: "100%" }}>
      <Typography variant="h5" fontWeight={800} sx={{ mb: 0.5, fontSize: { xs: "1.35rem", sm: "1.5rem" } }}>
        Daily Revenue & Cost
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Management estimates — quick daily entry and profitability views.
      </Typography>

      <Box sx={DRC_NAV_SX}>
        <Tabs
          value={tab}
          onChange={(_, v) => setTab(v)}
          variant="scrollable"
          scrollButtons="auto"
          allowScrollButtonsMobile
        >
          {TABS.map((t, i) => {
            const Icon = t.icon;
            return (
              <Tab
                key={t.key}
                icon={<Icon sx={{ fontSize: 20 }} />}
                iconPosition="start"
                label={t.label}
                sx={{ minHeight: 48, fontSize: { xs: "0.8rem", sm: "0.875rem" } }}
                value={i}
              />
            );
          })}
        </Tabs>
      </Box>

      {tab === 0 ? <DailyEntryTab /> : null}
      {tab === 1 ? <RevenueMaintenanceTab /> : null}
      {tab === 2 ? <CostMaintenanceTab /> : null}
      {tab === 3 ? <DashboardTab /> : null}
    </Box>
  );
}
