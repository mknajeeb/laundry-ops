import { useMemo } from "react";
import { Box, Chip, Stack, Typography } from "@mui/material";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";
import {
  buildDayViewTabs,
  buildRoleViewTabs,
  filterEntriesByRoleView,
  SCHEDULE_VIEW_ALL,
} from "./weeklyScheduleViewFilters";

function FilterChip({ label, count, selected, onClick, group = false }) {
  return (
    <Chip
      size="small"
      label={`${label} (${count})`}
      onClick={onClick}
      variant={selected ? "filled" : "outlined"}
      color={selected ? (group ? "primary" : "default") : "default"}
      sx={{
        height: 22,
        fontWeight: 700,
        fontSize: "0.72rem",
        borderColor: selected ? undefined : VEEWASH_DASHBOARD.snapshotBorder,
        bgcolor: selected && !group ? VEEWASH_DASHBOARD.primaryBlueLight : undefined,
        "& .MuiChip-label": { px: 0.85 },
      }}
    />
  );
}

function ChipRow({ title, children }) {
  return (
    <Stack direction="row" spacing={0.5} alignItems="center" flexWrap="wrap" useFlexGap sx={{ minHeight: 24 }}>
      <Typography
        variant="caption"
        sx={{
          fontWeight: 800,
          color: "text.secondary",
          fontSize: "0.68rem",
          letterSpacing: "0.04em",
          mr: 0.25,
          flexShrink: 0,
        }}
      >
        {title}
      </Typography>
      {children}
    </Stack>
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
    () => buildDayViewTabs(filterEntriesByRoleView(entries, roleTab), { compact: true }),
    [entries, roleTab],
  );

  const allRoleTab = roleTabs.find((tab) => tab.value === SCHEDULE_VIEW_ALL);
  const groupTabs = roleTabs.filter((tab) => tab.isGroup);
  const singleRoleTabs = roleTabs.filter((tab) => !tab.isGroup && tab.value !== SCHEDULE_VIEW_ALL);

  return (
    <Box
      sx={{
        borderTop: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
        bgcolor: "#f8fafc",
        px: 1.25,
        py: 0.5,
        display: "flex",
        flexDirection: "column",
        gap: 0.35,
      }}
      className="no-print"
    >
      <ChipRow title="Groups">
        {allRoleTab ? (
          <FilterChip
            label={allRoleTab.label}
            count={allRoleTab.count}
            selected={roleTab === allRoleTab.value}
            onClick={() => onRoleTabChange(allRoleTab.value)}
          />
        ) : null}
        {groupTabs.map((tab) => (
          <FilterChip
            key={tab.value}
            label={tab.label}
            count={tab.count}
            selected={roleTab === tab.value}
            onClick={() => onRoleTabChange(tab.value)}
            group
          />
        ))}
      </ChipRow>

      <ChipRow title="Roles">
        {singleRoleTabs.map((tab) => (
          <FilterChip
            key={tab.value}
            label={tab.label}
            count={tab.count}
            selected={roleTab === tab.value}
            onClick={() => onRoleTabChange(tab.value)}
          />
        ))}
      </ChipRow>

      <ChipRow title="Days">
        {dayTabs.map((tab) => (
          <FilterChip
            key={tab.value}
            label={tab.label}
            count={tab.count}
            selected={dayTab === tab.value}
            onClick={() => onDayTabChange(tab.value)}
          />
        ))}
      </ChipRow>
    </Box>
  );
}
