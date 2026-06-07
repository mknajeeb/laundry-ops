import { useMemo, useState } from "react";
import {
  Box,
  Button,
  Chip,
  Drawer,
  IconButton,
  Stack,
  Typography,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import {
  buildRosterBoardData,
  categoryCostsFromForecast,
  computeRosterSuggestions,
  COVERAGE_STATUS,
} from "../../payroll/rosterBoardPlanner";
import { SCHEDULE_THEME } from "../../payroll/scheduleTheme";
import RosterBoardCompactCard from "./RosterBoardCompactCard";
import RosterBoardSummaryPanel from "./RosterBoardSummaryPanel";
import RosterBoardSuggestionsPanel from "./RosterBoardSuggestionsPanel";
import PlanningWeekPicker from "../datetime/PlanningWeekPicker";

export default function RosterBoardView({
  draftEntries,
  settings,
  coverageTargets,
  workers,
  weekStart,
  weekEnd,
  selectedDate,
  onSelectedDateChange,
  workerStatsMap,
  fundingForecast,
  hasUnsaved,
  onAdd,
  onEdit,
  onRemove,
  onDuplicate,
  onAbsent,
  onReplace,
  onSuggestGap,
  onFillGap,
  onWorkerPanel,
}) {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("md"));
  const [boardDay, setBoardDay] = useState(selectedDate);
  const [summaryCollapsed, setSummaryCollapsed] = useState(false);
  const [suggestionsCollapsed, setSuggestionsCollapsed] = useState(false);
  const [workerDrawerOpen, setWorkerDrawerOpen] = useState(false);

  const focusDate = isMobile ? boardDay : selectedDate;

  const boardData = useMemo(
    () =>
      buildRosterBoardData({
        entries: draftEntries,
        settings,
        coverageTargets,
        workers,
        weekStart,
        weekEnd,
        focusDate,
      }),
    [draftEntries, settings, coverageTargets, workers, weekStart, weekEnd, focusDate],
  );

  const categoryCosts = useMemo(() => categoryCostsFromForecast(fundingForecast), [fundingForecast]);

  const weekGapCount = useMemo(() => {
    let n = 0;
    for (const day of boardData.weekDays) {
      n += (boardData.coverageByDay[day.ymd] || []).filter((g) => g.status === "short").length;
    }
    return n;
  }, [boardData]);

  const weekSummary = useMemo(
    () => ({ ...boardData.weekSummary, open_coverage_gaps: weekGapCount }),
    [boardData.weekSummary, weekGapCount],
  );

  const suggestions = useMemo(
    () =>
      computeRosterSuggestions({
        boardData,
        entries: draftEntries,
        workers,
        settings,
        coverageTargets,
        weekStart,
      }),
    [boardData, draftEntries, workers, settings, coverageTargets, weekStart],
  );

  const focusDay = boardData.weekDays.find((d) => d.ymd === focusDate) || boardData.weekDays[0];
  const daySummary = boardData.daySummaries[focusDate];

  const handleSuggestion = (s) => {
    if (s.action === "fill_gap" && s.gap) {
      onFillGap?.(s.work_date, s.gap, s.suggestion);
    } else if (s.action === "edit_entry" && s.entry) {
      onEdit?.(s.entry);
    } else if (s.action === "open_profile" && s.worker_profile_id) {
      onWorkerPanel?.(s.worker_profile_id);
    }
  };

  const renderCoverageBadges = (gaps) => {
    if (!gaps?.length) return null;
    return (
      <Stack spacing={0.5} sx={{ mb: 1 }}>
        {gaps.slice(0, 4).map((g) => {
          const badge = COVERAGE_STATUS[g.status] || COVERAGE_STATUS.covered;
          return (
            <Chip
              key={`${g.role_id}-${g.work_stream_id}`}
              size="small"
              color={badge.color}
              variant={g.status === "covered" ? "outlined" : "filled"}
              label={`${g.role_name}: ${g.required_count}/${g.scheduled_count}`}
              sx={{ height: 22, fontSize: "0.65rem", justifyContent: "flex-start" }}
            />
          );
        })}
      </Stack>
    );
  };

  const renderShiftColumn = (ymd, shift) => {
    const cell = boardData.cells[ymd]?.[shift.id];
    if (!cell) return null;
    return (
      <Box
        key={`${ymd}-${shift.id}`}
        sx={{
          minHeight: 120,
          p: 1,
          borderRadius: 2,
          bgcolor: "rgba(248,250,252,0.9)",
          border: "1px dashed",
          borderColor: "divider",
        }}
      >
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 0.75 }}>
          <Typography variant="caption" fontWeight={800} color="text.secondary">
            {shift.name}
          </Typography>
          <IconButton
            size="small"
            onClick={() => onAdd?.(shift.id, null, null, ymd)}
            sx={{ bgcolor: SCHEDULE_THEME.accentSoft }}
          >
            <AddIcon fontSize="small" />
          </IconButton>
        </Stack>
        {renderCoverageBadges(cell.coverage_gaps)}
        <Stack spacing={0.75}>
          {(cell.entries || []).map((e) => (
            <RosterBoardCompactCard
              key={e.id}
              entry={e}
              weekStats={workerStatsMap[e.worker_profile_id]}
              onEdit={onEdit}
              onRemove={onRemove}
              onDuplicate={onDuplicate}
              onAbsent={onAbsent}
              onReplace={onReplace}
              compact={isMobile}
            />
          ))}
          {!cell.entries?.length ? (
            <Typography variant="caption" color="text.secondary" sx={{ py: 1, textAlign: "center" }}>
              Empty
            </Typography>
          ) : null}
        </Stack>
      </Box>
    );
  };

  const desktopGrid = (
    <Box
      sx={{
        display: "grid",
        gridTemplateColumns: `120px repeat(7, minmax(140px, 1fr))`,
        gap: 1,
        overflowX: "auto",
        pb: 2,
      }}
    >
      <Box />
      {boardData.weekDays.map((day) => (
        <Box
          key={day.ymd}
          sx={{
            textAlign: "center",
            py: 1,
            borderRadius: 2,
            bgcolor: day.ymd === focusDate ? SCHEDULE_THEME.accentSoft : "transparent",
            border: day.ymd === focusDate ? "2px solid" : "none",
            borderColor: "primary.light",
            cursor: "pointer",
          }}
          onClick={() => onSelectedDateChange?.(day.ymd)}
        >
          <Typography variant="caption" fontWeight={700} color="text.secondary">
            {day.shortLabel}
          </Typography>
          <Typography variant="body2" fontWeight={800}>
            {day.label.split(", ").pop()}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {(boardData.daySummaries[day.ymd]?.total_people ?? 0)} workers
          </Typography>
        </Box>
      ))}
      {boardData.shifts.map((shift) => (
        <Box key={`row-${shift.id}`} sx={{ display: "contents" }}>
          <Box
            sx={{
              display: "flex",
              alignItems: "center",
              pr: 1,
              position: "sticky",
              left: 0,
              bgcolor: "background.paper",
              zIndex: 2,
            }}
          >
            <Typography variant="subtitle2" fontWeight={800}>
              {shift.name}
            </Typography>
          </Box>
          {boardData.weekDays.map((day) => (
            <Box key={`${day.ymd}-${shift.id}`}>{renderShiftColumn(day.ymd, shift)}</Box>
          ))}
        </Box>
      ))}
    </Box>
  );

  const mobileDayView = (
    <Stack spacing={2}>
      <Stack direction="row" spacing={0.75} sx={{ overflowX: "auto", pb: 0.5 }}>
        {boardData.weekDays.map((day) => (
          <Chip
            key={day.ymd}
            label={`${day.shortLabel} (${boardData.daySummaries[day.ymd]?.total_people ?? 0})`}
            clickable
            color={boardDay === day.ymd ? "primary" : "default"}
            onClick={() => {
              setBoardDay(day.ymd);
              onSelectedDateChange?.(day.ymd);
            }}
            sx={{ minHeight: 40, fontWeight: 700 }}
          />
        ))}
      </Stack>
      {boardData.shifts.map((shift) => (
        <Box key={shift.id}>
          <Typography variant="subtitle1" fontWeight={800} sx={{ mb: 1 }}>
            {shift.name}
          </Typography>
          {renderShiftColumn(focusDate, shift)}
        </Box>
      ))}
    </Stack>
  );

  return (
    <Box>
      <PlanningWeekPicker
        selectedDate={selectedDate}
        onSelectedDateChange={(d) => {
          onSelectedDateChange?.(d);
          setBoardDay(d);
        }}
        weekStartsOn={settings?.week_starts_on ?? 0}
        showDateJump={false}
      />

      <RosterBoardSummaryPanel
        weekSummary={weekSummary}
        daySummary={daySummary}
        categoryCosts={categoryCosts}
        hasUnsaved={hasUnsaved}
        draftCount={boardData.draft_count}
        publishedCount={boardData.published_count}
        collapsed={summaryCollapsed}
        onToggleCollapse={() => setSummaryCollapsed((v) => !v)}
        focusDayLabel={focusDay ? `${focusDay.label}` : null}
      />

      <Stack direction={{ xs: "column", lg: "row" }} spacing={2} sx={{ mb: 2 }}>
        <Box sx={{ flex: 1 }}>
          <RosterBoardSuggestionsPanel
            suggestions={suggestions}
            onAction={handleSuggestion}
            collapsed={suggestionsCollapsed}
            onToggle={() => setSuggestionsCollapsed((v) => !v)}
          />
        </Box>
        <Button
          variant="outlined"
          endIcon={<ChevronRightIcon />}
          onClick={() => setWorkerDrawerOpen(true)}
          sx={{ alignSelf: { lg: "flex-start" }, minHeight: 44, flexShrink: 0 }}
        >
          Worker hours ({boardData.workerRoster.filter((w) => w.week_stats?.scheduled_hours > 0).length})
        </Button>
      </Stack>

      {isMobile ? mobileDayView : desktopGrid}

      <Drawer
        anchor={isMobile ? "bottom" : "right"}
        open={workerDrawerOpen}
        onClose={() => setWorkerDrawerOpen(false)}
        PaperProps={{
          sx: isMobile
            ? { maxHeight: "85vh", borderRadius: "16px 16px 0 0", px: 2, py: 2 }
            : { width: 360, px: 2, py: 2 },
        }}
      >
        <Typography variant="h6" fontWeight={800} sx={{ mb: 2 }}>
          Worker week summary
        </Typography>
        <Stack spacing={1} sx={{ overflow: "auto", maxHeight: isMobile ? "70vh" : "calc(100vh - 120px)" }}>
          {boardData.workerRoster.map((w) => {
            const st = w.week_stats;
            if (!st) return null;
            const label = st.balance_label || "Balanced";
            const short =
              label === "Overtime Risk" ? "OT Risk" : label === "Heavy" ? "Heavy" : label === "Underused" ? "Underused" : "Safe";
            return (
              <Box
                key={w.worker_profile_id}
                sx={{
                  p: 1.25,
                  borderRadius: 2,
                  border: "1px solid",
                  borderColor: "divider",
                  cursor: "pointer",
                }}
                onClick={() => onWorkerPanel?.(w.user_id)}
              >
                <Stack direction="row" justifyContent="space-between">
                  <Typography fontWeight={700}>{w.worker_name || w.display_name}</Typography>
                  <Chip
                    size="small"
                    color={
                      label === "Overtime Risk" ? "error" : label === "Heavy" ? "warning" : label === "Underused" ? "info" : "success"
                    }
                    label={short}
                  />
                </Stack>
                <Typography variant="caption" color="text.secondary">
                  {st.scheduled_days} days · {st.scheduled_hours.toFixed(1)}h
                  {w.max_hours ? ` · max ${w.max_hours}h` : ""} · {st.hours_remaining_before_overtime.toFixed(1)}h before OT
                </Typography>
                <Typography variant="caption" display="block">
                  Est. ${Number(w.estimated_week_cost || 0).toFixed(0)}
                </Typography>
              </Box>
            );
          })}
        </Stack>
      </Drawer>
    </Box>
  );
}
