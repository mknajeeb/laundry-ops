import { useMemo } from "react";
import { Box, Tab, Tabs, Typography } from "@mui/material";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";
import {
  buildDayViewTabs,
  buildRoleViewTabs,
  filterEntriesByRoleView,
  SCHEDULE_VIEW_ALL,
} from "./weeklyScheduleViewFilters";

function ViewTabRow({ label, value, onChange, tabs }) {
  if (!tabs?.length) return null;
  return (
    <Box sx={{ mb: 0.5 }}>
      <Typography
        variant="caption"
        sx={{
          display: "block",
          px: 2,
          pt: 0.75,
          pb: 0.25,
          fontWeight: 700,
          color: "text.secondary",
          letterSpacing: "0.04em",
        }}
      >
        {label}
      </Typography>
      <Tabs
        value={value}
        onChange={(_, next) => onChange(next)}
        variant="scrollable"
        scrollButtons="auto"
        allowScrollButtonsMobile
        sx={{
          minHeight: 34,
          px: 1,
          "& .MuiTab-root": {
            minHeight: 34,
            py: 0.35,
            px: 1.25,
            fontWeight: 700,
            fontSize: "0.78rem",
            textTransform: "none",
          },
        }}
      >
        {tabs.map((tab) => (
          <Tab key={tab.value} value={tab.value} label={`${tab.label} (${tab.count})`} />
        ))}
      </Tabs>
    </Box>
  );
}

export default function WeeklyScheduleViewTabs({
  entries,
  roleTab = SCHEDULE_VIEW_ALL,
  onRoleTabChange,
  dayTab = SCHEDULE_VIEW_ALL,
  onDayTabChange,
}) {
  const roleTabs = useMemo(() => buildRoleViewTabs(entries), [entries]);
  const dayTabs = useMemo(
    () => buildDayViewTabs(filterEntriesByRoleView(entries, roleTab)),
    [entries, roleTab],
  );

  return (
    <Box
      sx={{
        borderTop: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
        bgcolor: "#fbfdfe",
      }}
      className="no-print"
    >
      <ViewTabRow label="Role view" value={roleTab} onChange={onRoleTabChange} tabs={roleTabs} />
      <ViewTabRow label="Day view" value={dayTab} onChange={onDayTabChange} tabs={dayTabs} />
    </Box>
  );
}
