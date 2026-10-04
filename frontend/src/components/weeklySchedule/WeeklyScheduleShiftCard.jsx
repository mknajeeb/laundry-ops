import { useState } from "react";
import {
  Box,
  IconButton,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  Paper,
  Stack,
  Tooltip,
  Typography,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import ContentCopyOutlinedIcon from "@mui/icons-material/ContentCopyOutlined";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import CheckIcon from "@mui/icons-material/Check";
import { formatTime12 } from "../datetime/scheduleTimeUi";
import {
  ENTITY_TAB_LABELS,
  resolveEntryEmployerAffiliation,
  shiftEntityOptionsForOrg,
  SHIFT_ENTITY,
} from "./weeklyScheduleEmployerTabs";
import { entityLabel } from "../../payroll/businessEntity";
import {
  entryBreakBreakdown,
  entryBreakLines,
  entryRoleAssignments,
  entryRoleCardStyle,
  entryRoleScopeView,
  formatHours,
  formatUnallocatedBreak,
  isScheduleTask,
  NO_ROLE_LABEL,
  parseEntryRoles,
  roleCompactLabel,
  roleLabels,
  UNALLOCATED_BREAK_NOTE,
} from "./weeklyScheduleRoles";
import ScheduleRoleChip from "./ScheduleRoleChip";

/**
 * One shift in the employee grid. With a role selection (`roleFilter`), the card shows only the selected
 * roles' segments and net hours (`roleScope` from `summarizeRoleSelection`); it still edits the whole shift.
 */
export default function WeeklyScheduleShiftCard({
  entry,
  employee,
  roleFilter = null,
  roleScope = null,
  onEdit,
  onDelete,
  onDuplicate,
  onSetEmployer,
  onDragStart,
  onDragEnd,
  dragging,
  duplicating = false,
  muted = false,
  showRoleLabels = true,
  showBreakMinutes = true,
  scheduleEndTimeEnabled = true,
  organizationSlug = null,
}) {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("md"));
  const [menuAnchor, setMenuAnchor] = useState(null);
  const menuOpen = Boolean(menuAnchor);

  const scoped = Array.isArray(roleFilter);
  const scopeView = scoped ? entryRoleScopeView(entry, roleFilter, roleScope) : null;
  const roles = scoped ? scopeView.roles : parseEntryRoles(entry);
  const cardStyle = entryRoleCardStyle(roles);
  const hours = scoped ? scopeView.hours : Number(entry.hours || 0);
  const showBreaks = scheduleEndTimeEnabled && showBreakMinutes;
  const breakParts = entryBreakBreakdown(entry);
  const breakLines = showBreaks ? [...(scoped ? scopeView.breaks : entryBreakLines(entry))] : [];
  const formatH = (value) => `${formatHours(value)}h`;
  const shiftRange = `${formatTime12(entry.start_time)} – ${formatTime12(entry.end_time)}`;
  const pending = scoped && scopeView.unallocatedBreakHours > 0.0001;
  const timedRoles = parseEntryRoles(entry).filter((role) => !isScheduleTask(role));
  const multiRoleUntimed = !scoped && showBreaks && timedRoles.length > 1 && breakParts.unscheduledBreakMinutes > 0;
  if (pending && showBreaks) breakLines.push(formatUnallocatedBreak(scopeView.unallocatedBreakHours));
  if (pending || multiRoleUntimed) breakLines.push(UNALLOCATED_BREAK_NOTE);
  let hoursLabel = showBreaks && breakParts.breakMinutes > 0
    ? `${formatH(hours)} net · ${formatH(breakParts.grossMinutes / 60)} gross`
    : formatH(hours);
  if (scoped) {
    const kind = pending ? " gross" : showBreaks && breakParts.breakMinutes > 0 ? " net" : "";
    hoursLabel = `${formatH(hours)}${kind} ${roles.map((role) => roleCompactLabel(role)).join(" + ")}`;
  }
  const timeLines = scheduleEndTimeEnabled
    ? scoped && scopeView.segments.length
      ? scopeView.segments.map((segment) => (roles.length > 1 ? `${segment.label} ${roleCompactLabel(segment.role)}` : segment.label))
      : [shiftRange]
    : [formatTime12(entry.start_time)];
  const roleTooltip = [
    showRoleLabels ? roleLabels(roles) : "",
    scoped && scheduleEndTimeEnabled ? `Shift ${shiftRange}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
  const assignmentDetails = showRoleLabels
    ? entryRoleAssignments(entry).filter(
      (a) => (!scoped || roles.includes(a.role)) && (a.remarks || (!scoped && !a.full_shift && scheduleEndTimeEnabled)),
    )
    : [];
  const hasActions = Boolean((onEdit || onDuplicate || onDelete || onSetEmployer) && !muted);
  const shiftEmployer = resolveEntryEmployerAffiliation(entry, employee, organizationSlug);
  const canSetEmployer = Boolean(onSetEmployer && !muted);
  const shiftEntityOptions = shiftEntityOptionsForOrg(organizationSlug);

  const closeMenu = () => setMenuAnchor(null);

  return (
    <Tooltip title={roleTooltip || ""} disableHoverListener={!roleTooltip} enterDelay={500}>
    <Paper
      elevation={0}
      data-shift-card
      data-role-scoped={scoped ? "true" : undefined}
      draggable={!muted}
      onDragStart={(e) => {
        if (muted) return;
        e.stopPropagation();
        e.dataTransfer.setData("text/plain", String(entry.id));
        e.dataTransfer.effectAllowed = "move";
        onDragStart?.(entry);
      }}
      onDragEnd={() => onDragEnd?.()}
      onClick={(e) => {
        e.stopPropagation();
        onEdit?.(entry);
      }}
      sx={{
        position: "relative",
        pl: 1.15,
        pr: hasActions ? 0.25 : 0.75,
        py: 0.35,
        mb: 0.35,
        borderRadius: 1.25,
        cursor: muted ? "default" : "grab",
        border: `1px solid ${muted ? "#e8ecf0" : cardStyle.border}`,
        bgcolor: muted ? "#f8fafc" : cardStyle.bg,
        opacity: dragging ? 0.45 : muted ? 0.72 : 1,
        boxShadow: "none",
        overflow: "visible",
        transition: "border-color 0.12s ease, background-color 0.12s ease, box-shadow 0.12s ease",
        "&:hover": muted
          ? {}
          : {
              bgcolor: cardStyle.hoverBg,
              borderColor: cardStyle.accent,
              boxShadow: "0 1px 4px rgba(15, 23, 42, 0.06)",
            },
        "&:active": muted ? {} : { cursor: "grabbing" },
        "&:hover .shift-card-menu-btn": {
          opacity: 1,
        },
        "&::before": muted
          ? undefined
          : {
              content: '""',
              position: "absolute",
              left: 0,
              top: 0,
              bottom: 0,
              width: cardStyle.multiRole ? 4 : 3,
              background: cardStyle.stripe,
            },
      }}
    >
      <Box sx={{ display: "flex", alignItems: "flex-start", gap: 0.25, minWidth: 0 }}>
        <Box sx={{ flex: 1, minWidth: 0, pr: hasActions ? 0 : 0.25 }}>
          {timeLines.map((line) => (
            <Typography
              key={line}
              variant="caption"
              fontWeight={700}
              data-shift-time
              sx={{
                color: "text.primary",
                fontSize: "0.72rem",
                lineHeight: 1.3,
                whiteSpace: "nowrap",
                display: "block",
                overflow: "visible",
                textOverflow: "clip",
              }}
            >
              {line}
            </Typography>
          ))}
          {scheduleEndTimeEnabled ? (
            <Typography
              variant="caption"
              data-shift-hours
              sx={{
                display: "block",
                mt: 0.15,
                color: "text.secondary",
                fontSize: "0.65rem",
                fontWeight: 700,
                lineHeight: 1.25,
              }}
            >
              {hoursLabel}
            </Typography>
          ) : null}
          {breakLines.map((line) => (
            <Typography
              key={line}
              variant="caption"
              data-break-line
              sx={{
                display: "block",
                mt: 0.15,
                color: line.endsWith("Not scheduled") ? "text.secondary" : "#9a3412",
                fontSize: "0.62rem",
                fontWeight: 700,
                lineHeight: 1.25,
                whiteSpace: "normal",
              }}
            >
              {line}
            </Typography>
          ))}
          {showRoleLabels && roles.length ? (
            <Stack direction="row" spacing={0.35} useFlexGap flexWrap="wrap" sx={{ mt: 0.35, maxWidth: "100%" }}>
              {roles.map((roleKey) => (
                <ScheduleRoleChip key={roleKey} roleKey={roleKey} />
              ))}
            </Stack>
          ) : null}
          {showRoleLabels && !roles.length ? (
            <Typography
              variant="caption"
              sx={{ display: "block", mt: 0.35, color: "text.secondary", fontSize: "0.62rem", fontWeight: 700 }}
            >
              {NO_ROLE_LABEL}
            </Typography>
          ) : null}
          {assignmentDetails.map((a) => (
            <Typography
              key={`${a.role}-${a.start_time}`}
              variant="caption"
              sx={{
                display: "block",
                mt: 0.2,
                color: "text.secondary",
                fontSize: "0.62rem",
                lineHeight: 1.25,
                whiteSpace: "normal",
                wordBreak: "break-word",
              }}
            >
              <Box component="span" sx={{ fontWeight: 800 }}>
                {roleCompactLabel(a.role)}
              </Box>
              {!a.full_shift && scheduleEndTimeEnabled
                ? ` ${formatTime12(a.start_time)}–${formatTime12(a.end_time)}`
                : ""}
              {a.remarks ? ` · ${a.remarks}` : ""}
            </Typography>
          ))}
        </Box>

        {hasActions ? (
          <>
            <Tooltip title="Shift actions">
              <IconButton
                className="shift-card-menu-btn"
                size="small"
                aria-label="Shift actions"
                onClick={(e) => {
                  e.stopPropagation();
                  setMenuAnchor(e.currentTarget);
                }}
                sx={{
                  p: 0.25,
                  mt: -0.15,
                  mr: 0.1,
                  flexShrink: 0,
                  opacity: isMobile ? 1 : 0,
                  transition: "opacity 0.12s ease",
                  color: cardStyle.accent,
                }}
              >
                <MoreVertIcon sx={{ fontSize: 16 }} />
              </IconButton>
            </Tooltip>
            <Menu
              anchorEl={menuAnchor}
              open={menuOpen}
              onClose={closeMenu}
              onClick={(e) => e.stopPropagation()}
              anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
              transformOrigin={{ vertical: "top", horizontal: "right" }}
              slotProps={{ paper: { sx: { minWidth: 196 } } }}
            >
              {canSetEmployer ? (
                <>
                  {shiftEntityOptions.map((affiliation) => {
                    const selected = shiftEmployer === affiliation;
                    const label = entityLabel(affiliation);
                    return (
                      <MenuItem
                        key={affiliation}
                        selected={selected}
                        onClick={() => {
                          closeMenu();
                          if (!selected) onSetEmployer(entry, affiliation);
                        }}
                      >
                        <ListItemIcon sx={{ minWidth: 28 }}>
                          {selected ? <CheckIcon fontSize="small" /> : <Box sx={{ width: 18 }} />}
                        </ListItemIcon>
                        <ListItemText primaryTypographyProps={{ fontSize: "0.875rem", fontWeight: 600 }}>
                          {label}
                        </ListItemText>
                      </MenuItem>
                    );
                  })}
                  {(onEdit || onDuplicate || onDelete) ? (
                    <Box sx={{ my: 0.5, borderTop: "1px solid", borderColor: "divider" }} />
                  ) : null}
                </>
              ) : null}
              {onEdit ? (
                <MenuItem
                  onClick={() => {
                    closeMenu();
                    onEdit(entry);
                  }}
                >
                  <ListItemIcon>
                    <EditOutlinedIcon fontSize="small" />
                  </ListItemIcon>
                  <ListItemText primaryTypographyProps={{ fontSize: "0.875rem", fontWeight: 600 }}>
                    Edit shift
                  </ListItemText>
                </MenuItem>
              ) : null}
              {onDuplicate ? (
                <MenuItem
                  disabled={duplicating}
                  onClick={() => {
                    closeMenu();
                    onDuplicate(entry);
                  }}
                >
                  <ListItemIcon>
                    <ContentCopyOutlinedIcon fontSize="small" />
                  </ListItemIcon>
                  <ListItemText primaryTypographyProps={{ fontSize: "0.875rem", fontWeight: 600 }}>
                    Duplicate
                  </ListItemText>
                </MenuItem>
              ) : null}
              {onDelete ? (
                <MenuItem
                  onClick={() => {
                    closeMenu();
                    onDelete(entry);
                  }}
                  sx={{ color: "error.main" }}
                >
                  <ListItemIcon sx={{ color: "error.main" }}>
                    <DeleteOutlineIcon fontSize="small" />
                  </ListItemIcon>
                  <ListItemText primaryTypographyProps={{ fontSize: "0.875rem", fontWeight: 600 }}>
                    Delete
                  </ListItemText>
                </MenuItem>
              ) : null}
            </Menu>
          </>
        ) : null}
      </Box>
    </Paper>
    </Tooltip>
  );
}
