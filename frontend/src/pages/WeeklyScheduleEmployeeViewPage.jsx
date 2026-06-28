import { useCallback, useEffect, useMemo, useState } from "react";
import { Link as RouterLink, useParams, useSearchParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import PrintIcon from "@mui/icons-material/Print";
import { getWeeklySchedule } from "../api";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";
import WeeklyScheduleShiftCard from "../components/weeklySchedule/WeeklyScheduleShiftCard";
import {
  DAY_LABELS,
  formatDayDate,
  normalizeWeekStart,
} from "../components/weeklySchedule/weeklyScheduleDates";
import {
  employeeScheduleRoles,
  formatEmployeeWeeklySummary,
  roleLabels,
} from "../components/weeklySchedule/weeklyScheduleRoles";
import "../components/weeklySchedule/weeklySchedulePrint.css";

export default function WeeklyScheduleEmployeeViewPage() {
  const { userId } = useParams();
  const [searchParams] = useSearchParams();
  const weekStartParam = searchParams.get("week_start");
  const [weekStart, setWeekStart] = useState(() =>
    normalizeWeekStart(weekStartParam || new Date().toISOString().slice(0, 10)),
  );
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async (week) => {
    setLoading(true);
    setError("");
    try {
      const res = await getWeeklySchedule({ week_start: week });
      setData(res.data);
      setWeekStart(res.data?.week_start || week);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to load schedule");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(weekStart);
  }, [userId]); // eslint-disable-line react-hooks/exhaustive-deps

  const employee = useMemo(
    () => (data?.employees || []).find((row) => String(row.user_id) === String(userId)),
    [data?.employees, userId],
  );

  const entriesByCell = useMemo(() => {
    const map = {};
    for (const entry of data?.entries || []) {
      if (String(entry.user_id) !== String(userId)) continue;
      const key = Number(entry.day_of_week);
      if (!map[key]) map[key] = [];
      map[key].push(entry);
    }
    return map;
  }, [data?.entries, userId]);

  const scheduleRoles = employeeScheduleRoles(employee?.user_id, data?.entries);
  const display = data?.display || {};
  const showRoleLabels = display.show_role_labels !== false;
  const showBreakMinutes = display.show_break_minutes !== false;
  const scheduleEndTimeEnabled = display.schedule_end_time_enabled !== false;
  const daysOnly = !scheduleEndTimeEnabled;

  const handlePrint = () => {
    window.print();
  };

  if (loading && !data) {
    return (
      <Stack alignItems="center" justifyContent="center" minHeight="50vh">
        <CircularProgress size={32} />
      </Stack>
    );
  }

  return (
    <Box
      className="weekly-schedule-print-root"
      sx={{
        p: { xs: 2, md: 3 },
        bgcolor: VEEWASH_DASHBOARD.pageBackground,
        minHeight: "100%",
      }}
    >
      <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between" sx={{ mb: 2 }} className="no-print">
        <Button
          component={RouterLink}
          to={`/performance/weekly-schedule?week_start=${weekStart}`}
          startIcon={<ArrowBackIcon />}
          variant="text"
          sx={{ fontWeight: 700 }}
        >
          Back to Weekly Schedule
        </Button>
        <Button variant="outlined" startIcon={<PrintIcon />} onClick={handlePrint} sx={{ fontWeight: 700 }}>
          Print
        </Button>
      </Stack>

      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} className="no-print">
          {error}
        </Alert>
      ) : null}

      {!employee && !loading ? (
        <Alert severity="warning">Employee not found in this week&apos;s schedule.</Alert>
      ) : null}

      {employee ? (
        <Paper
          elevation={0}
          className="weekly-schedule-print-area"
          sx={{
            borderRadius: 3,
            overflow: "hidden",
            border: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
            boxShadow: "0 8px 30px rgba(15, 23, 42, 0.06)",
          }}
        >
          <Box
            sx={{
              px: { xs: 2, md: 3 },
              py: 2.5,
              background: `linear-gradient(135deg, ${VEEWASH_DASHBOARD.primaryBlue} 0%, ${VEEWASH_DASHBOARD.tealDark} 100%)`,
              color: "#fff",
            }}
          >
            <Typography variant="h5" fontWeight={800} sx={{ letterSpacing: "-0.02em" }}>
              {employee.display_name}
            </Typography>
            {scheduleRoles.length ? (
              <Typography variant="body2" sx={{ mt: 0.75, fontWeight: 700 }}>
                Roles: {roleLabels(scheduleRoles)}
              </Typography>
            ) : null}
            <Typography variant="body2" sx={{ mt: 0.5, fontWeight: 600, opacity: 0.95 }}>
              {formatEmployeeWeeklySummary(employee, { daysOnly })}
            </Typography>
          </Box>

          <Box sx={{ p: { xs: 1.5, md: 2.5 }, bgcolor: "#fff" }}>
            <Box
              sx={{
                display: "grid",
                gridTemplateColumns: { xs: "1fr", md: "repeat(7, minmax(0, 1fr))" },
                gap: { xs: 1, md: 0 },
                border: { md: "1px solid #e2e8f0" },
                borderRadius: { md: 2.5 },
                overflow: "hidden",
              }}
            >
              {DAY_LABELS.map((dayLabel, dow) => {
                const cellEntries = entriesByCell[dow] || [];
                return (
                  <Box
                    key={dayLabel}
                    sx={{
                      px: 1.15,
                      py: 1,
                      borderBottom: { xs: "1px solid #e2e8f0", md: "none" },
                      borderLeft: { md: dow === 0 ? "none" : "1px solid #e2e8f0" },
                      bgcolor: cellEntries.length ? "#f8fafc" : "#fff",
                      minHeight: { md: 120 },
                    }}
                  >
                    <Typography
                      variant="overline"
                      sx={{
                        display: "block",
                        fontWeight: 800,
                        letterSpacing: "0.08em",
                        color: VEEWASH_DASHBOARD.primaryBlueDark,
                      }}
                    >
                      {dayLabel}
                    </Typography>
                    <Typography
                      variant="body2"
                      sx={{
                        display: "block",
                        fontWeight: 700,
                        color: "text.secondary",
                        fontSize: "0.8125rem",
                        mb: 0.75,
                      }}
                    >
                      {formatDayDate(weekStart, dow)}
                    </Typography>
                    {cellEntries.length ? (
                      cellEntries.map((entry) => (
                        <WeeklyScheduleShiftCard
                          key={entry.id}
                          entry={entry}
                          muted
                          showRoleLabels={showRoleLabels}
                          showBreakMinutes={showBreakMinutes}
                          scheduleEndTimeEnabled={scheduleEndTimeEnabled}
                        />
                      ))
                    ) : (
                      <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 600 }}>
                        Off
                      </Typography>
                    )}
                  </Box>
                );
              })}
            </Box>
          </Box>
        </Paper>
      ) : null}
    </Box>
  );
}
