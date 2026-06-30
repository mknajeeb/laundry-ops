import { useState } from "react";
import {
  Box,
  IconButton,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  Paper,
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
import { entryRoleCardStyle, parseEntryRoles, roleLabels } from "./weeklyScheduleRoles";

export default function WeeklyScheduleShiftCard({
  entry,
  employee,
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

  const roles = parseEntryRoles(entry);
  const cardStyle = entryRoleCardStyle(roles);
  const hours = Number(entry.hours || 0);
  const breakMin = Number(entry.break_minutes || 0);
  const breakSuffix = scheduleEndTimeEnabled && showBreakMinutes && breakMin > 0 ? ` · −${breakMin}m break` : "";
  const hoursLabel = Number.isInteger(hours) ? `${hours}h` : `${hours.toFixed(1)}h`;
  const roleText = showRoleLabels ? roleLabels(roles) : "";
  const hasActions = Boolean((onEdit || onDuplicate || onDelete || onSetEmployer) && !muted);
  const shiftEmployer = resolveEntryEmployerAffiliation(entry, employee, organizationSlug);
  const canSetEmployer = Boolean(onSetEmployer && !muted);
  const shiftEntityOptions = shiftEntityOptionsForOrg(organizationSlug);

  const closeMenu = () => setMenuAnchor(null);

  return (
    <Paper
      elevation={0}
      data-shift-card
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
        overflow: "hidden",
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
          <Typography
            variant="caption"
            fontWeight={700}
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
            {scheduleEndTimeEnabled
              ? `${formatTime12(entry.start_time)} – ${formatTime12(entry.end_time)}`
              : formatTime12(entry.start_time)}
          </Typography>
          {scheduleEndTimeEnabled ? (
            <Typography
              variant="caption"
              sx={{
                display: "block",
                mt: 0.15,
                color: "text.secondary",
                fontSize: "0.68rem",
                fontWeight: 700,
                lineHeight: 1.25,
                whiteSpace: "nowrap",
                overflow: "visible",
                textOverflow: "clip",
              }}
            >
              {hoursLabel}
              {breakSuffix}
            </Typography>
          ) : null}
          {roleText ? (
            <Typography
              variant="caption"
              sx={{
                display: "block",
                mt: 0.15,
                color: cardStyle.accent,
                fontSize: "0.68rem",
                fontWeight: 700,
                lineHeight: 1.25,
                whiteSpace: "nowrap",
                overflow: "visible",
                textOverflow: "clip",
              }}
            >
              {roleText}
            </Typography>
          ) : null}
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
  );
}
