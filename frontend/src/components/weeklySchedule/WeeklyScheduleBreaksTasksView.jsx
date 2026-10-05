import {
  Alert,
  Box,
  Button,
  Chip,
  IconButton,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from "@mui/material";
import AddCircleOutlineIcon from "@mui/icons-material/AddCircleOutline";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";
import { DAY_LABELS } from "./weeklyScheduleDates";
import { roleStyle, scheduleRoleLabel, UNALLOCATED_BREAK_NOTE } from "./weeklyScheduleRoles";
import { ASSIGNMENT_KIND, dayDateLabel, formatCoverageHours } from "./weeklyScheduleTimeBlocks";
import { gridDayBreakText, gridDayTaskText } from "./weeklyScheduleBreaksGrid";
import { isCodeSelected, toggleSelectionCode } from "./weeklyScheduleViewFilters";

const BREAK_ACCENT = "#9a3412";
const cellSx = { verticalAlign: "top", borderColor: "#eef2f6", px: 0.75, py: 0.5, fontSize: "0.78rem" };
const clickableSx = (enabled) => ({
  cursor: enabled ? "pointer" : "default",
  borderRadius: 0.75,
  px: 0.25,
  "&:hover": enabled ? { bgcolor: "rgba(0, 151, 178, 0.08)" } : {},
});

function minutesText(hours) {
  return `${Math.round(Number(hours || 0) * 60)} min`;
}

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
  };
}

export function BreaksNotices({ showBreaks, endTimeEnabled, noRolesSelected, noRolesText, onSelectAllRoles }) {
  return (
    <>
      {!endTimeEnabled ? <Alert severity="info">Planned break times need shift end times. Tasks are listed below.</Alert> : null}
      {endTimeEnabled && !showBreaks ? <Alert severity="info">Break details are hidden in this view.</Alert> : null}
      {noRolesSelected && showBreaks && endTimeEnabled ? (
        <Alert
          severity="info"
          data-no-roles-selected
          action={
            onSelectAllRoles ? (
              <Button color="inherit" size="small" onClick={onSelectAllRoles} sx={{ fontWeight: 800 }}>
                Select all
              </Button>
            ) : null
          }
        >
          {`${noRolesText}—breaks are hidden until a role is selected. Tasks are still shown.`}
        </Alert>
      ) : null}
    </>
  );
}

export function TaskFilter({ options, selection, onChange }) {
  if (!options.length || !onChange) return null;
  const allSelected = !Array.isArray(selection);
  return (
    <Stack direction="row" spacing={0.5} alignItems="center" useFlexGap sx={{ overflowX: "auto", whiteSpace: "nowrap", pb: 0.25 }}>
      <Typography variant="caption" sx={{ fontWeight: 800, color: "text.secondary", fontSize: "0.68rem", letterSpacing: "0.04em", mr: 0.25 }}>
        TASKS
      </Typography>
      <Chip
        size="small"
        label="All"
        onClick={() => onChange(null)}
        variant={allSelected ? "filled" : "outlined"}
        color={allSelected ? "primary" : "default"}
        sx={{ height: 22, fontWeight: 700, fontSize: "0.72rem" }}
      />
      {options.map((code) => {
        const selected = isCodeSelected(selection, code);
        return (
          <Chip
            key={code}
            size="small"
            label={scheduleRoleLabel(code)}
            data-task-filter={code}
            onClick={() => onChange(toggleSelectionCode(selection, code, options))}
            variant={selected ? "filled" : "outlined"}
            sx={{
              height: 22,
              fontWeight: 700,
              fontSize: "0.72rem",
              bgcolor: selected ? roleStyle(code).chipBg : undefined,
              color: selected ? roleStyle(code).accent : undefined,
              border: `1px solid ${selected ? roleStyle(code).border : VEEWASH_DASHBOARD.snapshotBorder}`,
            }}
          />
        );
      })}
    </Stack>
  );
}

function TimedBreak({ range, canEdit, onEditEntry }) {
  const edit = canEdit && range.entry ? () => onEditEntry?.(range.entry) : undefined;
  return (
    <Box data-break-row="timed" {...activate(edit)} sx={clickableSx(Boolean(edit))}>
      <Typography component="span" sx={{ fontSize: "0.76rem", fontWeight: 800, color: BREAK_ACCENT }}>
        {range.label}
      </Typography>
      {range.overlapsWith?.length ? (
        <Typography component="span" sx={{ fontSize: "0.68rem", color: "#b45309", fontWeight: 700 }}>
          {` · with ${range.overlapsWith.join(", ")}`}
        </Typography>
      ) : null}
    </Box>
  );
}

function UntimedBreak({ item, canEdit, onEditEntry }) {
  const edit = canEdit && item.entry ? () => onEditEntry?.(item.entry) : undefined;
  const allocation = item.unallocated
    ? "not allocated to a role"
    : `from ${item.allocatedRole ? scheduleRoleLabel(item.allocatedRole) : "time without a role"}`;
  return (
    <Tooltip title={item.unallocated ? UNALLOCATED_BREAK_NOTE : ""} enterDelay={300}>
      <Box data-break-row="untimed" data-untimed-break-allocation={item.unallocated ? "unallocated" : "allocated"} {...activate(edit)} sx={clickableSx(Boolean(edit))}>
        <Typography component="span" sx={{ fontSize: "0.76rem", fontWeight: 800, color: "text.secondary" }}>
          Not scheduled
        </Typography>
        <Typography component="span" sx={{ fontSize: "0.7rem", color: "text.secondary" }}>
          {` · ${minutesText(item.hours)}`}
        </Typography>
        {edit ? (
          <Typography component="span" sx={{ fontSize: "0.7rem", fontWeight: 800, color: "primary.main" }}>
            {" · Set time"}
          </Typography>
        ) : null}
        <Typography
          sx={{ fontSize: "0.66rem", lineHeight: 1.25, color: item.unallocated ? BREAK_ACCENT : "text.disabled", fontWeight: item.unallocated ? 700 : 400 }}
        >
          {allocation}
        </Typography>
      </Box>
    </Tooltip>
  );
}

function TaskLine({ task, canEdit, onEditResponsibility }) {
  const edit = canEdit ? () => onEditResponsibility?.(task.item) : undefined;
  return (
    <Box data-grid-task={task.role} {...activate(edit)} sx={{ ...clickableSx(Boolean(edit)), borderLeft: `3px solid ${roleStyle(task.role).accent}`, pl: 0.5, mt: 0.25 }}>
      <Typography sx={{ fontSize: "0.74rem", lineHeight: 1.3 }}>
        <Box component="span" sx={{ fontWeight: 800, color: roleStyle(task.role).accent }}>
          {task.label}
        </Box>
        {task.remarks ? (
          <Box component="span" sx={{ color: "text.secondary" }}>{` — ${task.remarks}`}</Box>
        ) : (
          <Box component="span" sx={{ color: "text.disabled" }}>{" — no instructions"}</Box>
        )}
      </Typography>
    </Box>
  );
}

function GridCell({ cell, showBreakDetail, canEdit, onEditEntry, onEditResponsibility, onAddTask, userId, dow }) {
  const empty = !cell || (!cell.timed.length && !cell.untimed.length && !cell.tasks.length);
  return (
    <TableCell sx={{ ...cellSx, position: "relative", "&:hover .grid-add-task": { opacity: 1 } }}>
      {empty ? (
        cell?.hasShift && showBreakDetail ? (
          <Typography sx={{ fontSize: "0.7rem", color: "text.disabled" }}>No break planned</Typography>
        ) : (
          <Typography sx={{ fontSize: "0.74rem", color: "text.disabled" }}>—</Typography>
        )
      ) : (
        <>
          {cell.timed.map((range) => (
            <TimedBreak key={`t${range.start}-${range.end}`} range={range} canEdit={canEdit} onEditEntry={onEditEntry} />
          ))}
          {cell.untimed.map((item, index) => (
            <UntimedBreak key={`u${index}`} item={item} canEdit={canEdit} onEditEntry={onEditEntry} />
          ))}
          {cell.tasks.map((task) => (
            <TaskLine key={task.key} task={task} canEdit={canEdit} onEditResponsibility={onEditResponsibility} />
          ))}
        </>
      )}
      {canEdit && onAddTask ? (
        <IconButton
          size="small"
          className="grid-add-task no-print"
          aria-label="Add task"
          title="Add task"
          onClick={() => onAddTask({ userId, day: dow })}
          sx={{ position: "absolute", top: 1, right: 1, p: 0.25, opacity: { xs: 0.6, md: 0 } }}
        >
          <AddCircleOutlineIcon sx={{ fontSize: 15 }} />
        </IconButton>
      ) : null}
    </TableCell>
  );
}

/**
 * Breaks & tasks grid: shown days as columns, employees as rows. Each cell lists timed breaks, breaks
 * without a time ("Not scheduled"), and tasks with instructions; every item opens the same shift or task
 * dialog as the other views. Day headers carry the day's break total and task count; the last row holds
 * the task types nobody has that day. Tasks follow the task filter, never the role selection.
 */
export default function WeeklyScheduleBreaksTasksView({
  weekStart,
  grid,
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
  onAddTask,
}) {
  const columns = grid?.columns || [];
  const rows = grid?.rows || [];
  const showBreakDetail = showBreaks && endTimeEnabled && !noRolesSelected;
  const hasUnassigned = columns.some((column) => column.unassignedTasks.length);
  return (
    <Stack spacing={0.75} sx={{ pb: 2 }}>
      <BreaksNotices
        showBreaks={showBreaks}
        endTimeEnabled={endTimeEnabled}
        noRolesSelected={noRolesSelected}
        noRolesText={noRolesText}
        onSelectAllRoles={onSelectAllRoles}
      />
      <TaskFilter options={taskOptions} selection={taskSelection} onChange={onTaskSelectionChange} />
      <Paper elevation={0} sx={{ border: "1px solid #e2e8f0", borderRadius: 2, overflow: "hidden", bgcolor: "#fff" }}>
        <TableContainer sx={{ overflowX: "auto" }}>
          <Table size="small" stickyHeader sx={{ "& td, & th": cellSx, tableLayout: "fixed", minWidth: 140 + columns.length * 150 }}>
            <TableHead>
              <TableRow>
                <TableCell sx={{ fontWeight: 800, width: 140, position: "sticky", left: 0, zIndex: 3, bgcolor: "#f8fafc" }}>
                  Employee
                </TableCell>
                {columns.map((column) => (
                  <TableCell key={column.dow} data-breaks-tasks-day={column.dow} sx={{ fontWeight: 800, bgcolor: "#f8fafc", width: 150 }}>
                    <Box sx={{ whiteSpace: "nowrap" }}>
                      {DAY_LABELS[column.dow]}
                      <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 0.5, fontWeight: 600 }}>
                        {dayDateLabel(weekStart, column.dow)}
                      </Typography>
                    </Box>
                    {showBreakDetail ? (
                      <Typography sx={{ fontSize: "0.68rem", fontWeight: 700, color: column.breakHours ? BREAK_ACCENT : "text.disabled" }}>
                        {gridDayBreakText(column, formatCoverageHours) || "No breaks"}
                      </Typography>
                    ) : null}
                    <Typography sx={{ fontSize: "0.68rem", fontWeight: 700, color: "text.secondary" }}>{gridDayTaskText(column)}</Typography>
                  </TableCell>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.length ? (
                rows.map((row) => (
                  <TableRow key={row.userId} data-grid-employee={row.userId}>
                    <TableCell sx={{ position: "sticky", left: 0, zIndex: 1, bgcolor: "#fff", fontWeight: 800 }}>
                      {row.name}
                      <Typography sx={{ fontSize: "0.66rem", color: "text.secondary", fontWeight: 600 }}>
                        {[
                          showBreakDetail && row.breakHours ? `${formatCoverageHours(row.breakHours)} breaks` : "",
                          row.taskCount ? `${row.taskCount} ${row.taskCount === 1 ? "task" : "tasks"}` : "",
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </Typography>
                    </TableCell>
                    {columns.map((column) => (
                      <GridCell
                        key={column.dow}
                        cell={row.cells[column.dow]}
                        showBreakDetail={showBreakDetail}
                        canEdit={canEdit}
                        onEditEntry={onEditEntry}
                        onEditResponsibility={onEditResponsibility}
                        onAddTask={onAddTask}
                        userId={row.userId}
                        dow={column.dow}
                      />
                    ))}
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={columns.length + 1} sx={{ color: "text.secondary" }}>
                    {showBreakDetail ? "No breaks or tasks planned for these days." : "No tasks assigned for these days."}
                  </TableCell>
                </TableRow>
              )}
              {hasUnassigned ? (
                <TableRow data-grid-unassigned sx={{ bgcolor: "#fffbeb" }}>
                  <TableCell sx={{ position: "sticky", left: 0, zIndex: 1, bgcolor: "#fffbeb", fontWeight: 800, color: "#b45309" }}>
                    Unassigned tasks
                  </TableCell>
                  {columns.map((column) => (
                    <TableCell key={column.dow}>
                      <Stack direction="row" spacing={0.4} useFlexGap flexWrap="wrap">
                        {column.unassignedTasks.map((code) => (
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
        Click a break to change it in the shift. Tasks are whole-day assignments with instructions; they have no times and add no hours.
      </Typography>
    </Stack>
  );
}
