import { useMemo } from "react";
import { Box, Chip, Stack, Typography } from "@mui/material";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";
import {
  buildDayViewTabs,
  buildRoleViewTabs,
  filterEntriesByRoleView,
  hasRoleViewFilter,
  SCHEDULE_VIEW_ALL,
  toggleRoleViewSelection,
} from "./weeklyScheduleViewFilters";

function FilterChip({ label, count, selected, onClick }) {
  return (
    <Chip
      size="small"
      label={`${label} (${count})`}
      onClick={onClick}
      variant={selected ? "filled" : "outlined"}
      color={selected ? "primary" : "default"}
      sx={{
        height: 22,
        fontWeight: 700,
        fontSize: "0.72rem",
        borderColor: selected ? undefined : VEEWASH_DASHBOARD.snapshotBorder,
        bgcolor: selected ? VEEWASH_DASHBOARD.primaryBlueLight : undefined,
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
  selectedRoles = [],
  onSelectedRolesChange,
  dayTab = SCHEDULE_VIEW_ALL,
  onDayTabChange,
  hiddenRoles = [],
}) {
  const roleTabs = useMemo(
    () => buildRoleViewTabs(entries, { hiddenRoles }),
    [entries, hiddenRoles],
  );
  const dayTabs = useMemo(
    () => buildDayViewTabs(filterEntriesByRoleView(entries, selectedRoles), { compact: true }),
    [entries, selectedRoles],
  );

  const allRoleTab = roleTabs.find((tab) => tab.value === SCHEDULE_VIEW_ALL);
  const singleRoleTabs = roleTabs.filter((tab) => tab.value !== SCHEDULE_VIEW_ALL);
  const showAllRoles = !hasRoleViewFilter(selectedRoles);

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
      <ChipRow title="Roles">
        {allRoleTab ? (
          <FilterChip
            label={allRoleTab.label}
            count={allRoleTab.count}
            selected={showAllRoles}
            onClick={() => onSelectedRolesChange([])}
          />
        ) : null}
        {singleRoleTabs.map((tab) => (
          <FilterChip
            key={tab.value}
            label={tab.label}
            count={tab.count}
            selected={selectedRoles.includes(tab.value)}
            onClick={() => onSelectedRolesChange(toggleRoleViewSelection(selectedRoles, tab.value))}
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
