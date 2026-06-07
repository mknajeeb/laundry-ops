import { useMemo, useState } from "react";
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Popover,
  Stack,
  TextField,
  Typography,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import CalendarMonthOutlinedIcon from "@mui/icons-material/CalendarMonthOutlined";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import CloseIcon from "@mui/icons-material/Close";
import TodayIcon from "@mui/icons-material/Today";
import { addDaysYmd, businessTodayYmd, formatDateShortLabel } from "../../utils/businessTime";
import { PICKER_FIELD_SX } from "./scheduleTimeUi";

const WEEK_HEADERS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];

function parseYmd(ymd) {
  const [y, m, d] = (ymd || "").split("-").map((x) => parseInt(x, 10));
  return { y: y || 2000, m: (m || 1) - 1, d: d || 1 };
}

function ymdFromParts(y, m, d) {
  return `${y}-${String(m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

function CalendarBody({ value, onSelect, viewY, viewM }) {
  const first = new Date(viewY, viewM, 1);
  const startPad = first.getDay();
  const daysInMonth = new Date(viewY, viewM + 1, 0).getDate();
  const cells = [];
  for (let i = 0; i < startPad; i += 1) cells.push(null);
  for (let d = 1; d <= daysInMonth; d += 1) {
    cells.push(ymdFromParts(viewY, viewM, d));
  }
  while (cells.length % 7 !== 0) cells.push(null);

  const today = businessTodayYmd();

  return (
    <Box
      sx={{
        display: "grid",
        gridTemplateColumns: "repeat(7, 1fr)",
        gap: 0.5,
        minWidth: 280,
      }}
    >
      {WEEK_HEADERS.map((h) => (
        <Typography key={h} variant="caption" color="text.secondary" align="center" fontWeight={700} sx={{ py: 0.5 }}>
          {h}
        </Typography>
      ))}
      {cells.map((ymd, idx) => {
        if (!ymd) return <Box key={`e-${idx}`} />;
        const selected = ymd === value;
        const isToday = ymd === today;
        return (
          <Button
            key={ymd}
            onClick={() => onSelect(ymd)}
            variant={selected ? "contained" : "text"}
            color={selected ? "primary" : "inherit"}
            sx={{
              minWidth: 0,
              minHeight: 40,
              p: 0,
              borderRadius: 2,
              fontWeight: selected || isToday ? 700 : 500,
              border: isToday && !selected ? "2px solid" : "none",
              borderColor: "primary.light",
            }}
          >
            {parseInt(ymd.slice(8), 10)}
          </Button>
        );
      })}
    </Box>
  );
}

export default function PlanningDatePicker({
  label = "Date",
  value,
  onChange,
  allowClear = false,
  fullWidth = true,
  size = "small",
  disabled = false,
  showNavShortcuts = true,
}) {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("sm"));
  const [anchor, setAnchor] = useState(null);
  const open = Boolean(anchor);
  const { y: vy, m: vm } = parseYmd(value || businessTodayYmd());
  const [viewY, setViewY] = useState(vy);
  const [viewM, setViewM] = useState(vm);

  const monthLabel = useMemo(
    () => new Date(viewY, viewM, 1).toLocaleDateString("en-US", { month: "long", year: "numeric" }),
    [viewY, viewM],
  );

  const openPicker = (e) => {
    if (disabled) return;
    const p = parseYmd(value || businessTodayYmd());
    setViewY(p.y);
    setViewM(p.m);
    setAnchor(e.currentTarget);
  };

  const close = () => setAnchor(null);

  const pick = (ymd) => {
    onChange?.(ymd);
    close();
  };

  const pickerContent = (
    <Box sx={{ p: isMobile ? 1 : 0.5 }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
        <IconButton
          size="small"
          onClick={() => {
            const d = new Date(viewY, viewM - 1, 1);
            setViewY(d.getFullYear());
            setViewM(d.getMonth());
          }}
        >
          <ChevronLeftIcon />
        </IconButton>
        <Typography variant="subtitle2" fontWeight={800}>
          {monthLabel}
        </Typography>
        <IconButton
          size="small"
          onClick={() => {
            const d = new Date(viewY, viewM + 1, 1);
            setViewY(d.getFullYear());
            setViewM(d.getMonth());
          }}
        >
          <ChevronRightIcon />
        </IconButton>
      </Stack>
      <CalendarBody value={value} onSelect={pick} viewY={viewY} viewM={viewM} />
      {showNavShortcuts ? (
        <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ mt: 1.5 }}>
          <Button size="small" startIcon={<TodayIcon />} onClick={() => pick(businessTodayYmd())}>
            Today
          </Button>
          {value ? (
            <>
              <Button size="small" onClick={() => pick(addDaysYmd(value, -1))}>
                Prev day
              </Button>
              <Button size="small" onClick={() => pick(addDaysYmd(value, 1))}>
                Next day
              </Button>
            </>
          ) : null}
          {allowClear && value ? (
            <Button size="small" color="inherit" onClick={() => pick("")}>
              Clear
            </Button>
          ) : null}
        </Stack>
      ) : null}
    </Box>
  );

  return (
    <>
      <TextField
        label={label}
        size={size}
        fullWidth={fullWidth}
        disabled={disabled}
        value={value ? formatDateShortLabel(value) : ""}
        placeholder="Select date"
        onClick={openPicker}
        InputProps={{
          readOnly: true,
          endAdornment: (
            <IconButton size="small" onClick={openPicker} edge="end" disabled={disabled}>
              <CalendarMonthOutlinedIcon />
            </IconButton>
          ),
        }}
        sx={PICKER_FIELD_SX}
      />
      {isMobile ? (
        <Dialog open={open} onClose={close} fullWidth maxWidth="xs">
          <DialogTitle sx={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            {label}
            <IconButton onClick={close}>
              <CloseIcon />
            </IconButton>
          </DialogTitle>
          <DialogContent>{pickerContent}</DialogContent>
          <DialogActions>
            <Button onClick={close}>Cancel</Button>
          </DialogActions>
        </Dialog>
      ) : (
        <Popover
          open={open}
          anchorEl={anchor}
          onClose={close}
          anchorOrigin={{ vertical: "bottom", horizontal: "left" }}
          transformOrigin={{ vertical: "top", horizontal: "left" }}
          slotProps={{ paper: { sx: { p: 2, borderRadius: 3, minWidth: 320 } } }}
        >
          {pickerContent}
        </Popover>
      )}
    </>
  );
}
