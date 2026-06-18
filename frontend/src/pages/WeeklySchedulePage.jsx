import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  FormControlLabel,
  IconButton,
  Paper,
  Stack,
  Switch,
  Tooltip,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import AttachMoneyOutlinedIcon from "@mui/icons-material/AttachMoneyOutlined";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import PersonOffOutlinedIcon from "@mui/icons-material/PersonOffOutlined";
import VisibilityOffOutlinedIcon from "@mui/icons-material/VisibilityOffOutlined";
import {
  createWeeklyScheduleEntry,
  deleteWeeklyScheduleEntry,
  duplicateWeeklyScheduleEntry,
  getWeeklySchedule,
  moveWeeklyScheduleEntry,
  setWeeklyScheduleExclusion,
  updateWeeklyScheduleEntry,
  updateWeeklyScheduleDisplaySettings,
} from "../api";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";
import WeeklyScheduleEntryDialog from "../components/weeklySchedule/WeeklyScheduleEntryDialog";
import WeeklyScheduleShiftCard from "../components/weeklySchedule/WeeklyScheduleShiftCard";
import { ROLE_STYLES } from "../components/weeklySchedule/weeklyScheduleRoles";

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
  return { people, hours, sort: Number(day?.sort_count || 0), wash: Number(day?.wash_count || 0), fold: Number(day?.fold_count || 0) };
}

function employeeSummary(employee, { showCost, showRates }) {
  const days = Number(employee?.scheduled_days || 0);
  const hours = Number(employee?.total_hours || 0);
  const parts = [`${days} days`, `${hours.toFixed(1)} hrs`];
  if (showRates && employee?.default_hourly_rate) {
    parts.push(`${formatCurrency(employee.default_hourly_rate)}/hr`);
  }
  if (showCost) {
    parts.push(`${formatCurrency(employee?.estimated_cost || 0)} est.`);
  }
  return parts.join(" · ");
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
  const [showExcluded, setShowExcluded] = useState(false);
  const [showCost, setShowCost] = useState(false);
  const [costSaving, setCostSaving] = useState(false);
  const [excludeSavingUserId, setExcludeSavingUserId] = useState(null);

  const display = data?.display || {};
  const canEdit = display.can_edit_schedule !== false;
  const canManageExclusions = display.can_manage_exclusions !== false;
  const showRoleLabels = display.show_role_labels !== false;
  const showBreakMinutes = display.show_break_minutes !== false;
  const showEmployeeRates = display.show_employee_rates !== false;
  const costAllowed = display.show_estimated_cost !== false;
  const canConfigureSharing = display.can_configure_sharing !== false;

  useEffect(() => {
    if (data?.display) {
      setShowCost(data.display.show_estimated_cost !== false);
    }
  }, [data?.display?.show_estimated_cost]);

  const handleCostToggle = async () => {
    const next = !showCost;
    setShowCost(next);
    if (!canConfigureSharing) return;
    setCostSaving(true);
    try {
      await updateWeeklyScheduleDisplaySettings({ show_estimated_cost_default: next });
    } catch {
      setShowCost(!next);
    } finally {
      setCostSaving(false);
    }
  };

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

  const visibleEmployees = useMemo(() => {
    const rows = data?.employees || [];
    if (showExcluded) return rows;
    return rows.filter((e) => !e.excluded);
  }, [data?.employees, showExcluded]);

  const excludedCount = useMemo(
    () => (data?.employees || []).filter((e) => e.excluded).length,
    [data?.employees],
  );

  const handleExcludeToggle = async (employee, excluded) => {
    setExcludeSavingUserId(employee.user_id);
    setError("");
    try {
      const res = await setWeeklyScheduleExclusion({
        week_start: weekStart,
        user_id: employee.user_id,
        excluded,
      });
      setData(res.data);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to update exclusion");
    } finally {
      setExcludeSavingUserId(null);
    }
  };

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
          borderRadius: 3,
          overflow: "hidden",
          border: `1px solid ${VEEWASH_DASHBOARD.snapshotBorder}`,
          boxShadow: "0 8px 30px rgba(15, 23, 42, 0.06)",
        }}
      >
        <Box
          sx={{
            px: { xs: 2, md: 2.5 },
            py: 2,
            background: `linear-gradient(135deg, ${VEEWASH_DASHBOARD.primaryBlue} 0%, ${VEEWASH_DASHBOARD.tealDark} 100%)`,
            color: "#fff",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 1.5,
            flexWrap: "wrap",
          }}
        >
          <Box>
            <Typography variant="h5" fontWeight={800} sx={{ letterSpacing: "-0.02em" }}>
              Weekly Schedule
            </Typography>
            <Typography variant="body2" sx={{ opacity: 0.92, mt: 0.25 }}>
              Plan labor by day — drag shifts, assign Sort · Wash · Fold roles
            </Typography>
          </Box>
          <Stack
            direction="row"
            spacing={0.5}
            alignItems="center"
            sx={{
              bgcolor: "rgba(255,255,255,0.14)",
              borderRadius: 999,
              px: 0.5,
              py: 0.25,
            }}
          >
            <IconButton size="small" onClick={() => changeWeek(-1)} sx={{ color: "#fff" }}>
              <ChevronLeftIcon />
            </IconButton>
            <Typography variant="subtitle2" sx={{ minWidth: 220, textAlign: "center", fontWeight: 700 }}>
              {formatWeekRange(weekStart)}
            </Typography>
            <IconButton size="small" onClick={() => changeWeek(1)} sx={{ color: "#fff" }}>
              <ChevronRightIcon />
            </IconButton>
          </Stack>
        </Box>

        <Box
          sx={{
            px: 2,
            py: 1.25,
            bgcolor: "#fff",
            borderBottom: "1px solid #e8eef2",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 1,
            flexWrap: "wrap",
          }}
        >
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            {excludedCount > 0 && canManageExclusions ? (
              <Chip
                icon={<PersonOffOutlinedIcon />}
                label={showExcluded ? `Showing excluded (${excludedCount})` : `Show excluded (${excludedCount})`}
                onClick={() => setShowExcluded((v) => !v)}
                color={showExcluded ? "warning" : "default"}
                variant={showExcluded ? "filled" : "outlined"}
                sx={{ fontWeight: 700 }}
              />
            ) : null}
            {costAllowed ? (
              <Chip
                icon={<AttachMoneyOutlinedIcon />}
                label={showCost ? "Hide cost" : "Show cost"}
                onClick={handleCostToggle}
                disabled={costSaving}
                variant={showCost ? "filled" : "outlined"}
                color={showCost ? "primary" : "default"}
                sx={{ fontWeight: 700 }}
              />
            ) : null}
          </Stack>
          {!display.is_privileged && display.org_settings ? (
            <Typography variant="caption" color="text.secondary">
              Shared view — some details hidden per org settings
            </Typography>
          ) : null}
        </Box>

        <Box sx={{ p: 2 }}>
          {excludedCount > 0 && !showExcluded && canManageExclusions ? (
            <Alert
              severity="info"
              sx={{ mb: 2, borderRadius: 2 }}
              action={
                <Button color="inherit" size="small" onClick={() => setShowExcluded(true)} sx={{ fontWeight: 700 }}>
                  Show excluded ({excludedCount})
                </Button>
              }
            >
              {excludedCount} employee{excludedCount === 1 ? "" : "s"} excluded from this week&apos;s schedule. Toggle &quot;Show excluded&quot; to review and include them.
            </Alert>
          ) : null}
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
                  gridTemplateColumns: `minmax(200px, 240px) repeat(7, minmax(132px, 1fr))`,
                  minWidth: 1100,
                  gap: 0,
                  border: "1px solid #e2e8f0",
                  borderRadius: 2.5,
                  overflow: "hidden",
                  bgcolor: "#fff",
                }}
              >
                <Box
                  sx={{
                    p: 1.5,
                    bgcolor: "#f8fafc",
                    borderBottom: "1px solid #e2e8f0",
                    position: "sticky",
                    left: 0,
                    zIndex: 2,
                  }}
                >
                  <Typography variant="overline" fontWeight={800} color="text.secondary" sx={{ letterSpacing: "0.08em" }}>
                    Employee
                  </Typography>
                </Box>
                {DAY_LABELS.map((label, dow) => {
                  const summary = daySummary(dayTotals[dow]);
                  return (
                  <Box
                    key={label}
                    sx={{
                      p: 1.5,
                      bgcolor: "#f8fafc",
                      borderBottom: "1px solid #e2e8f0",
                      borderLeft: "1px solid #e2e8f0",
                    }}
                  >
                    <Typography variant="subtitle2" fontWeight={800}>
                      {label}
                    </Typography>
                    <Typography variant="caption" display="block" color="text.secondary" sx={{ mt: 0.35 }}>
                      {summary.people} people · {summary.hours.toFixed(1)} hrs
                    </Typography>
                    <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ mt: 0.5 }}>
                      {summary.sort > 0 ? (
                        <Chip
                          size="small"
                          label={`${summary.sort} Sort`}
                          sx={{ height: 20, fontSize: "0.62rem", fontWeight: 700, bgcolor: ROLE_STYLES.sort.bg, color: ROLE_STYLES.sort.accent, border: `1px solid ${ROLE_STYLES.sort.border}` }}
                        />
                      ) : null}
                      {summary.wash > 0 ? (
                        <Chip
                          size="small"
                          label={`${summary.wash} Wash`}
                          sx={{ height: 20, fontSize: "0.62rem", fontWeight: 700, bgcolor: ROLE_STYLES.wash.bg, color: ROLE_STYLES.wash.accent, border: `1px solid ${ROLE_STYLES.wash.border}` }}
                        />
                      ) : null}
                      {summary.fold > 0 ? (
                        <Chip
                          size="small"
                          label={`${summary.fold} Fold`}
                          sx={{ height: 20, fontSize: "0.62rem", fontWeight: 700, bgcolor: ROLE_STYLES.fold.bg, color: ROLE_STYLES.fold.accent, border: `1px solid ${ROLE_STYLES.fold.border}` }}
                        />
                      ) : null}
                    </Stack>
                  </Box>
                  );
                })}

                {(visibleEmployees || []).map((employee) => {
                  const excluded = Boolean(employee.excluded);
                  return (
                    <Box key={employee.user_id} sx={{ display: "contents" }}>
                      <Box
                        sx={{
                          p: 1.25,
                          borderBottom: "1px solid #e2e8f0",
                          bgcolor: excluded ? "#fafafa" : "#fff",
                          position: "sticky",
                          left: 0,
                          zIndex: 1,
                          boxShadow: excluded ? "none" : "2px 0 6px rgba(15,23,42,0.04)",
                        }}
                      >
                        <Stack direction="row" alignItems="flex-start" justifyContent="space-between" spacing={0.5}>
                          <Box sx={{ minWidth: 0, flex: 1 }}>
                            <Typography
                              variant="body2"
                              fontWeight={800}
                              noWrap
                              sx={{
                                textDecoration: excluded ? "line-through" : "none",
                                color: excluded ? "text.secondary" : "text.primary",
                              }}
                            >
                              {employee.display_name}
                            </Typography>
                            {excluded ? (
                              <Chip
                                size="small"
                                label="Excluded this week"
                                color="default"
                                sx={{ mt: 0.5, height: 20, fontSize: "0.62rem", fontWeight: 700 }}
                              />
                            ) : null}
                            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
                              {employeeSummary(employee, {
                                showCost: showCost && costAllowed,
                                showRates: showEmployeeRates,
                              })}
                            </Typography>
                          </Box>
                          {canManageExclusions ? (
                            <Tooltip title={excluded ? "Include in schedule" : "Exclude from this week's schedule"}>
                              <IconButton
                                size="small"
                                aria-label={excluded ? "Include in schedule" : "Exclude from schedule"}
                                disabled={excludeSavingUserId === employee.user_id}
                                onClick={() => handleExcludeToggle(employee, !excluded)}
                                sx={{ mt: -0.25, flexShrink: 0 }}
                              >
                                {excluded ? (
                                  <VisibilityOffOutlinedIcon fontSize="small" />
                                ) : (
                                  <PersonOffOutlinedIcon fontSize="small" />
                                )}
                              </IconButton>
                            </Tooltip>
                          ) : null}
                        </Stack>
                        {excluded && canManageExclusions ? (
                          <Button
                            size="small"
                            variant="contained"
                            color="success"
                            onClick={() => handleExcludeToggle(employee, false)}
                            disabled={excludeSavingUserId === employee.user_id}
                            sx={{ mt: 0.75, fontSize: "0.72rem", textTransform: "none", fontWeight: 700 }}
                          >
                            Include in schedule
                          </Button>
                        ) : null}
                      </Box>
                      {DAY_LABELS.map((_, dow) => {
                        const cellKey = `${employee.user_id}:${dow}`;
                        const cellEntries = entriesByCell[cellKey] || [];
                        const isDropTarget = dropTarget === cellKey;
                        return (
                          <Box
                            key={cellKey}
                            onDragOver={(e) => {
                              if (excluded || !canEdit) return;
                              e.preventDefault();
                              setDropTarget(cellKey);
                            }}
                            onDragLeave={() => {
                              if (dropTarget === cellKey) setDropTarget(null);
                            }}
                            onDrop={(e) => {
                              if (excluded || !canEdit) return;
                              e.preventDefault();
                              const entryId = e.dataTransfer.getData("text/plain");
                              handleDrop(employee.user_id, dow, entryId);
                            }}
                            sx={{
                              p: 0.75,
                              minHeight: 92,
                              borderBottom: "1px solid #e2e8f0",
                              borderLeft: "1px solid #e2e8f0",
                              bgcolor: excluded
                                ? "#fafafa"
                                : isDropTarget
                                  ? VEEWASH_DASHBOARD.primaryBlueLight
                                  : "#fff",
                              opacity: excluded ? 0.85 : 1,
                              transition: "background-color 0.12s ease",
                            }}
                          >
                            {cellEntries.map((entry) => (
                              <WeeklyScheduleShiftCard
                                key={entry.id}
                                entry={entry}
                                dragging={draggingId === entry.id}
                                muted={excluded}
                                showRoleLabels={showRoleLabels}
                                showBreakMinutes={showBreakMinutes}
                                onEdit={canEdit ? openEdit : undefined}
                                onDelete={canEdit ? handleDelete : undefined}
                                onDuplicate={canEdit ? handleDuplicate : undefined}
                                onDragStart={canEdit ? (e) => setDraggingId(e.id) : undefined}
                                onDragEnd={canEdit ? () => setDraggingId(null) : undefined}
                              />
                            ))}
                            {!excluded && canEdit ? (
                              <Button
                                size="small"
                                startIcon={<AddIcon sx={{ fontSize: 14 }} />}
                                onClick={() => openCreate(employee.user_id, dow)}
                                sx={{
                                  mt: 0.25,
                                  fontSize: "0.7rem",
                                  minWidth: 0,
                                  px: 0.75,
                                  color: "text.secondary",
                                  fontWeight: 600,
                                }}
                              >
                                Add shift
                              </Button>
                            ) : null}
                          </Box>
                        );
                      })}
                    </Box>
                  );
                })}
              </Box>
            </Box>
          )}
        </Box>
      </Paper>

      <WeeklyScheduleEntryDialog
        open={dialogOpen && canEdit}
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
