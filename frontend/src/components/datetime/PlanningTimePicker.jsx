import { useEffect, useState } from "react";
import {
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Popover,
  Select,
  Stack,
  TextField,
  Typography,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import AccessTimeIcon from "@mui/icons-material/AccessTime";
import CloseIcon from "@mui/icons-material/Close";
import {
  QUICK_TIME_CHIPS,
  PICKER_FIELD_SX,
  formatTime12,
  hmFrom12Parts,
  normalizeTimeHm,
  time12Parts,
} from "./scheduleTimeUi";

const HOURS = [12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];
const MINUTES_QUARTER = [0, 15, 30, 45];
const MINUTES_EXACT = Array.from({ length: 60 }, (_, i) => i);

function TimePickerBody({ value, onChange, onDone, minuteOptions, showQuickChips = true }) {
  const parts = time12Parts(value);
  const [hour12, setHour12] = useState(parts.hour12);
  const [minute, setMinute] = useState(parts.minute);
  const [ampm, setAmpm] = useState(parts.ampm);
  const minutes = minuteOptions || MINUTES_QUARTER;

  useEffect(() => {
    const p = time12Parts(value);
    setHour12(p.hour12);
    setMinute(p.minute);
    setAmpm(p.ampm);
  }, [value]);

  const applyParts = (h, m, ap) => {
    onChange?.(hmFrom12Parts(h, m, ap));
  };

  // Keep Select controlled when value minutes are outside the offered list (e.g. :17 on quarter grid).
  const minuteValue = minutes.includes(minute) ? minute : minutes[0];

  return (
    <Box sx={{ minWidth: 260 }}>
      {showQuickChips ? (
        <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ mb: 1.5 }}>
          {QUICK_TIME_CHIPS.map((c) => (
            <Chip
              key={c.value}
              label={c.label}
              clickable
              color={normalizeTimeHm(value) === c.value ? "primary" : "default"}
              onClick={() => {
                onChange?.(c.value);
                onDone?.();
              }}
              sx={{ minHeight: 36, fontSize: "0.875rem" }}
            />
          ))}
        </Stack>
      ) : null}
      <Stack direction="row" spacing={1} alignItems="center">
        <FormControl size="small" sx={{ minWidth: 72 }}>
          <InputLabel>Hour</InputLabel>
          <Select
            label="Hour"
            value={hour12}
            onChange={(e) => {
              const h = e.target.value;
              setHour12(h);
              applyParts(h, minute, ampm);
            }}
          >
            {HOURS.map((h) => (
              <MenuItem key={h} value={h}>
                {h}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: 72 }}>
          <InputLabel>Min</InputLabel>
          <Select
            label="Min"
            value={minuteValue}
            onChange={(e) => {
              const m = e.target.value;
              setMinute(m);
              applyParts(hour12, m, ampm);
            }}
          >
            {minutes.map((m) => (
              <MenuItem key={m} value={m}>
                {String(m).padStart(2, "0")}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: 88 }}>
          <InputLabel>AM/PM</InputLabel>
          <Select
            label="AM/PM"
            value={ampm}
            onChange={(e) => {
              const ap = e.target.value;
              setAmpm(ap);
              applyParts(hour12, minute, ap);
            }}
          >
            <MenuItem value="AM">AM</MenuItem>
            <MenuItem value="PM">PM</MenuItem>
          </Select>
        </FormControl>
      </Stack>
      <Typography variant="caption" color="text.secondary" sx={{ mt: 1.5, display: "block" }}>
        {value ? formatTime12(value) : "Select a time"}
      </Typography>
    </Box>
  );
}

export default function PlanningTimePicker({
  label = "Time",
  value,
  onChange,
  fullWidth = true,
  size = "small",
  disabled = false,
  compact = false,
  /** When true, offer every minute 0–59 (management planner). Default remains quarter-hours. */
  exactMinutes = false,
}) {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("sm"));
  const [anchor, setAnchor] = useState(null);
  const open = Boolean(anchor);

  const openPicker = (e) => {
    if (disabled) return;
    setAnchor(e.currentTarget);
  };

  const close = () => setAnchor(null);

  const body = (
    <TimePickerBody
      value={value}
      onChange={onChange}
      onDone={close}
      minuteOptions={exactMinutes ? MINUTES_EXACT : MINUTES_QUARTER}
      showQuickChips={!exactMinutes}
    />
  );

  if (compact) {
    return (
      <>
        <Button
          variant="outlined"
          size="small"
          disabled={disabled}
          onClick={openPicker}
          startIcon={<AccessTimeIcon />}
          sx={{ minHeight: 40, borderRadius: 2, textTransform: "none", fontWeight: 600 }}
        >
          {value ? formatTime12(value) : "—"}
        </Button>
        {isMobile ? (
          <Dialog open={open} onClose={close} fullWidth maxWidth="xs">
            <DialogTitle>{label}</DialogTitle>
            <DialogContent>{body}</DialogContent>
            <DialogActions>
              <Button onClick={close}>Done</Button>
            </DialogActions>
          </Dialog>
        ) : (
          <Popover open={open} anchorEl={anchor} onClose={close} slotProps={{ paper: { sx: { p: 2, borderRadius: 3 } } }}>
            {body}
          </Popover>
        )}
      </>
    );
  }

  return (
    <>
      <TextField
        label={label}
        size={size}
        fullWidth={fullWidth}
        disabled={disabled}
        value={value ? formatTime12(value) : ""}
        placeholder="Select time"
        onClick={openPicker}
        InputProps={{
          readOnly: true,
          endAdornment: (
            <IconButton size="small" onClick={openPicker} edge="end" disabled={disabled}>
              <AccessTimeIcon />
            </IconButton>
          ),
        }}
        sx={PICKER_FIELD_SX}
      />
      {isMobile ? (
        <Dialog open={open} onClose={close} fullWidth maxWidth="xs">
          <DialogTitle sx={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            {label}
            <IconButton onClick={close}>
              <CloseIcon />
            </IconButton>
          </DialogTitle>
          <DialogContent>{body}</DialogContent>
          <DialogActions>
            <Button onClick={close}>Done</Button>
          </DialogActions>
        </Dialog>
      ) : (
        <Popover open={open} anchorEl={anchor} onClose={close} slotProps={{ paper: { sx: { p: 2, borderRadius: 3 } } }}>
          {body}
        </Popover>
      )}
    </>
  );
}
