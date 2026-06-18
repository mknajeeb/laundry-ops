import {
  Box,
  Chip,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Typography,
} from "@mui/material";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";
import { fmtLaborValue } from "../../utils/employeeProductivityHelpers";

function formatTime12(raw) {
  if (!raw) return "—";
  const [hStr, mStr] = String(raw).split(":");
  const h = Number(hStr);
  const m = Number(mStr);
  if (Number.isNaN(h) || Number.isNaN(m)) return raw;
  const suffix = h >= 12 ? "PM" : "AM";
  const hour12 = h % 12 || 12;
  return `${hour12}:${String(m).padStart(2, "0")} ${suffix}`;
}

function formatHoursDisplay(entry) {
  if (entry?.shift_open || !entry?.end_time) return "Open";
  return fmtLaborValue(entry.hours, { digits: 2 });
}

function formatCostDisplay(entry) {
  if (entry?.shift_open || entry?.cost == null) return "—";
  return fmtLaborValue(entry.cost, { currency: true });
}

export default function DailyShiftRosterCard({
  entry,
  draft = false,
  onEdit,
  onDelete,
  onRoleChange,
  roleSaving = false,
}) {
  const endLabel = entry?.shift_open || !entry?.end_time ? "Open" : formatTime12(entry.end_time);

  return (
    <Box
      sx={{
        p: 2,
        borderRadius: 2.5,
        bgcolor: draft ? VEEWASH_DASHBOARD.snapshotBg : "#fff",
        border: "1px solid",
        borderColor: draft ? VEEWASH_DASHBOARD.snapshotBorder : VEEWASH_DASHBOARD.primaryBlueBorder,
        boxShadow: VEEWASH_DASHBOARD.cardShadow,
        transition: "border-color 0.15s ease, box-shadow 0.15s ease",
        "&:hover": {
          borderColor: VEEWASH_DASHBOARD.primaryBlue,
          boxShadow: "0 4px 14px rgba(0, 151, 178, 0.12)",
        },
      }}
    >
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1}>
        <Box sx={{ minWidth: 0, flex: 1 }}>
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <Typography variant="h6" fontWeight={800} sx={{ fontSize: "1.05rem", lineHeight: 1.25 }}>
              {entry.employee_name}
            </Typography>
            {draft ? (
              <Chip size="small" label="From Payroll" color="info" variant="outlined" sx={{ height: 22 }} />
            ) : null}
          </Stack>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mt: 1 }} alignItems={{ sm: "center" }}>
            <FormControl size="small" sx={{ minWidth: 130 }} disabled={roleSaving}>
              <InputLabel id={`roster-role-${entry.id || entry.employee_name}`}>Role</InputLabel>
              <Select
                labelId={`roster-role-${entry.id || entry.employee_name}`}
                label="Role"
                value={entry.role || "folder"}
                onChange={(e) => onRoleChange?.(entry, e.target.value)}
              >
                <MenuItem value="folder">Folder</MenuItem>
                <MenuItem value="operator">Operator</MenuItem>
              </Select>
            </FormControl>
            <Chip
              size="small"
              variant="outlined"
              label={`${formatTime12(entry.start_time)} → ${endLabel}`}
              sx={{ height: 28, fontWeight: 600, maxWidth: "100%" }}
            />
          </Stack>
          <Box
            sx={{
              mt: 1.25,
              display: "grid",
              gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
              gap: 1,
            }}
          >
            <Box>
              <Typography variant="caption" color="text.secondary" fontWeight={700} display="block">
                Hours
              </Typography>
              <Typography variant="body1" fontWeight={800}>
                {formatHoursDisplay(entry)}
              </Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary" fontWeight={700} display="block">
                Rate
              </Typography>
              <Typography variant="body1" fontWeight={800}>
                {fmtLaborValue(entry.rate, { currency: true })}
              </Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary" fontWeight={700} display="block">
                Cost
              </Typography>
              <Typography variant="body1" fontWeight={800} sx={{ color: VEEWASH_DASHBOARD.primaryBlueDark }}>
                {formatCostDisplay(entry)}
              </Typography>
            </Box>
          </Box>
          {entry.break_minutes > 0 ? (
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.75 }}>
              Break: {entry.break_minutes} min
            </Typography>
          ) : null}
          {entry.notes ? (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75, fontStyle: "italic" }}>
              {entry.notes}
            </Typography>
          ) : null}
        </Box>
        <Stack direction="row" spacing={0.25} sx={{ flexShrink: 0 }}>
          <IconButton size="small" aria-label="Edit roster entry" onClick={() => onEdit?.(entry)}>
            <EditOutlinedIcon fontSize="small" />
          </IconButton>
          {!draft ? (
            <IconButton size="small" aria-label="Delete roster entry" onClick={() => onDelete?.(entry)}>
              <DeleteOutlineIcon fontSize="small" />
            </IconButton>
          ) : null}
        </Stack>
      </Stack>
    </Box>
  );
}
