import {
  Box,
  Chip,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from "@mui/material";
import { DAY_LABELS } from "./weeklyScheduleDates";
import { roleStyle, scheduleRoleLabel, UNALLOCATED_BREAK_NOTE } from "./weeklyScheduleRoles";
import { ASSIGNMENT_KIND, dayDateLabel, formatCoverageHours } from "./weeklyScheduleTimeBlocks";
import { gridDayTaskText } from "./weeklyScheduleBreaksGrid";
import {
  BREAK_INTERVAL_OPTIONS,
  BREAKS_VIEW,
  byTimeDayHeaderText,
  peakIntensity,
  slotHeadline,
  slotPersonDetail,
  untimedPersonText,
} from "./weeklyScheduleBreaksByTime";
import { BreaksNotices, TaskFilter } from "./WeeklyScheduleBreaksTasksView";

const BREAK_ACCENT = "#9a3412";
const cellSx = { verticalAlign: "top", borderColor: "#eef2f6", px: 0.75, py: 0.5, fontSize: "0.78rem" };
const stickySx = (bgcolor) => ({ position: "sticky", left: 0, zIndex: 1, bgcolor, fontWeight: 800 });
const toggleSx = { py: 0.25, px: 1, fontSize: "0.72rem", fontWeight: 800, textTransform: "none" };

function activate(handler) {
  return {
    onClick: handler,
    onKeyDown: (e) => {
      if (handler && (e.key === "Enter" || e.key === " ")) {
        e.preventDefault();
        handler();
      }
    },
    role: handler ? "button" : undefined,
    tabIndex: handler ? 0 : undefined,
    sx: {
      cursor: handler ? "pointer" : "default",
      borderRadius: 0.75,
      px: 0.25,
      "&:hover": handler ? { bgcolor: "rgba(0, 151, 178, 0.08)" } : {},
    },
  };
}

/** "By employee | By time" and, for By time, "30 min | 15 min". */
export function BreaksViewToggle({ view, onViewChange, interval, onIntervalChange }) {
  return (
    <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap" className="no-print">
      <ToggleButtonGroup size="small" exclusive value={view} onChange={(_, next) => next && onViewChange?.(next)}>
        <ToggleButton value={BREAKS_VIEW.EMPLOYEE} sx={toggleSx} data-breaks-view={BREAKS_VIEW.EMPLOYEE}>
          By employee
        </ToggleButton>
        <ToggleButton value={BREAKS_VIEW.TIME} sx={toggleSx} data-breaks-view={BREAKS_VIEW.TIME}>
          By time
        </ToggleButton>
      </ToggleButtonGroup>
      {view === BREAKS_VIEW.TIME ? (
        <ToggleButtonGroup size="small" exclusive value={interval} onChange={(_, next) => next && onIntervalChange?.(next)}>
          {BREAK_INTERVAL_OPTIONS.map((minutes) => (
            <ToggleButton key={minutes} value={minutes} sx={toggleSx} data-break-interval={minutes}>
              {minutes} min
            </ToggleButton>
          ))}
        </ToggleButtonGroup>
      ) : null}
    </Stack>
  );
}

function SlotCell({ cell, weekPeak, canEdit, onEditEntry }) {
  if (!cell?.count) {
    return (
      <TableCell>
        <Typography sx={{ fontSize: "0.72rem", color: "text.disabled" }}>—</Typography>
      </TableCell>
    );
  }
  const strength = peakIntensity(cell.peak, weekPeak);
  return (
    <TableCell data-slot-count={cell.count} data-slot-peak={cell.peak} sx={{ bgcolor: `rgba(234, 88, 12, ${(0.04 + 0.2 * strength).toFixed(3)})` }}>
      <Typography sx={{ fontSize: "0.72rem", fontWeight: 800, color: BREAK_ACCENT, lineHeight: 1.3 }}>{slotHeadline(cell)}</Typography>
      {cell.people.map((person) => {
        const entry = person.breaks[0]?.entry;
        const edit = canEdit && entry ? () => onEditEntry?.(entry) : undefined;
        return (
          <Box key={person.userId} data-slot-person={person.userId} {...activate(edit)}>
            <Typography sx={{ fontSize: "0.74rem", lineHeight: 1.3 }}>
              <Box component="span" sx={{ fontWeight: 700 }}>
                {person.name}
              </Box>
              <Box component="span" sx={{ color: "text.secondary" }}>{` ${slotPersonDetail(person)}`}</Box>
            </Typography>
          </Box>
        );
      })}
    </TableCell>
  );
}

function UntimedCell({ items, canEdit, onEditEntry }) {
  if (!items.length) {
    return (
      <TableCell>
        <Typography sx={{ fontSize: "0.72rem", color: "text.disabled" }}>—</Typography>
      </TableCell>
    );
  }
  return (
    <TableCell>
      {items.map((item, index) => {
        const edit = canEdit && item.entry ? () => onEditEntry?.(item.entry) : undefined;
        return (
          <Tooltip key={`${item.userId}-${index}`} title={item.unallocated ? UNALLOCATED_BREAK_NOTE : ""} enterDelay={300}>
            <Box data-untimed-person={item.userId} {...activate(edit)}>
              <Typography sx={{ fontSize: "0.74rem", lineHeight: 1.3 }}>
                {untimedPersonText(item)}
                {edit ? (
                  <Box component="span" sx={{ fontWeight: 800, color: "primary.main" }}>
                    {" · Set time"}
                  </Box>
                ) : null}
              </Typography>
            </Box>
          </Tooltip>
        );
      })}
    </TableCell>
  );
}

function DayHeader({ column, weekStart, children }) {
  return (
    <TableCell data-breaks-time-day={column.dow} sx={{ fontWeight: 800, bgcolor: "#f8fafc", width: 170 }}>
      <Box sx={{ whiteSpace: "nowrap" }}>
        {DAY_LABELS[column.dow]}
        <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 0.5, fontWeight: 600 }}>
          {dayDateLabel(weekStart, column.dow)}
        </Typography>
      </Box>
      {children}
    </TableCell>
  );
}

/**
 * Breaks by time: shown days as columns, 30- or 15-minute rows. Cells show who breaks in the interval,
 * their exact break times, break-hours inside the interval, and — when not everyone overlaps — the most on
 * break at once; shading follows that simultaneous count. Breaks without a time sit in their own row and
 * tasks in their own section, since neither has a time slot. Clicking a break opens its shift.
 */
export default function WeeklyScheduleBreaksByTimeView({
  weekStart,
  byTime,
  grid,
  tasksByDay = {},
  canEdit = false,
  showBreaks = true,
  endTimeEnabled = true,
  noRolesSelected = false,
  noRolesText = "No roles selected",
  onSelectAllRoles,
  taskOptions = [],
  taskSelection = null,
  onTaskSelectionChange,
  onEditEntry,
  onEditResponsibility,
  onAdd,
}) {
  const columns = byTime?.columns || [];
  const showBreakDetail = showBreaks && endTimeEnabled && !noRolesSelected;
  const gridColumns = new Map((grid?.columns || []).map((column) => [column.dow, column]));
  const hasUntimed = columns.some((column) => column.untimed.length);
  const hasUnassigned = (grid?.columns || []).some((column) => column.unassignedTasks.length);
  const minWidth = 150 + columns.length * 170;
  return (
    <Stack spacing={0.75} sx={{ pb: 2 }}>
      <BreaksNotices
        showBreaks={showBreaks}
        endTimeEnabled={endTimeEnabled}
        noRolesSelected={noRolesSelected}
        noRolesText={noRolesText}
        onSelectAllRoles={onSelectAllRoles}
      />
      {showBreakDetail ? (
        <Paper elevation={0} sx={{ border: "1px solid #e2e8f0", borderRadius: 2, overflow: "hidden", bgcolor: "#fff" }}>
          <TableContainer sx={{ overflowX: "auto" }}>
            <Table size="small" stickyHeader sx={{ "& td, & th": cellSx, tableLayout: "fixed", minWidth }}>
              <TableHead>
                <TableRow>
                  <TableCell sx={{ ...stickySx("#f8fafc"), width: 150, zIndex: 3 }}>{`Time (${byTime.interval} min)`}</TableCell>
                  {columns.map((column) => (
                    <DayHeader key={column.dow} column={column} weekStart={weekStart}>
                      <Typography sx={{ fontSize: "0.68rem", fontWeight: 700, color: column.breakHours ? BREAK_ACCENT : "text.disabled" }}>
                        {byTimeDayHeaderText(column, formatCoverageHours)}
                      </Typography>
                    </DayHeader>
                  ))}
                </TableRow>
              </TableHead>
              <TableBody>
                {!byTime.hasTimed ? (
                  <TableRow>
                    <TableCell colSpan={columns.length + 1} sx={{ color: "text.secondary" }}>
                      No timed breaks planned for these days.
                    </TableCell>
                  </TableRow>
                ) : null}
                {byTime.rows.map((row) =>
                  row.gap ? (
                    <TableRow key={`g${row.start}`} data-slot-gap>
                      <TableCell sx={{ ...stickySx("#fff"), color: "text.secondary", fontWeight: 700 }}>{row.label}</TableCell>
                      <TableCell colSpan={columns.length} sx={{ color: "text.disabled", fontStyle: "italic" }}>
                        No timed breaks
                      </TableCell>
                    </TableRow>
                  ) : (
                    <TableRow key={row.start} data-slot-start={row.start}>
                      <TableCell sx={{ ...stickySx("#fff"), whiteSpace: "nowrap" }}>{row.label}</TableCell>
                      {columns.map((column) => (
                        <SlotCell
                          key={column.dow}
                          cell={row.cells[column.dow]}
                          weekPeak={byTime.week.peak}
                          canEdit={canEdit}
                          onEditEntry={onEditEntry}
                        />
                      ))}
                    </TableRow>
                  ),
                )}
                {byTime.hasTimed ? (
                  <TableRow data-slot-total sx={{ bgcolor: "#f8fafc" }}>
                    <TableCell sx={stickySx("#f8fafc")}>
                      Scheduled total
                      <Typography sx={{ fontSize: "0.66rem", color: "text.secondary", fontWeight: 600 }}>
                        {`Week ${formatCoverageHours(byTime.week.intervalHours)}`}
                      </Typography>
                    </TableCell>
                    {columns.map((column) => (
                      <TableCell key={column.dow} sx={{ fontWeight: 800 }}>
                        {formatCoverageHours(column.intervalHours)}
                      </TableCell>
                    ))}
                  </TableRow>
                ) : null}
                {hasUntimed ? (
                  <TableRow data-slot-not-scheduled>
                    <TableCell sx={{ ...stickySx("#fff"), color: "text.secondary" }}>
                      Not scheduled
                      <Typography sx={{ fontSize: "0.66rem", color: "text.secondary", fontWeight: 600 }}>
                        {`Week ${formatCoverageHours(byTime.week.untimedBreakHours)} · no time yet`}
                      </Typography>
                    </TableCell>
                    {columns.map((column) => (
                      <UntimedCell key={column.dow} items={column.untimed} canEdit={canEdit} onEditEntry={onEditEntry} />
                    ))}
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </TableContainer>
        </Paper>
      ) : null}

      <Typography variant="subtitle2" sx={{ fontWeight: 800, pt: 0.5 }}>
        Tasks
      </Typography>
      <TaskFilter options={taskOptions} selection={taskSelection} onChange={onTaskSelectionChange} />
      <Paper elevation={0} sx={{ border: "1px solid #e2e8f0", borderRadius: 2, overflow: "hidden", bgcolor: "#fff" }}>
        <TableContainer sx={{ overflowX: "auto" }}>
          <Table size="small" sx={{ "& td, & th": cellSx, tableLayout: "fixed", minWidth }}>
            <TableHead>
              <TableRow>
                <TableCell sx={{ ...stickySx("#f8fafc"), width: 150 }}>Tasks</TableCell>
                {columns.map((column) => (
                  <DayHeader key={column.dow} column={column} weekStart={weekStart}>
                    <Typography sx={{ fontSize: "0.68rem", fontWeight: 700, color: "text.secondary" }}>
                      {gridColumns.get(column.dow) ? gridDayTaskText(gridColumns.get(column.dow)) : ""}
                    </Typography>
                  </DayHeader>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              <TableRow data-time-tasks>
                <TableCell sx={stickySx("#fff")}>Assigned</TableCell>
                {columns.map((column) => {
                  const tasks = tasksByDay[column.dow] || [];
                  return (
                    <TableCell key={column.dow}>
                      {tasks.length ? (
                        tasks.map((task) => {
                          const edit = canEdit ? () => onEditResponsibility?.(task.item) : undefined;
                          return (
                            <Box key={task.key} data-time-task={task.role} {...activate(edit)}>
                              <Typography
                                sx={{ fontSize: "0.74rem", lineHeight: 1.3, borderLeft: `3px solid ${roleStyle(task.role).accent}`, pl: 0.5, mt: 0.25 }}
                              >
                                <Box component="span" sx={{ fontWeight: 800, color: roleStyle(task.role).accent }}>
                                  {task.label}
                                </Box>
                                {` · ${task.name}`}
                                <Box component="span" sx={{ color: task.remarks ? "text.secondary" : "text.disabled" }}>
                                  {task.remarks ? ` — ${task.remarks}` : " — no instructions"}
                                </Box>
                              </Typography>
                            </Box>
                          );
                        })
                      ) : (
                        <Typography sx={{ fontSize: "0.72rem", color: "text.disabled" }}>—</Typography>
                      )}
                    </TableCell>
                  );
                })}
              </TableRow>
              {hasUnassigned ? (
                <TableRow data-grid-unassigned sx={{ bgcolor: "#fffbeb" }}>
                  <TableCell sx={{ ...stickySx("#fffbeb"), color: "#b45309" }}>Unassigned tasks</TableCell>
                  {columns.map((column) => (
                    <TableCell key={column.dow}>
                      <Stack direction="row" spacing={0.4} useFlexGap flexWrap="wrap">
                        {(gridColumns.get(column.dow)?.unassignedTasks || []).map((code) => (
                          <Chip
                            key={code}
                            size="small"
                            variant="outlined"
                            label={scheduleRoleLabel(code)}
                            title={canEdit ? "Assign" : undefined}
                            onClick={canEdit ? () => onAdd?.({ day: column.dow, role: code, kind: ASSIGNMENT_KIND.RESPONSIBILITY }) : undefined}
                            sx={{ height: 20, fontSize: "0.66rem", fontWeight: 700, borderStyle: "dashed", maxWidth: "100%" }}
                          />
                        ))}
                      </Stack>
                    </TableCell>
                  ))}
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>
      <Typography variant="caption" color="text.secondary" sx={{ px: 0.25 }}>
        Break-hours in a row count only the part of each break inside that interval, so rows add up to the day&apos;s
        scheduled total. &ldquo;Max at once&rdquo; is shown when not everyone listed is on break together. Click a break
        to change it in the shift. Breaks without a time are listed under Not scheduled and never placed in a row.
      </Typography>
    </Stack>
  );
}
