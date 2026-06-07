import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Drawer,
  Stack,
  Typography,
} from "@mui/material";
import PersonSearchIcon from "@mui/icons-material/PersonSearch";
import { formatTime12 } from "../../payroll/scheduleTheme";

export default function ReplacementFindPanel({
  open,
  onClose,
  originalEntry,
  suggestions,
  loading,
  onAssign,
  onMarkAbsentFirst,
}) {
  const entry = originalEntry;
  if (!open) return null;

  return (
    <Drawer
      anchor="bottom"
      open={open}
      onClose={onClose}
      PaperProps={{ sx: { borderRadius: "20px 20px 0 0", maxHeight: "90vh", px: 2, py: 2 } }}
    >
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
        <PersonSearchIcon color="primary" />
        <Typography variant="h6" fontWeight={800}>
          Find replacement
        </Typography>
      </Stack>

      {entry ? (
        <Card variant="outlined" sx={{ mb: 2, borderRadius: 2, bgcolor: "action.hover" }}>
          <CardContent sx={{ py: 1.5 }}>
            <Typography variant="overline" color="text.secondary">
              Original shift
            </Typography>
            <Typography variant="subtitle1" fontWeight={800}>
              {entry.worker_name}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {String(entry.work_date).slice(0, 10)} · {entry.shift_name}
            </Typography>
            <Typography variant="body2">
              {entry.work_stream_name} · {entry.role_name}
            </Typography>
            <Typography variant="body2">
              {formatTime12(entry.start_time)}–{formatTime12(entry.end_time)} · {Number(entry.scheduled_hours || 0).toFixed(1)}h
            </Typography>
            {!["sick", "absent", "no_show"].includes(entry.status) && onMarkAbsentFirst ? (
              <Button size="small" sx={{ mt: 1 }} onClick={() => onMarkAbsentFirst(entry)}>
                Mark sick/absent first
              </Button>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      {loading ? (
        <Box sx={{ py: 4, textAlign: "center" }}>
          <CircularProgress size={32} />
        </Box>
      ) : (
        <Stack spacing={1.5} sx={{ maxHeight: "55vh", overflow: "auto", pb: 2 }}>
          {(suggestions || []).map((s, idx) => (
            <Card key={s.worker_profile_id} variant="outlined" sx={{ borderRadius: 2 }}>
              <CardContent sx={{ py: 1.5 }}>
                <Stack direction="row" justifyContent="space-between" alignItems="center">
                  <Typography fontWeight={800}>
                    {idx + 1}. {s.worker_name}
                  </Typography>
                  <Chip
                    size="small"
                    color={
                      s.recommendation === "Best"
                        ? "success"
                        : s.recommendation === "Avoid" || String(s.recommendation || "").includes("Avoid")
                          ? "error"
                          : "default"
                    }
                    label={s.recommendation || "Good"}
                  />
                </Stack>
                {(s.reasons || []).map((r) => (
                  <Typography key={r} variant="caption" display="block" color="text.secondary">
                    {r}
                  </Typography>
                ))}
                <Button
                  fullWidth
                  variant="contained"
                  sx={{ mt: 1.5, minHeight: 44 }}
                  onClick={() => onAssign?.(s)}
                >
                  Assign replacement
                </Button>
              </CardContent>
            </Card>
          ))}
          {!loading && !suggestions?.length ? (
            <Alert severity="warning">No qualified replacements found. Check availability, skills, and overtime.</Alert>
          ) : null}
        </Stack>
      )}
    </Drawer>
  );
}
