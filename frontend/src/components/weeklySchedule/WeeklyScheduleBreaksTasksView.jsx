import { useMemo } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import { formatTime12 } from "../datetime/scheduleTimeUi";
import { DAY_LABELS } from "./weeklyScheduleDates";
import { roleStyle, scheduleRoleCatalog, scheduleRoleLabel } from "./weeklyScheduleRoles";
import { ASSIGNMENT_KIND, dayDateLabel, formatCoverageHours } from "./weeklyScheduleTimeBlocks";
import { PersonLine } from "./WeeklyScheduleTimeRoleView";

const BREAK_ACCENT = "#9a3412";
const cellSx = { verticalAlign: "top", borderColor: "#eef2f6", px: 1, py: 0.6, fontSize: "0.8rem" };

function shiftLabel(entry) {
  return entry ? `${formatTime12(entry.start_time)} – ${formatTime12(entry.end_time)}` : "";
}

function SectionTitle({ children, note }) {
  return (
    <Stack direction="row" alignItems="baseline" spacing={0.75} sx={{ px: 1.5, pt: 1, pb: 0.5 }}>
      <Typography variant="overline" sx={{ fontWeight: 800, letterSpacing: "0.08em", fontSize: "0.68rem" }}>
        {children}
      </Typography>
      {note ? (
        <Typography variant="caption" color="text.secondary">
          {note}
        </Typography>
      ) : null}
    </Stack>
  );
}

function BreakList({ day, canEdit, onEditEntry }) {
  const rows = [
    ...day.breakRanges.map((range) => ({ ...range, timed: true })),
    ...day.unscheduledBreaks.map((item) => ({ ...item, timed: false })),
  ];
  if (!rows.length) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ px: 1.5, pb: 1 }}>
        No planned breaks.
      </Typography>
    );
  }
  return (
    <TableContainer>
      <Table size="small" sx={{ "& td, & th": cellSx }}>
        <TableHead>
          <TableRow>
            <TableCell sx={{ fontWeight: 800, minWidth: 150 }}>Break</TableCell>
            <TableCell sx={{ fontWeight: 800 }}>Employee</TableCell>
            <TableCell sx={{ fontWeight: 800 }}>Shift</TableCell>
            <TableCell sx={{ fontWeight: 800 }}>Roles paused</TableCell>
            <TableCell sx={{ fontWeight: 800 }}>Overlap</TableCell>
            {canEdit ? <TableCell /> : null}
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow key={`${row.userId}-${row.timed ? row.start : "u"}-${index}`} data-break-row>
              <TableCell sx={{ whiteSpace: "nowrap", fontWeight: 700, color: row.timed ? BREAK_ACCENT : "text.secondary" }}>
                {row.timed ? row.label : "Not scheduled"}
                <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
                  {row.timed ? formatCoverageHours(row.hours) : `${Math.round(row.hours * 60)} min · no time set`}
                </Typography>
              </TableCell>
              <TableCell sx={{ fontWeight: 700 }}>{row.name}</TableCell>
              <TableCell sx={{ whiteSpace: "nowrap" }}>{shiftLabel(row.entry)}</TableCell>
              <TableCell>
                {row.timed ? (
                  row.roles.length ? (
                    row.roles.map(scheduleRoleLabel).join(", ")
                  ) : (
                    <Typography variant="caption" color="text.secondary">
                      No role
                    </Typography>
                  )
                ) : (
                  <Typography variant="caption" color="text.secondary">
                    Not placed in any hour
                  </Typography>
                )}
              </TableCell>
              <TableCell>
                {row.timed && row.overlapsWith.length ? (
                  <Chip
                    size="small"
                    color="warning"
                    variant="outlined"
                    label={`With ${row.overlapsWith.join(", ")}`}
                    sx={{ height: 22, fontSize: "0.7rem", fontWeight: 700 }}
                  />
                ) : (
                  "—"
                )}
              </TableCell>
              {canEdit ? (
                <TableCell sx={{ whiteSpace: "nowrap" }}>
                  {row.entry ? (
                    <Button
                      size="small"
                      startIcon={<EditOutlinedIcon sx={{ fontSize: 16 }} />}
                      onClick={() => onEditEntry?.(row.entry)}
                      sx={{ fontWeight: 700, py: 0 }}
                    >
                      {row.timed ? "Edit" : "Set time"}
                    </Button>
                  ) : null}
                </TableCell>
              ) : null}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}

/** Hour by hour: who is on a timed break and the role coverage left (the same cells as the hourly matrix). */
function HourlyBreakTable({ day, columns, showNames, canEdit, onEditEntry }) {
  const rows = day.hours.filter((row) => row.breaks.count > 0);
  if (!rows.length) return null;
  return (
    <TableContainer>
      <Table size="small" sx={{ "& td, & th": cellSx }}>
        <TableHead>
          <TableRow>
            <TableCell sx={{ fontWeight: 800, minWidth: 104 }}>Hour</TableCell>
            <TableCell sx={{ fontWeight: 800, color: BREAK_ACCENT, minWidth: 150 }}>On break</TableCell>
            <TableCell sx={{ fontWeight: 800, minWidth: 220 }}>Remaining role coverage</TableCell>
            <TableCell sx={{ fontWeight: 800 }}>All shown roles</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.hour} sx={{ bgcolor: row.gap ? "#fffbeb" : "#fff" }}>
              <TableCell sx={{ fontWeight: 800, whiteSpace: "nowrap" }}>{row.label}</TableCell>
              <TableCell>
                <Typography variant="body2" sx={{ fontWeight: 800, fontSize: "0.8rem", color: BREAK_ACCENT, whiteSpace: "nowrap" }}>
                  {row.breaks.count} · {formatCoverageHours(row.breaks.hours)}
                </Typography>
                {showNames
                  ? row.breaks.people.map((person) => (
                      <PersonLine
                        key={person.userId}
                        person={person}
                        onClick={canEdit && person.entry ? () => onEditEntry?.(person.entry) : undefined}
                      />
                    ))
                  : null}
              </TableCell>
              <TableCell>
                <Stack direction="row" spacing={0.5} useFlexGap flexWrap="wrap">
                  {columns.map((role) => {
                    const cell = row.cells[role];
                    return (
                      <Chip
                        key={role}
                        size="small"
                        label={`${scheduleRoleLabel(role)} ${cell?.count || 0} · ${formatCoverageHours(cell?.hours || 0)}`}
                        sx={{
                          height: 22,
                          fontSize: "0.7rem",
                          fontWeight: 700,
                          bgcolor: cell?.count ? roleStyle(role).chipBg : "#fef3c7",
                          color: cell?.count ? roleStyle(role).accent : "#b45309",
                          border: `1px solid ${cell?.count ? roleStyle(role).border : "#fcd34d"}`,
                        }}
                      />
                    );
                  })}
                </Stack>
              </TableCell>
              <TableCell sx={{ whiteSpace: "nowrap", fontWeight: 700 }}>
                {row.gap ? "No coverage" : `${row.total.count} · ${formatCoverageHours(row.total.hours)}`}
              </TableCell>
            </TableRow>
          ))}
          <TableRow sx={{ bgcolor: "#f1f5f9" }}>
            <TableCell sx={{ fontWeight: 800 }}>Day total</TableCell>
            <TableCell sx={{ fontWeight: 800, color: BREAK_ACCENT }}>
              {day.breakTotal.count} · {formatCoverageHours(day.breakTotal.hours)}
            </TableCell>
            <TableCell colSpan={2} />
          </TableRow>
        </TableBody>
      </Table>
    </TableContainer>
  );
}

function taskCatalog() {
  return scheduleRoleCatalog().filter((role) => role.uses_time_slots === false && role.active !== false);
}

function DayTaskSection({ day, canEdit, onAdd, onEditResponsibility }) {
  const assigned = new Set(day.responsibilities.map((group) => group.role));
  const unassigned = taskCatalog().filter((role) => !assigned.has(role.code));
  return (
    <>
      {day.responsibilities.length ? (
        <Stack spacing={0.5} sx={{ px: 1.5, pb: 0.75 }}>
          {day.responsibilities.map((group) => (
            <Box key={group.role} sx={{ borderLeft: `4px solid ${roleStyle(group.role).accent}`, pl: 1 }}>
              <Stack direction="row" spacing={0.75} alignItems="center">
                <Typography variant="body2" fontWeight={800} sx={{ color: roleStyle(group.role).accent }}>
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
              {group.people.map((person) => (
                <Box
                  key={person.key}
                  role={canEdit ? "button" : undefined}
                  tabIndex={canEdit ? 0 : undefined}
                  onClick={canEdit ? () => onEditResponsibility?.(person.item) : undefined}
                  sx={{ py: 0.2, cursor: canEdit ? "pointer" : "default", "&:hover": canEdit ? { bgcolor: "#f8fafc" } : {} }}
                >
                  <Typography variant="body2" sx={{ fontSize: "0.8rem" }}>
                    <Box component="span" sx={{ fontWeight: 700 }}>
                      {person.name}
                    </Box>
                    {person.remarks ? (
                      <Box component="span" sx={{ color: "text.secondary" }}>
                        {` — ${person.remarks}`}
                      </Box>
                    ) : (
                      <Box component="span" sx={{ color: "text.disabled" }}>
                        {" — no instructions"}
                      </Box>
                    )}
                  </Typography>
                </Box>
              ))}
            </Box>
          ))}
        </Stack>
      ) : (
        <Typography variant="body2" color="text.secondary" sx={{ px: 1.5, pb: 0.75 }}>
          No tasks assigned.
        </Typography>
      )}
      {unassigned.length ? (
        <Stack direction="row" spacing={0.5} useFlexGap flexWrap="wrap" alignItems="center" sx={{ px: 1.5, pb: 1 }}>
          <Typography variant="caption" sx={{ fontWeight: 800, color: "#b45309" }}>
            Unassigned:
          </Typography>
          {unassigned.map((role) => (
            <Chip
              key={role.code}
              size="small"
              variant="outlined"
              label={canEdit ? `${role.name} · Assign` : role.name}
              onClick={
                canEdit
                  ? () => onAdd?.({ day: day.dow, role: role.code, kind: ASSIGNMENT_KIND.RESPONSIBILITY })
                  : undefined
              }
              sx={{ height: 22, fontSize: "0.7rem", fontWeight: 700, borderStyle: "dashed" }}
            />
          ))}
        </Stack>
      ) : null}
    </>
  );
}

function TaskCountsCard({ responsibilities, employeesById }) {
  const rows = useMemo(() => {
    const byUser = new Map();
    for (const item of responsibilities || []) {
      const uid = Number(item.user_id);
      if (!byUser.has(uid)) byUser.set(uid, []);
      byUser.get(uid).push(item);
    }
    return [...byUser.entries()]
      .map(([uid, items]) => ({
        uid,
        name: employeesById?.[uid]?.display_name || `User #${uid}`,
        count: items.length,
        days: new Set(items.map((item) => Number(item.day_of_week))).size,
        labels: [...new Set(items.map((item) => scheduleRoleLabel(item.role)))],
      }))
      .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  }, [responsibilities, employeesById]);
  return (
    <Paper elevation={0} sx={{ border: "1px solid #e2e8f0", borderRadius: 2.5, bgcolor: "#fff" }}>
      <SectionTitle note="tasks have no times and add no hours">Tasks per employee</SectionTitle>
      {rows.length ? (
        <TableContainer>
          <Table size="small" sx={{ "& td, & th": cellSx }}>
            <TableHead>
              <TableRow>
                <TableCell sx={{ fontWeight: 800 }}>Employee</TableCell>
                <TableCell sx={{ fontWeight: 800 }}>Tasks</TableCell>
                <TableCell sx={{ fontWeight: 800 }}>Days</TableCell>
                <TableCell sx={{ fontWeight: 800 }}>Assigned</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.uid} data-task-count-row>
                  <TableCell sx={{ fontWeight: 700 }}>{row.name}</TableCell>
                  <TableCell sx={{ fontWeight: 800 }}>{row.count}</TableCell>
                  <TableCell>{row.days}</TableCell>
                  <TableCell>{row.labels.join(", ")}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      ) : (
        <Typography variant="body2" color="text.secondary" sx={{ px: 1.5, pb: 1 }}>
          No tasks assigned in this view.
        </Typography>
      )}
    </Paper>
  );
}

/**
 * Planned breaks and tasks for the shown days. Every row opens the same shift or task dialog as the
 * other views, so there is one set of records. `days` comes from buildHourlyCoverage.
 */
export default function WeeklyScheduleBreaksTasksView({
  weekStart,
  days,
  columns,
  responsibilities,
  employeesById,
  showNames = true,
  canEdit = false,
  showBreaks = true,
  endTimeEnabled = true,
  onEditEntry,
  onEditResponsibility,
  onAdd,
}) {
  return (
    <Stack spacing={1.25} sx={{ pb: 2 }}>
      {!endTimeEnabled ? (
        <Alert severity="info">Planned break times need shift end times. Tasks are listed below.</Alert>
      ) : null}
      {!showBreaks ? <Alert severity="info">Break details are hidden in this view.</Alert> : null}
      <TaskCountsCard responsibilities={responsibilities} employeesById={employeesById} />
      {(days || []).map((day) => (
        <Paper
          key={day.dow}
          elevation={0}
          data-breaks-tasks-day={day.dow}
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
            {showBreaks && endTimeEnabled ? (
              <Typography variant="caption" sx={{ fontWeight: 700, color: BREAK_ACCENT }}>
                Timed breaks {formatCoverageHours(day.breakTotal.hours)}
                {day.unscheduledBreakTotal.hours > 0
                  ? ` · not scheduled ${formatCoverageHours(day.unscheduledBreakTotal.hours)}`
                  : ""}
              </Typography>
            ) : null}
          </Stack>
          {showBreaks && endTimeEnabled ? (
            <>
              <SectionTitle note="click a row to change the break in the shift">Breaks</SectionTitle>
              <BreakList day={day} canEdit={canEdit} onEditEntry={onEditEntry} />
              {day.breakTotal.count ? (
                <>
                  <SectionTitle note="role cells already exclude employees on break">
                    Hourly break totals &amp; remaining coverage
                  </SectionTitle>
                  <HourlyBreakTable
                    day={day}
                    columns={columns}
                    showNames={showNames}
                    canEdit={canEdit}
                    onEditEntry={onEditEntry}
                  />
                </>
              ) : null}
            </>
          ) : null}
          <SectionTitle note="whole day · no times · not counted in hours">Tasks</SectionTitle>
          <DayTaskSection day={day} canEdit={canEdit} onAdd={onAdd} onEditResponsibility={onEditResponsibility} />
        </Paper>
      ))}
    </Stack>
  );
}
