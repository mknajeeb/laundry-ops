import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  IconButton,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import {
  createWeeklyScheduleEntry,
  deleteWeeklyScheduleEntry,
  duplicateWeeklyScheduleEntry,
  getWeeklySchedule,
  moveWeeklyScheduleEntry,
  updateWeeklyScheduleEntry,
} from "../api";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";
import WeeklyScheduleEntryDialog from "../components/weeklySchedule/WeeklyScheduleEntryDialog";
import WeeklyScheduleShiftCard from "../components/weeklySchedule/WeeklyScheduleShiftCard";

const DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function normalizeWeekStart(isoDate) {
  const d = new Date(`${isoDate}T12:00:00`);
  const dow = d.getDay();
  d.setDate(d.getDate() - dow);
  return d.toISOString().slice(0, 10);
}

function shiftWeek(isoDate, deltaWeeks) {
  const d = new Date(`${isoDate}T12:00:00`);
  d.setDate(d.getDate() + deltaWeeks * 7);
  return normalizeWeekStart(d.toISOString().slice(0, 10));
}

function formatWeekRange(weekStart) {
  const start = new Date(`${weekStart}T12:00:00`);
  const end = new Date(start);
  end.setDate(end.getDate() + 6);
  const fmt = (dt) =>
    dt.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  return `${fmt(start)} – ${fmt(end)}`;
}

function formatCurrency(value) {
  const n = Number(value || 0);
  return n.toLocaleString(undefined, { style: "currency", currency: "USD" });
}

function daySummary(day) {
  const people = Number(day?.employee_count || 0);
  const hours = Number(day?.total_hours || 0);
  const ops = Number(day?.operator_count || 0);
  const folders = Number(day?.folder_count || 0);
  return `${people} people | ${hours.toFixed(0)} hrs | ${ops} operators / ${folders} folders`;
}

function employeeSummary(employee) {
  const days = Number(employee?.scheduled_days || 0);
  const hours = Number(employee?.total_hours || 0);
  const cost = formatCurrency(employee?.estimated_cost || 0);
  return `${days} days | ${hours.toFixed(0)} hrs | ${cost} est. cost`;
}

export default function WeeklySchedulePage() {
  const [weekStart, setWeekStart] = useState(() => normalizeWeekStart(new Date().toISOString().slice(0, 10)));
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingEntry, setEditingEntry] = useState(null);
  const [dialogDefaults, setDialogDefaults] = useState({ userId: null, day: 0 });
  const [draggingId, setDraggingId] = useState(null);
  const [dropTarget, setDropTarget] = useState(null);

  const load = useCallback(async (week) => {
    setLoading(true);
    setError("");
    try {
      const res = await getWeeklySchedule({ week_start: week });
      setData(res.data);
      setWeekStart(res.data?.week_start || week);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to load weekly schedule");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(weekStart);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const entriesByCell = useMemo(() => {
    const map = {};
    for (const entry of data?.entries || []) {
      const key = `${entry.user_id}:${entry.day_of_week}`;
      if (!map[key]) map[key] = [];
      map[key].push(entry);
    }
    return map;
  }, [data?.entries]);

  const dayTotals = data?.totals?.day_totals || [];

  const openCreate = (userId, day) => {
    setEditingEntry(null);
    setDialogDefaults({ userId, day });
    setDialogOpen(true);
  };

  const openEdit = (entry) => {
    setEditingEntry(entry);
    setDialogDefaults({ userId: entry.user_id, day: entry.day_of_week });
    setDialogOpen(true);
  };

  const handleSave = async (form) => {
    setSaving(true);
    setError("");
    try {
      if (editingEntry?.id) {
        const res = await updateWeeklyScheduleEntry(editingEntry.id, form);
        setData(res.data);
      } else {
        const res = await createWeeklyScheduleEntry({ week_start: weekStart, ...form });
        setData(res.data);
      }
      setDialogOpen(false);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to save shift");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (entry) => {
    if (!window.confirm("Delete this shift?")) return;
    setError("");
    try {
      const res = await deleteWeeklyScheduleEntry(entry.id);
      setData(res.data);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to delete shift");
    }
  };

  const handleDuplicate = async (entry) => {
    setError("");
    try {
      const res = await duplicateWeeklyScheduleEntry(entry.id, {
        day_of_week: entry.day_of_week,
        user_id: entry.user_id,
      });
      setData(res.data);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to duplicate shift");
    }
  };

  const handleDrop = async (userId, dayOfWeek, entryId) => {
    if (!entryId) return;
    setError("");
    try {
      const res = await moveWeeklyScheduleEntry(entryId, { user_id: userId, day_of_week: dayOfWeek });
      setData(res.data);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to move shift");
    } finally {
      setDraggingId(null);
      setDropTarget(null);
    }
  };

  const changeWeek = (delta) => {
    const next = shiftWeek(weekStart, delta);
    setWeekStart(next);
    load(next);
  };

  return (
    <Box sx={{ p: { xs: 1.5, md: 2.5 }, bgcolor: VEEWASH_DASHBOARD.pageBackground, minHeight: "100%" }}>
      <Paper
        elevation={0}
        sx={{
          borderRadius: 2.5,
          overflow: "hidden",
          border: `1px solid ${VEEWASH_DASHBOARD.primaryBlueBorder}`,
          boxShadow: VEEWASH_DASHBOARD.cardShadow,
        }}
      >
        <Box
          sx={{
            px: 2,
            py: 1.5,
            bgcolor: VEEWASH_DASHBOARD.workloadHeaderBg,
            color: "#fff",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 1,
            flexWrap: "wrap",
          }}
        >
          <Box>
            <Typography variant="h6" fontWeight={700}>
              Weekly Schedule
            </Typography>
            <Typography variant="body2" sx={{ opacity: 0.9 }}>
              Planned labor grid — drag shifts between days and employees
            </Typography>
          </Box>
          <Stack direction="row" spacing={0.5} alignItems="center">
            <IconButton size="small" onClick={() => changeWeek(-1)} sx={{ color: "#fff" }}>
              <ChevronLeftIcon />
            </IconButton>
            <Typography variant="subtitle2" sx={{ minWidth: 220, textAlign: "center" }}>
              {formatWeekRange(weekStart)}
            </Typography>
            <IconButton size="small" onClick={() => changeWeek(1)} sx={{ color: "#fff" }}>
              <ChevronRightIcon />
            </IconButton>
          </Stack>
        </Box>

        <Box sx={{ p: 2 }}>
          {error ? (
            <Alert severity="error" sx={{ mb: 2 }}>
              {error}
            </Alert>
          ) : null}

          {loading ? (
            <Stack alignItems="center" py={6}>
              <CircularProgress size={32} />
            </Stack>
          ) : (
            <Box sx={{ overflowX: "auto" }}>
              <Box
                sx={{
                  display: "grid",
                  gridTemplateColumns: `220px repeat(7, minmax(140px, 1fr))`,
                  minWidth: 1200,
                  gap: 0,
                  border: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
                  borderRadius: 2,
                  overflow: "hidden",
                }}
              >
                <Box sx={{ p: 1.25, bgcolor: VEEWASH_DASHBOARD.snapshotBg, borderBottom: "1px solid #e2e8f0" }}>
                  <Typography variant="caption" fontWeight={700} color="text.secondary">
                    Employee
                  </Typography>
                </Box>
                {DAY_LABELS.map((label, dow) => (
                  <Box
                    key={label}
                    sx={{
                      p: 1.25,
                      bgcolor: VEEWASH_DASHBOARD.snapshotBg,
                      borderBottom: "1px solid #e2e8f0",
                      borderLeft: "1px solid #e2e8f0",
                    }}
                  >
                    <Typography variant="caption" fontWeight={700}>
                      {label}
                    </Typography>
                    <Typography variant="caption" display="block" color="text.secondary" sx={{ mt: 0.25 }}>
                      {daySummary(dayTotals[dow])}
                    </Typography>
                  </Box>
                ))}

                {(data?.employees || []).map((employee) => (
                  <Box key={employee.user_id} sx={{ display: "contents" }}>
                    <Box
                      sx={{
                        p: 1.25,
                        borderBottom: "1px solid #e2e8f0",
                        bgcolor: "#fff",
                        position: "sticky",
                        left: 0,
                        zIndex: 1,
                      }}
                    >
                      <Typography variant="body2" fontWeight={700} noWrap>
                        {employee.display_name}
                      </Typography>
                      <Typography variant="caption" color="text.secondary" display="block">
                        {employeeSummary(employee)}
                      </Typography>
                    </Box>
                    {DAY_LABELS.map((_, dow) => {
                      const cellKey = `${employee.user_id}:${dow}`;
                      const cellEntries = entriesByCell[cellKey] || [];
                      const isDropTarget = dropTarget === cellKey;
                      return (
                        <Box
                          key={cellKey}
                          onDragOver={(e) => {
                            e.preventDefault();
                            setDropTarget(cellKey);
                          }}
                          onDragLeave={() => {
                            if (dropTarget === cellKey) setDropTarget(null);
                          }}
                          onDrop={(e) => {
                            e.preventDefault();
                            const entryId = e.dataTransfer.getData("text/plain");
                            handleDrop(employee.user_id, dow, entryId);
                          }}
                          sx={{
                            p: 0.75,
                            minHeight: 88,
                            borderBottom: "1px solid #e2e8f0",
                            borderLeft: "1px solid #e2e8f0",
                            bgcolor: isDropTarget ? VEEWASH_DASHBOARD.primaryBlueLight : "#fff",
                            transition: "background-color 0.12s ease",
                          }}
                        >
                          {cellEntries.map((entry) => (
                            <WeeklyScheduleShiftCard
                              key={entry.id}
                              entry={entry}
                              dragging={draggingId === entry.id}
                              onEdit={openEdit}
                              onDelete={handleDelete}
                              onDuplicate={handleDuplicate}
                              onDragStart={(e) => setDraggingId(e.id)}
                              onDragEnd={() => setDraggingId(null)}
                            />
                          ))}
                          <Button
                            size="small"
                            startIcon={<AddIcon sx={{ fontSize: 14 }} />}
                            onClick={() => openCreate(employee.user_id, dow)}
                            sx={{ mt: 0.25, fontSize: "0.7rem", minWidth: 0, px: 0.75 }}
                          >
                            Add
                          </Button>
                        </Box>
                      );
                    })}
                  </Box>
                ))}
              </Box>
            </Box>
          )}
        </Box>
      </Paper>

      <WeeklyScheduleEntryDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onSave={handleSave}
        saving={saving}
        entry={editingEntry}
        defaultUserId={dialogDefaults.userId}
        defaultDay={dialogDefaults.day}
      />
    </Box>
  );
}
