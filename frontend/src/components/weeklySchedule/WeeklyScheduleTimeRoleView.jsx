import { Box, Button, Chip, IconButton, Paper, Stack, Tooltip, Typography } from "@mui/material";
import AddCircleOutlineIcon from "@mui/icons-material/AddCircleOutline";
import AddIcon from "@mui/icons-material/Add";
import { formatTime12 } from "../datetime/scheduleTimeUi";
import { DAY_LABELS } from "./weeklyScheduleDates";
import { roleStyle } from "./weeklyScheduleRoles";
import { ASSIGNMENT_KIND, dayDateLabel, timeBlockLabel } from "./weeklyScheduleTimeBlocks";

function PersonItem({ person, onClick, shiftLabel }) {
  const body = (
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
        px: 0.85,
        py: 0.35,
        borderRadius: 1.25,
        border: "1px solid #e2e8f0",
        bgcolor: "#fff",
        cursor: onClick ? "pointer" : "default",
        minWidth: 0,
        maxWidth: "100%",
        "&:hover": onClick ? { borderColor: "rgba(0, 151, 178, 0.45)", bgcolor: "rgba(0, 151, 178, 0.04)" } : {},
      }}
    >
      <Typography variant="body2" fontWeight={700} sx={{ fontSize: "0.78rem", lineHeight: 1.3 }}>
        {person.name}
      </Typography>
      {person.remarks ? (
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ display: "block", lineHeight: 1.25, whiteSpace: "normal", wordBreak: "break-word" }}
        >
          {person.remarks}
        </Typography>
      ) : null}
    </Box>
  );
  if (!shiftLabel) return body;
  return (
    <Tooltip title={shiftLabel} enterDelay={400}>
      {body}
    </Tooltip>
  );
}

function RoleRow({ group, children, onAdd }) {
  const style = roleStyle(group.role);
  return (
    <Box
      sx={{
        display: "grid",
        gridTemplateColumns: { xs: "1fr", sm: "180px 1fr" },
        gap: { xs: 0.5, sm: 1 },
        alignItems: "start",
        py: 0.65,
        "&:not(:last-of-type)": { borderBottom: "1px dashed #e8eef2" },
      }}
    >
      <Stack direction="row" spacing={0.5} alignItems="center" sx={{ minWidth: 0 }}>
        <Box sx={{ width: 4, alignSelf: "stretch", minHeight: 18, borderRadius: 2, bgcolor: style.accent, flexShrink: 0 }} />
        <Typography variant="body2" fontWeight={800} sx={{ color: style.accent, fontSize: "0.8rem" }} noWrap>
          {group.label}
        </Typography>
        <Chip
          size="small"
          label={group.count}
          sx={{ height: 18, fontSize: "0.65rem", fontWeight: 800, bgcolor: style.chipBg, color: style.accent }}
        />
        {onAdd ? (
          <IconButton size="small" aria-label={`Add ${group.label}`} onClick={onAdd} sx={{ p: 0.25 }}>
            <AddIcon sx={{ fontSize: 15 }} />
          </IconButton>
        ) : null}
      </Stack>
      <Stack direction="row" spacing={0.5} useFlexGap flexWrap="wrap" sx={{ minWidth: 0 }}>
        {children}
      </Stack>
    </Box>
  );
}

/** `days` comes from buildTimeRoleDays so screen, print, and export share one grouping. */
export default function WeeklyScheduleTimeRoleView({
  weekStart,
  days,
  endTimeEnabled = true,
  canEdit = false,
  onEditEntry,
  onEditResponsibility,
  onAdd,
}) {
  return (
    <Stack spacing={1.25} sx={{ pb: 2 }}>
      {(days || []).map((day) => {
        const empty = !day.blocks.length && !day.responsibilities.length;
        return (
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

            {empty ? (
              <Typography variant="body2" color="text.secondary" sx={{ px: 1.5, py: 1.25 }}>
                No assignments.
              </Typography>
            ) : null}

            {day.blocks.map((block) => (
              <Box
                key={block.key}
                sx={{
                  display: "grid",
                  gridTemplateColumns: { xs: "1fr", md: "170px 1fr" },
                  borderBottom: "1px solid #eef2f6",
                }}
              >
                <Box sx={{ px: 1.5, pt: 1, pb: { xs: 0, md: 1 } }}>
                  <Typography variant="body2" fontWeight={800} sx={{ fontSize: "0.82rem", whiteSpace: "nowrap" }}>
                    {timeBlockLabel(block, endTimeEnabled)}
                  </Typography>
                </Box>
                <Box sx={{ px: 1.5, py: 0.5 }}>
                  {block.roles.map((group) => (
                    <RoleRow
                      key={group.role}
                      group={group}
                      onAdd={
                        canEdit
                          ? () =>
                              onAdd?.({
                                day: day.dow,
                                role: group.role,
                                startTime: block.start_time,
                                endTime: block.end_time,
                              })
                          : null
                      }
                    >
                      {group.people.map((person) => (
                        <PersonItem
                          key={person.key}
                          person={person}
                          onClick={canEdit ? () => onEditEntry?.(person.entry) : undefined}
                          shiftLabel={
                            !person.fullShift && endTimeEnabled
                              ? `Part of ${formatTime12(person.entry.start_time)} – ${formatTime12(person.entry.end_time)} shift`
                              : ""
                          }
                        />
                      ))}
                    </RoleRow>
                  ))}
                </Box>
              </Box>
            ))}

            {day.responsibilities.length ? (
              <Box sx={{ px: 1.5, py: 0.75, bgcolor: "#fcfcfd" }}>
                <Stack direction="row" alignItems="center" spacing={0.75} sx={{ mb: 0.25 }}>
                  <Typography
                    variant="overline"
                    sx={{ fontWeight: 800, letterSpacing: "0.08em", fontSize: "0.66rem", color: "text.secondary" }}
                  >
                    Daily Responsibilities
                  </Typography>
                  <Typography variant="caption" color="text.disabled">
                    no time slot · not counted in hours
                  </Typography>
                </Stack>
                {day.responsibilities.map((group) => (
                  <RoleRow
                    key={group.role}
                    group={group}
                    onAdd={
                      canEdit
                        ? () => onAdd?.({ day: day.dow, role: group.role, kind: ASSIGNMENT_KIND.RESPONSIBILITY })
                        : null
                    }
                  >
                    {group.people.map((person) => (
                      <PersonItem
                        key={person.key}
                        person={person}
                        onClick={canEdit ? () => onEditResponsibility?.(person.item) : undefined}
                      />
                    ))}
                  </RoleRow>
                ))}
              </Box>
            ) : null}
          </Paper>
        );
      })}
    </Stack>
  );
}
