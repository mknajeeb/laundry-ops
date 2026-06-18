import {
  Box,
  Chip,
  IconButton,
  Stack,
  Typography,
} from "@mui/material";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";
import { fmtLaborValue } from "../../utils/employeeProductivityHelpers";

function formatRole(role) {
  if (role === "operator") return "Operator";
  if (role === "folder") return "Folder";
  return role || "—";
}

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

export default function DailyShiftRosterCard({ entry, onEdit, onDelete }) {
  return (
    <Box
      sx={{
        p: 2,
        borderRadius: 2.5,
        bgcolor: "#fff",
        border: "1px solid",
        borderColor: VEEWASH_DASHBOARD.primaryBlueBorder,
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
          <Typography variant="h6" fontWeight={800} sx={{ fontSize: "1.05rem", lineHeight: 1.25 }}>
            {entry.employee_name}
          </Typography>
          <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap sx={{ mt: 0.75 }}>
            <Chip
              size="small"
              label={formatRole(entry.role)}
              sx={{
                height: 24,
                fontWeight: 700,
                bgcolor: entry.role === "operator" ? VEEWASH_DASHBOARD.hdBg : VEEWASH_DASHBOARD.wfBg,
                color: entry.role === "operator" ? VEEWASH_DASHBOARD.hdTeal : VEEWASH_DASHBOARD.wfCharcoal,
                border: "1px solid",
                borderColor: entry.role === "operator" ? VEEWASH_DASHBOARD.hdBorder : VEEWASH_DASHBOARD.wfBorder,
              }}
            />
            <Chip
              size="small"
              variant="outlined"
              label={`${formatTime12(entry.start_time)} – ${formatTime12(entry.end_time)}`}
              sx={{ height: 24, fontWeight: 600 }}
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
                {fmtLaborValue(entry.hours, { digits: 2 })}
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
                {fmtLaborValue(entry.cost, { currency: true })}
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
          <IconButton size="small" aria-label="Delete roster entry" onClick={() => onDelete?.(entry)}>
            <DeleteOutlineIcon fontSize="small" />
          </IconButton>
        </Stack>
      </Stack>
    </Box>
  );
}
