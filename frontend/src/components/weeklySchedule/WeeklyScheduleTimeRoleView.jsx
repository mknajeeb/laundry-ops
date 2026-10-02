import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  FormControlLabel,
  MenuItem,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import AddCircleOutlineIcon from "@mui/icons-material/AddCircleOutline";
import { formatTime12 } from "../datetime/scheduleTimeUi";
import { DAY_LABELS } from "./weeklyScheduleDates";
import { groupRoleCodes, roleStyle, scheduleRoleLabel } from "./weeklyScheduleRoles";
import {
  ASSIGNMENT_KIND,
  dayDateLabel,
  formatCoverageHours,
  hourBoundaryLabel,
  HOURLY_COVERAGE_EXPLANATION,
} from "./weeklyScheduleTimeBlocks";

function peopleCountLabel(count) {
  return `${count} ${count === 1 ? "person" : "people"}`;
}

/** Role checkboxes (grouped), Select all / Clear all, names toggle, and the hour range. */
export function HourlyCoverageControls({
  roleOptions,
  selectedRoles,
  onSelectedRolesChange,
  showNames,
  onShowNamesChange,
  fromHour,
  toHour,
  hourBounds,
  onHourRangeChange,
}) {
  const selected = new Set(selectedRoles ?? roleOptions);
  const toggle = (role) => {
    const next = new Set(selected);
    if (next.has(role)) next.delete(role);
    else next.add(role);
    const list = roleOptions.filter((code) => next.has(code));
    onSelectedRolesChange(list.length === roleOptions.length ? null : list);
  };
  const hourChoices = [];
  if (hourBounds) {
    for (let hour = hourBounds.min; hour <= hourBounds.max; hour += 1) hourChoices.push(hour);
  }
  return (
    <Paper
      elevation={0}
      className="no-print"
      sx={{ border: "1px solid #e2e8f0", borderRadius: 2, p: 1.25, mb: 1.25, bgcolor: "#fff" }}
    >
      <Stack direction="row" alignItems="center" spacing={1} useFlexGap flexWrap="wrap" sx={{ mb: 0.5 }}>
        <Typography variant="overline" sx={{ fontWeight: 800, letterSpacing: "0.08em", lineHeight: 1.6 }}>
          Roles shown
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {selected.size} of {roleOptions.length}
        </Typography>
        <Button size="small" onClick={() => onSelectedRolesChange(null)} sx={{ fontWeight: 700, py: 0 }}>
          Select all
        </Button>
        <Button size="small" onClick={() => onSelectedRolesChange([])} sx={{ fontWeight: 700, py: 0 }}>
          Clear all
        </Button>
      </Stack>
      <Stack spacing={0.25}>
        {groupRoleCodes(roleOptions).map((group) => (
          <Stack key={group.code || "ungrouped"} direction="row" alignItems="center" useFlexGap flexWrap="wrap" columnGap={0.5}>
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{ fontWeight: 800, minWidth: 96, textTransform: "uppercase", letterSpacing: "0.04em" }}
            >
              {group.label}
            </Typography>
            {group.roles.map((role) => (
              <FormControlLabel
                key={role}
                sx={{ mr: 1, "& .MuiFormControlLabel-label": { fontSize: "0.8rem", fontWeight: 600 } }}
                control={
                  <Checkbox
                    size="small"
                    checked={selected.has(role)}
                    onChange={() => toggle(role)}
                    sx={{ p: 0.5, color: roleStyle(role).accent, "&.Mui-checked": { color: roleStyle(role).accent } }}
                  />
                }
                label={scheduleRoleLabel(role)}
              />
            ))}
          </Stack>
        ))}
      </Stack>
      <Stack direction="row" alignItems="center" spacing={1.5} useFlexGap flexWrap="wrap" sx={{ mt: 0.75 }}>
        <FormControlLabel
          sx={{ "& .MuiFormControlLabel-label": { fontSize: "0.85rem", fontWeight: 700 } }}
          control={<Checkbox size="small" checked={showNames} onChange={(e) => onShowNamesChange(e.target.checked)} />}
          label="Show employee names"
        />
        {hourChoices.length ? (
          <>
            <TextField
              select
              size="small"
              label="From"
              value={fromHour ?? ""}
              onChange={(e) => onHourRangeChange({ fromHour: e.target.value === "" ? null : Number(e.target.value), toHour })}
              sx={{ minWidth: 120 }}
            >
              <MenuItem value="">Start of day</MenuItem>
              {hourChoices.map((hour) => (
                <MenuItem key={hour} value={hour} disabled={toHour != null && hour >= toHour}>
                  {hourBoundaryLabel(hour)}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              select
              size="small"
              label="To"
              value={toHour ?? ""}
              onChange={(e) => onHourRangeChange({ fromHour, toHour: e.target.value === "" ? null : Number(e.target.value) })}
              sx={{ minWidth: 120 }}
            >
              <MenuItem value="">End of day</MenuItem>
              {hourChoices.map((hour) => (
                <MenuItem key={hour} value={hour + 1} disabled={fromHour != null && hour + 1 <= fromHour}>
                  {hourBoundaryLabel(hour + 1)}
                </MenuItem>
              ))}
            </TextField>
          </>
        ) : null}
      </Stack>
    </Paper>
  );
}

function PersonLine({ person, onClick }) {
  const detail = [person.partial ? person.rangeLabel : "", person.shared ? `split ${formatCoverageHours(person.hours)}` : ""]
    .filter(Boolean)
    .join(" · ");
  const shiftLabel = `${formatTime12(person.entry?.start_time)} – ${formatTime12(person.entry?.end_time)} shift`;
  return (
    <Tooltip title={shiftLabel} enterDelay={400}>
      <Box
        role={onClick ? "button" : undefined}
        tabIndex={onClick ? 0 : undefined}
        onClick={onClick}
        onKeyDown={(e) => {
          if (onClick && (e.key === "Enter" || e.key === " ")) {
            e.preventDefault();
            onClick();
          }
        }}
        sx={{
          fontSize: "0.74rem",
          lineHeight: 1.3,
          cursor: onClick ? "pointer" : "default",
          borderRadius: 0.75,
          px: 0.25,
          "&:hover": onClick ? { bgcolor: "rgba(0, 151, 178, 0.08)" } : {},
        }}
      >
        <Box component="span" sx={{ fontWeight: 700 }}>
          {person.name}
        </Box>
        {detail ? (
          <Box component="span" sx={{ color: "text.secondary" }}>
            {` ${detail}`}
          </Box>
        ) : null}
      </Box>
    </Tooltip>
  );
}

function CoverageCell({ cell, endLabel, showNames, onEditEntry, canEdit }) {
  if (!cell?.count) {
    return (
      <>
        <Typography variant="body2" color="text.disabled" sx={{ fontSize: "0.78rem" }}>
          —
        </Typography>
        {cell?.cumulative ? (
          <Typography variant="caption" color="text.disabled" sx={{ display: "block", lineHeight: 1.2 }}>
            Total through {endLabel}: {formatCoverageHours(cell.cumulative)}
          </Typography>
        ) : null}
      </>
    );
  }
  return (
    <>
      <Typography variant="body2" sx={{ fontWeight: 800, fontSize: "0.8rem", whiteSpace: "nowrap" }}>
        {peopleCountLabel(cell.count)} · {formatCoverageHours(cell.hours)}
      </Typography>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", lineHeight: 1.2, whiteSpace: "nowrap" }}>
        Total through {endLabel}: {formatCoverageHours(cell.cumulative)}
      </Typography>
      {showNames ? (
        <Box sx={{ mt: 0.35 }}>
          {cell.people.map((person) => (
            <PersonLine
              key={person.userId}
              person={person}
              onClick={canEdit && person.entry ? () => onEditEntry?.(person.entry) : undefined}
            />
          ))}
        </Box>
      ) : null}
    </>
  );
}

const stickyCol = { position: "sticky", left: 0, zIndex: 1, bgcolor: "inherit" };

function DayMatrix({ day, columns, showNames, canEdit, onEditEntry }) {
  return (
    <TableContainer sx={{ maxWidth: "100%" }}>
      <Table size="small" sx={{ "& td, & th": { verticalAlign: "top", borderColor: "#eef2f6", px: 1, py: 0.6 } }}>
        <TableHead>
          <TableRow sx={{ bgcolor: "#fff" }}>
            <TableCell sx={{ ...stickyCol, fontWeight: 800, minWidth: 104 }}>Hour</TableCell>
            {columns.map((role) => (
              <TableCell key={role} sx={{ fontWeight: 800, minWidth: 140, color: roleStyle(role).accent }}>
                {scheduleRoleLabel(role)}
              </TableCell>
            ))}
            <TableCell sx={{ fontWeight: 800, minWidth: 150, bgcolor: "#f8fafc" }}>All shown roles</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {day.hours.map((row) => (
            <TableRow key={row.hour} sx={{ bgcolor: row.gap ? "#fffbeb" : "#fff" }}>
              <TableCell sx={{ ...stickyCol, fontWeight: 800, whiteSpace: "nowrap", fontSize: "0.8rem" }}>
                {row.label}
              </TableCell>
              {columns.map((role) => (
                <TableCell key={role}>
                  <CoverageCell
                    cell={row.cells[role]}
                    endLabel={row.endLabel}
                    showNames={showNames}
                    canEdit={canEdit}
                    onEditEntry={onEditEntry}
                  />
                </TableCell>
              ))}
              <TableCell sx={{ bgcolor: row.gap ? "#fef3c7" : "#f8fafc" }}>
                {row.gap ? (
                  <Typography variant="body2" sx={{ fontWeight: 800, fontSize: "0.8rem", color: "#b45309" }}>
                    {row.scheduled ? `No coverage · ${peopleCountLabel(row.scheduled)} scheduled` : "No one scheduled"}
                  </Typography>
                ) : (
                  <Typography variant="body2" sx={{ fontWeight: 800, fontSize: "0.8rem", whiteSpace: "nowrap" }}>
                    {peopleCountLabel(row.total.count)} · {formatCoverageHours(row.total.hours)}
                  </Typography>
                )}
                <Typography variant="caption" color="text.secondary" sx={{ display: "block", lineHeight: 1.2, whiteSpace: "nowrap" }}>
                  Total through {row.endLabel}: {formatCoverageHours(row.total.cumulative)}
                </Typography>
              </TableCell>
            </TableRow>
          ))}
          <TableRow sx={{ bgcolor: "#f1f5f9", "& td": { borderTop: "2px solid #cbd5e1" } }}>
            <TableCell sx={{ ...stickyCol, fontWeight: 800, fontSize: "0.8rem" }}>Day total</TableCell>
            {columns.map((role) => {
              const total = day.totals[role];
              return (
                <TableCell key={role}>
                  <Typography variant="body2" sx={{ fontWeight: 800, fontSize: "0.8rem", whiteSpace: "nowrap" }}>
                    {total ? `${peopleCountLabel(total.count)} · ${formatCoverageHours(total.hours)}` : "—"}
                  </Typography>
                </TableCell>
              );
            })}
            <TableCell>
              <Typography variant="body2" sx={{ fontWeight: 800, fontSize: "0.8rem", whiteSpace: "nowrap" }}>
                {peopleCountLabel(day.overall.count)} · {formatCoverageHours(day.overall.hours)}
              </Typography>
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </TableContainer>
  );
}

function DayTasks({ day, canEdit, onAdd, onEditResponsibility }) {
  if (!day.responsibilities.length) return null;
  return (
    <Box sx={{ px: 1.5, py: 0.75, bgcolor: "#fcfcfd", borderTop: "1px solid #eef2f6" }}>
      <Stack direction="row" alignItems="center" spacing={0.75} sx={{ mb: 0.25 }}>
        <Typography variant="overline" sx={{ fontWeight: 800, letterSpacing: "0.08em", fontSize: "0.66rem", color: "text.secondary" }}>
          Tasks
        </Typography>
        <Typography variant="caption" color="text.disabled">
          whole day · no times · not counted in hours
        </Typography>
      </Stack>
      {day.responsibilities.map((group) => {
        const style = roleStyle(group.role);
        return (
          <Stack
            key={group.role}
            direction={{ xs: "column", sm: "row" }}
            spacing={{ xs: 0.25, sm: 1 }}
            sx={{ py: 0.5, "&:not(:last-of-type)": { borderBottom: "1px dashed #e8eef2" } }}
          >
            <Stack direction="row" spacing={0.5} alignItems="center" sx={{ minWidth: 180 }}>
              <Box sx={{ width: 4, alignSelf: "stretch", minHeight: 18, borderRadius: 2, bgcolor: style.accent }} />
              <Typography variant="body2" fontWeight={800} sx={{ color: style.accent, fontSize: "0.8rem" }} noWrap>
                {group.label}
              </Typography>
              <Chip size="small" label={group.count} sx={{ height: 18, fontSize: "0.65rem", fontWeight: 800 }} />
              {canEdit ? (
                <Button
                  size="small"
                  onClick={() => onAdd?.({ day: day.dow, role: group.role, kind: ASSIGNMENT_KIND.RESPONSIBILITY })}
                  sx={{ minWidth: 0, py: 0, fontWeight: 700 }}
                >
                  Add
                </Button>
              ) : null}
            </Stack>
            <Stack direction="row" spacing={0.5} useFlexGap flexWrap="wrap">
              {group.people.map((person) => (
                <Box
                  key={person.key}
                  role={canEdit ? "button" : undefined}
                  tabIndex={canEdit ? 0 : undefined}
                  onClick={canEdit ? () => onEditResponsibility?.(person.item) : undefined}
                  sx={{
                    px: 0.85,
                    py: 0.35,
                    borderRadius: 1.25,
                    border: "1px solid #e2e8f0",
                    bgcolor: "#fff",
                    cursor: canEdit ? "pointer" : "default",
                  }}
                >
                  <Typography variant="body2" fontWeight={700} sx={{ fontSize: "0.78rem", lineHeight: 1.3 }}>
                    {person.name}
                  </Typography>
                  {person.remarks ? (
                    <Typography variant="caption" color="text.secondary" sx={{ display: "block", lineHeight: 1.25, whiteSpace: "normal" }}>
                      {person.remarks}
                    </Typography>
                  ) : null}
                </Box>
              ))}
            </Stack>
          </Stack>
        );
      })}
    </Box>
  );
}

/** `days` comes from buildHourlyCoverage so screen, print, and export share one calculation. */
export default function WeeklyScheduleTimeRoleView({
  weekStart,
  days,
  columns,
  showNames = false,
  endTimeEnabled = true,
  canEdit = false,
  onEditEntry,
  onEditResponsibility,
  onAdd,
}) {
  return (
    <Stack spacing={1.25} sx={{ pb: 2 }}>
      {!endTimeEnabled ? (
        <Alert severity="info">Hourly coverage needs shift end times. Turn on end times in the display settings.</Alert>
      ) : null}
      {!columns.length ? (
        <Alert severity="info">No roles selected. Choose roles above to see hourly coverage.</Alert>
      ) : null}
      {(days || []).map((day) => (
        <Paper
          key={day.dow}
          elevation={0}
          sx={{ border: "1px solid #e2e8f0", borderRadius: 2.5, overflow: "hidden", bgcolor: "#fff" }}
        >
          <Stack
            direction="row"
            alignItems="center"
            justifyContent="space-between"
            sx={{ px: 1.5, py: 0.75, bgcolor: "#f8fafc", borderBottom: "1px solid #e2e8f0" }}
          >
            <Typography variant="subtitle2" fontWeight={800}>
              {DAY_LABELS[day.dow]}
              <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 0.75, fontWeight: 600 }}>
                {dayDateLabel(weekStart, day.dow)}
              </Typography>
            </Typography>
            {canEdit ? (
              <Button
                size="small"
                startIcon={<AddCircleOutlineIcon sx={{ fontSize: 16 }} />}
                onClick={() => onAdd?.({ day: day.dow })}
                sx={{ fontWeight: 700, py: 0.25 }}
              >
                Add
              </Button>
            ) : null}
          </Stack>
          {day.hours.length && columns.length ? (
            <DayMatrix day={day} columns={columns} showNames={showNames} canEdit={canEdit} onEditEntry={onEditEntry} />
          ) : null}
          {!day.hours.length && !day.responsibilities.length ? (
            <Typography variant="body2" color="text.secondary" sx={{ px: 1.5, py: 1.25 }}>
              No assignments.
            </Typography>
          ) : null}
          <DayTasks day={day} canEdit={canEdit} onAdd={onAdd} onEditResponsibility={onEditResponsibility} />
        </Paper>
      ))}
      <Typography variant="caption" color="text.secondary" sx={{ px: 0.25 }}>
        {HOURLY_COVERAGE_EXPLANATION}
      </Typography>
    </Stack>
  );
}
