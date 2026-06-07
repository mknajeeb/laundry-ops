import { Box, Button, IconButton, Stack, Typography } from "@mui/material";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import TodayIcon from "@mui/icons-material/Today";
import {
  addDaysYmd,
  businessTodayYmd,
  formatWeekRangeLabel,
  weekEndFromStart,
  weekStartFromDate,
} from "../../utils/businessTime";
import PlanningDatePicker from "./PlanningDatePicker";

/**
 * Week navigation aligned to payroll calendar week_starts_on (0=Monday … 6=Sunday).
 */
export default function PlanningWeekPicker({
  selectedDate,
  onSelectedDateChange,
  weekStartsOn = 0,
  showDateJump = true,
}) {
  const weekStart = weekStartFromDate(selectedDate, weekStartsOn);
  const weekEnd = weekEndFromStart(weekStart);
  const label = formatWeekRangeLabel(weekStart, weekEnd);

  const goWeek = (delta) => {
    onSelectedDateChange?.(addDaysYmd(selectedDate, delta * 7));
  };

  const goThisWeek = () => {
    onSelectedDateChange?.(weekStartFromDate(businessTodayYmd(), weekStartsOn));
  };

  return (
    <Stack spacing={1} sx={{ mb: 0.5 }}>
      <Stack direction="row" alignItems="center" spacing={0.5} flexWrap="wrap" useFlexGap>
        <IconButton aria-label="Previous week" onClick={() => goWeek(-1)} sx={{ p: 1.25 }}>
          <ChevronLeftIcon />
        </IconButton>
        <Box
          sx={{
            flex: "1 1 200px",
            px: 1.5,
            py: 1,
            borderRadius: 2,
            bgcolor: "rgba(99, 102, 241, 0.08)",
            border: "1px solid rgba(99, 102, 241, 0.15)",
            textAlign: "center",
          }}
        >
          <Typography variant="caption" color="text.secondary" display="block" fontWeight={600}>
            Work week
          </Typography>
          <Typography variant="subtitle1" fontWeight={800}>
            {label}
          </Typography>
        </Box>
        <IconButton aria-label="Next week" onClick={() => goWeek(1)} sx={{ p: 1.25 }}>
          <ChevronRightIcon />
        </IconButton>
        <Button size="small" startIcon={<TodayIcon />} onClick={goThisWeek} sx={{ minHeight: 40 }}>
          This week
        </Button>
      </Stack>
      {showDateJump ? (
        <PlanningDatePicker
          label="Jump to date in week"
          value={selectedDate}
          onChange={onSelectedDateChange}
          showNavShortcuts={false}
        />
      ) : null}
    </Stack>
  );
}
