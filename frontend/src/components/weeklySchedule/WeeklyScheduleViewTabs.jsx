import { useMemo } from "react";
import { Box, Chip, Stack, Typography } from "@mui/material";
import { useI18n } from "../../i18n/I18nContext";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";
import { groupRoleCodes } from "./weeklyScheduleRoles";
import {
  buildBreaksTasksDayTabs,
  buildDayViewTabs,
  buildRoleViewTabs,
  filterEntriesByRoles,
  isCodeSelected,
  SCHEDULE_VIEW_ALL,
  toggleSelectionCode,
} from "./weeklyScheduleViewFilters";

function FilterChip({ label, count, selected, onClick, title }) {
  return (
    <Chip
      size="small"
      label={`${label} (${count})`}
      title={title}
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

/**
 * `selectedRoles`: null = all roles (every chip on), otherwise the selected role codes, shared with the
 * hourly views. `roleUniverse` is every role code the selection can hold, so roles chosen on another
 * employer tab stay chosen when a chip here is toggled.
 */
export default function WeeklyScheduleViewTabs({
  entries,
  selectedRoles = null,
  onSelectedRolesChange,
  dayTab = SCHEDULE_VIEW_ALL,
  onDayTabChange,
  hiddenRoles = [],
  roleCatalog = null,
  responsibilities = [],
  hideRoles = false,
  roleUniverse = null,
  dayCountMode = "employees",
}) {
  const roleTabs = useMemo(
    () => buildRoleViewTabs(entries, { hiddenRoles }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tabs read the registered role catalog
    [entries, hiddenRoles, roleCatalog],
  );
  const dayTabs = useMemo(
    () =>
      dayCountMode === "activity"
        ? buildBreaksTasksDayTabs(entries, responsibilities)
        : buildDayViewTabs(filterEntriesByRoles(entries, selectedRoles), {
            compact: true,
            responsibilities: Array.isArray(selectedRoles) ? [] : responsibilities,
          }),
    [entries, selectedRoles, responsibilities, dayCountMode],
  );
  const allRoleTab = roleTabs.find((tab) => tab.value === SCHEDULE_VIEW_ALL);
  const singleRoleTabs = roleTabs.filter((tab) => tab.value !== SCHEDULE_VIEW_ALL);
  const tabByRole = new Map(singleRoleTabs.map((tab) => [tab.value, tab]));
  const roleGroups = groupRoleCodes(singleRoleTabs.map((tab) => tab.value));
  const showAllRoles = !Array.isArray(selectedRoles);
  const universe = roleUniverse || singleRoleTabs.map((tab) => tab.value);
  const { t } = useI18n();
  const employeeTitle = (count) =>
    t(count === 1 ? "weeklySchedule.filters.employee" : "weeklySchedule.filters.employees", { count });
  const dayTitle = (count) =>
    dayCountMode === "activity"
      ? t(count === 1 ? "weeklySchedule.filters.dayActivityOne" : "weeklySchedule.filters.dayActivity", { count })
      : employeeTitle(count);

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
      {hideRoles ? null : (
        <ChipRow title={t("weeklySchedule.filters.roles")}>
          {allRoleTab ? (
            <FilterChip
              label={allRoleTab.label}
              count={allRoleTab.count}
              title={employeeTitle(allRoleTab.count)}
              selected={showAllRoles}
              onClick={() => onSelectedRolesChange(null)}
            />
          ) : null}
          <Chip
            size="small"
            label={t("weeklySchedule.filters.clear")}
            variant="outlined"
            onClick={() => onSelectedRolesChange([])}
            sx={{ height: 22, fontWeight: 700, fontSize: "0.72rem", borderStyle: "dashed" }}
          />
          {roleGroups.map((group) => (
            <Stack key={group.code || "ungrouped"} direction="row" spacing={0.5} alignItems="center" useFlexGap flexWrap="wrap">
              {roleGroups.length > 1 ? (
                <Typography variant="caption" sx={{ fontWeight: 700, color: "text.disabled", fontSize: "0.64rem", ml: 0.5 }}>
                  {group.label}:
                </Typography>
              ) : null}
              {group.roles.map((role) => {
                const tab = tabByRole.get(role);
                return (
                  <FilterChip
                    key={role}
                    label={tab.label}
                    count={tab.count}
                    title={employeeTitle(tab.count)}
                    selected={isCodeSelected(selectedRoles, role)}
                    onClick={() => onSelectedRolesChange(toggleSelectionCode(selectedRoles, role, universe))}
                  />
                );
              })}
            </Stack>
          ))}
        </ChipRow>
      )}

      <ChipRow title={t("weeklySchedule.filters.days")}>
        {dayTabs.map((tab) => (
          <FilterChip
            key={tab.value}
            label={tab.label}
            count={tab.count}
            title={dayTitle(tab.count)}
            selected={dayTab === tab.value}
            onClick={() => onDayTabChange(tab.value)}
          />
        ))}
      </ChipRow>
    </Box>
  );
}
