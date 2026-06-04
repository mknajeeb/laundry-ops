import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Collapse,
  Drawer,
  Fab,
  FormControl,
  IconButton,
  InputAdornment,
  InputLabel,
  MenuItem,
  Select,
  Snackbar,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import { Link as RouterLink } from "react-router-dom";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import EventBusyOutlinedIcon from "@mui/icons-material/EventBusyOutlined";
import AddIcon from "@mui/icons-material/Add";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import FilterListIcon from "@mui/icons-material/FilterList";
import IosShareIcon from "@mui/icons-material/IosShare";
import LightbulbOutlinedIcon from "@mui/icons-material/LightbulbOutlined";
import SearchIcon from "@mui/icons-material/Search";
import {
  getPayrollSchedulePlan,
  getPayrollScheduleSuggestions,
  postPayrollSchedulePublish,
  postPayrollScheduleSaveDraft,
} from "../api";
import ScheduleWorkerCard from "./schedule/ScheduleWorkerCard";
import PayrollFundingForecastPanel from "./PayrollFundingForecastPanel";
import ShareRosterDrawer from "./schedule/ShareRosterDrawer";
import ScheduleEmptyState from "./schedule/ScheduleEmptyState";
import PayrollPlanningSettingsPanel from "./PayrollPlanningSettingsPanel";
import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import { useAuth } from "../context/AuthContext";
import {
  addDaysYmd,
  applyWorkerProfileToForm,
  checkEntryProfileWarnings,
  computeDayPlan,
  computePlanSummary,
  computeScheduledHours,
  computeWorkerWeekStats,
  eligibleRolesForWorker,
  eligibleStreamsForWorker,
  enrichEntry,
  entriesForDate,
  newTempEntry,
  previewHoursAfterAssignment,
  removeLocalEntry,
  upsertLocalEntry,
  weekStartFromDate,
  workerProfileGaps,
  workerProfileUrl,
} from "../payroll/schedulePlanner";
import { computeFundingForecast } from "../payroll/fundingForecast";
import { WORKER_CATEGORY_OPTIONS } from "../payroll/payrollDocumentChecklists";
import { SCHEDULE_THEME } from "../payroll/scheduleTheme";

function localDateYmd(d = new Date()) {
  return d.toISOString().slice(0, 10);
}

function SummaryMetric({ label, value, highlight }) {
  return (
    <Box
      sx={{
        minWidth: 72,
        px: 1.25,
        py: 0.75,
        borderRadius: 2,
        bgcolor: highlight ? "error.50" : SCHEDULE_THEME.accentSoft,
        border: "1px solid",
        borderColor: highlight ? "error.light" : "transparent",
        flex: "0 0 auto",
      }}
    >
      <Typography variant="caption" color="text.secondary" display="block" lineHeight={1.2}>
        {label}
      </Typography>
      <Typography variant="body1" fontWeight={800} color={highlight ? "error.main" : "text.primary"}>
        {value}
      </Typography>
    </Box>
  );
}

function ShiftPlanCard({ plan, workerStatsMap, onAdd, onEdit, onRemove, onAbsent, onReplace, onSuggest }) {
  const gapShort = (plan.coverage_gaps || []).filter((g) => g.status === "short");
  const gapOver = (plan.coverage_gaps || []).filter((g) => g.status === "overstaffed");
  return (
    <Card sx={{ ...SCHEDULE_THEME.shiftCard, mb: 2.5 }}>
      <CardContent sx={{ p: 2 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="flex-start" sx={{ mb: 1.5 }}>
          <Box>
            <Typography variant="h6" fontWeight={800} sx={{ letterSpacing: "-0.02em" }}>
              {plan.shift_name}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {plan.people_count} people · {Number(plan.total_hours || 0).toFixed(0)} hrs · $
              {Number(plan.estimated_cost || 0).toFixed(0)} est.
            </Typography>
            <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ mt: 1 }}>
              {Object.entries(plan.role_counts || {}).map(([role, cnt]) => (
                <Chip key={role} size="small" label={`${role}: ${cnt}`} />
              ))}
            </Stack>
            <Stack direction="row" spacing={0.5} sx={{ mt: 1 }}>
              {gapShort.length ? (
                <Chip size="small" color="error" label={`${gapShort.length} gap${gapShort.length > 1 ? "s" : ""}`} />
              ) : (
                <Chip size="small" color="success" variant="outlined" label="Coverage OK" />
              )}
              {plan.overtime_risk_count ? (
                <Chip size="small" color="warning" label={`${plan.overtime_risk_count} OT risk`} />
              ) : null}
              {gapOver.length ? (
                <Chip size="small" variant="outlined" label="Overstaffed" />
              ) : null}
            </Stack>
          </Box>
          <Stack spacing={0.5}>
            <Button size="small" startIcon={<LightbulbOutlinedIcon />} onClick={() => onSuggest(plan)}>
              Suggest
            </Button>
            <Button size="small" variant="contained" onClick={() => onAdd(plan.shift_id)}>
              + Add
            </Button>
          </Stack>
        </Stack>

        {Object.entries(plan.by_stream || {}).map(([streamName, streamEntries]) => (
          <Box key={streamName} sx={{ mb: 2 }}>
            <Typography
              variant="overline"
              sx={{ color: SCHEDULE_THEME.accent, fontWeight: 800, letterSpacing: "0.08em" }}
            >
              {streamName} ({streamEntries.length})
            </Typography>
            {(streamEntries || []).map((e) => (
              <ScheduleWorkerCard
                key={e.id}
                entry={e}
                weekStats={workerStatsMap[e.worker_profile_id]}
                onEdit={onEdit}
                onRemove={onRemove}
                onAbsent={onAbsent}
                onReplace={onReplace}
              />
            ))}
            {!streamEntries?.length ? (
              <Typography variant="body2" color="text.secondary" sx={{ py: 1 }}>
                No one assigned — tap Suggest or Add
              </Typography>
            ) : null}
          </Box>
        ))}
      </CardContent>
    </Card>
  );
}

export default function PayrollSchedulingPanel() {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("md"));
  const { hasPerm, user } = useAuth();
  const canManageSettings =
    hasPerm("ta.settings") ||
    (user?.roles || []).some((r) => String(r).toUpperCase() === "ADMIN");

  const [settingsView, setSettingsView] = useState(false);
  const [view, setView] = useState("day");
  const [selectedDate, setSelectedDate] = useState(localDateYmd());
  const [settings, setSettings] = useState(null);
  const [workers, setWorkers] = useState([]);
  const [coverageTargets, setCoverageTargets] = useState([]);
  const [draftEntries, setDraftEntries] = useState([]);
  const [serverEntries, setServerEntries] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [summaryCollapsed, setSummaryCollapsed] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [editEntry, setEditEntry] = useState(null);
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState({});
  const [suggestions, setSuggestions] = useState(null);
  const [saving, setSaving] = useState(false);
  const [publishedCount, setPublishedCount] = useState(0);
  const [toast, setToast] = useState({ open: false, message: "", severity: "info" });
  const [replaceContext, setReplaceContext] = useState(null);

  const [filterShift, setFilterShift] = useState("");
  const [filterStream, setFilterStream] = useState("");
  const [filterRole, setFilterRole] = useState("");
  const [filterCategory, setFilterCategory] = useState("");
  const [search, setSearch] = useState("");
  const [onlyOt, setOnlyOt] = useState(false);
  const [onlyGaps, setOnlyGaps] = useState(false);

  const weekStart = useMemo(
    () => weekStartFromDate(selectedDate, settings?.week_starts_on ?? 0),
    [selectedDate, settings?.week_starts_on],
  );
  const weekEnd = useMemo(() => addDaysYmd(weekStart, 6), [weekStart]);

  const loadPlan = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getPayrollSchedulePlan({ start_date: weekStart, end_date: weekEnd });
      const data = res.data || {};
      setSettings(data.settings || null);
      setWorkers(data.workers || []);
      setCoverageTargets(data.coverage_targets || []);
      const entries = data.entries || [];
      setServerEntries(entries);
      setDraftEntries(entries.map((e) => ({ ...e })));
      setPublishedCount(data.published_count ?? 0);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Load failed");
    } finally {
      setLoading(false);
    }
  }, [weekStart, weekEnd]);

  useEffect(() => {
    loadPlan();
  }, [loadPlan]);

  const filteredEntries = useMemo(() => {
    let list = draftEntries.filter((e) => !e._deleted && e.status !== "cancelled" && e.status !== "replaced");
    if (view === "day") {
      list = list.filter((e) => String(e.work_date).slice(0, 10) === selectedDate);
    }
    if (filterShift) list = list.filter((e) => String(e.shift_id) === String(filterShift));
    if (filterStream) list = list.filter((e) => String(e.work_stream_id) === String(filterStream));
    if (filterRole) list = list.filter((e) => String(e.role_id) === String(filterRole));
    if (filterCategory) {
      list = list.filter((e) => {
        const w = workers.find((x) => String(x.id) === String(e.worker_profile_id));
        return w?.worker_category === filterCategory;
      });
    }
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter((e) => String(e.worker_name || "").toLowerCase().includes(q));
    }
    if (onlyOt) {
      list = list.filter((e) => {
        const st = computeWorkerWeekStats(e.worker_profile_id, draftEntries, settings, weekStart, {});
        return st.overtime_risk;
      });
    }
    return list;
  }, [
    draftEntries,
    view,
    selectedDate,
    filterShift,
    filterStream,
    filterRole,
    filterCategory,
    search,
    onlyOt,
    workers,
    settings,
    weekStart,
  ]);

  const planningEntries = useMemo(() => {
    if (onlyGaps && view === "day") {
      const dayPlan = computeDayPlan(draftEntries, settings, coverageTargets, selectedDate, workers);
      const gapShiftIds = new Set(
        (dayPlan.coverage_gaps || []).filter((g) => g.status === "short").map((g) => String(g.shift_id)),
      );
      return filteredEntries.filter((e) => gapShiftIds.has(String(e.shift_id)));
    }
    return filteredEntries;
  }, [filteredEntries, onlyGaps, view, draftEntries, settings, coverageTargets, selectedDate, workers]);

  const settingsWithWorkers = useMemo(
    () => (settings ? { ...settings, _workers: workers } : null),
    [settings, workers],
  );

  const dayPlanFull = useMemo(() => {
    if (!settingsWithWorkers) return null;
    return computeDayPlan(draftEntries, settingsWithWorkers, coverageTargets, selectedDate, workers);
  }, [draftEntries, settingsWithWorkers, coverageTargets, selectedDate, workers]);

  const dayPlan = useMemo(() => {
    if (!dayPlanFull) return null;
    if (!planningEntries.length && filteredEntries.length === 0 && (dayPlanFull.total_people || 0) === 0) {
      return dayPlanFull;
    }
    const displayIds = new Set(planningEntries.map((e) => e.id));
    const shiftPlans = (dayPlanFull.shift_plans || []).map((plan) => ({
      ...plan,
      by_stream: Object.fromEntries(
        Object.entries(plan.by_stream || {}).map(([k, entries]) => [
          k,
          entries.filter((e) => displayIds.has(e.id)),
        ]),
      ),
      entries: (plan.entries || []).filter((e) => displayIds.has(e.id)),
      people_count: (plan.entries || []).filter((e) => displayIds.has(e.id)).length,
    }));
    return { ...dayPlanFull, shift_plans: shiftPlans };
  }, [dayPlanFull, planningEntries, filteredEntries]);

  const weekSummary = useMemo(() => {
    if (!settings) return null;
    return computePlanSummary(draftEntries, workers, settings, coverageTargets, { weekStart });
  }, [draftEntries, workers, settings, coverageTargets, weekStart]);

  const workerStatsMap = useMemo(() => {
    const m = {};
    for (const w of workers) {
      const id = w.worker_profile_id || w.id;
      m[id] = computeWorkerWeekStats(id, draftEntries, settings, weekStart, w);
    }
    return m;
  }, [workers, draftEntries, settings, weekStart]);

  const activeSummary = view === "day" ? dayPlanFull : weekSummary;
  const hasUnsaved = JSON.stringify(draftEntries) !== JSON.stringify(serverEntries);

  const fundingForecast = useMemo(() => {
    if (!settings || !weekStart || !weekEnd) return null;
    const sw = settingsWithWorkers || { ...settings, _workers: workers };
    const enriched = draftEntries
      .filter((e) => !e._deleted)
      .map((e) => enrichEntry(e, sw));
    const calendarBundle = {
      categories: {
        default: {
          work_week_start_day: settings.week_starts_on ?? 0,
          payment_day_of_week: settings.payment_day_of_week ?? 5,
          overtime_enabled: true,
          overtime_threshold_hours: settings.overtime_threshold_hours ?? 40,
          include_draft_schedule_in_forecast: true,
          include_published_schedule_in_forecast: true,
        },
        w2: { overtime_enabled: true },
        contractor_1099: { overtime_enabled: false },
        temp: { overtime_enabled: false },
      },
    };
    return computeFundingForecast({
      entries: enriched,
      workers,
      settings,
      calendarBundle,
      weekStart,
      weekEnd,
      includeDraft: true,
      includePublished: true,
    });
  }, [draftEntries, workers, settings, settingsWithWorkers, weekStart, weekEnd]);

  const selectedFormWorker = useMemo(
    () => workers.find((w) => String(w.id) === String(form.worker_profile_id)),
    [workers, form.worker_profile_id],
  );

  const formEligibleRoles = useMemo(
    () => eligibleRolesForWorker(selectedFormWorker, settings || {}),
    [selectedFormWorker, settings],
  );

  const formEligibleStreams = useMemo(
    () => eligibleStreamsForWorker(selectedFormWorker, settings || {}, form.role_id),
    [selectedFormWorker, settings, form.role_id],
  );

  const formProfileWarnings = useMemo(() => {
    if (!selectedFormWorker || !settingsWithWorkers) return [];
    return checkEntryProfileWarnings({ ...form, work_date: form.work_date || selectedDate }, selectedFormWorker, settingsWithWorkers);
  }, [selectedFormWorker, form, selectedDate, settingsWithWorkers]);

  const formOtPreview = useMemo(() => {
    if (!form.worker_profile_id || !form.start_time || !form.end_time) return null;
    const worker = workers.find((w) => String(w.id) === String(form.worker_profile_id));
    const hours = computeScheduledHours(form.start_time, form.end_time, form.break_minutes);
    return previewHoursAfterAssignment(
      form.worker_profile_id,
      draftEntries,
      settings,
      weekStart,
      worker || {},
      hours,
      editEntry?.id,
    );
  }, [form, draftEntries, settings, weekStart, workers, editEntry]);

  const showToast = (message, severity = "info") => setToast({ open: true, message, severity });

  const handleWorkerSelect = (workerProfileId) => {
    const worker = workers.find((w) => String(w.id) === String(workerProfileId));
    setForm((prev) => {
      const base = { ...prev, worker_profile_id: workerProfileId };
      return worker && settings ? applyWorkerProfileToForm(base, worker, settings) : base;
    });
    if (worker) {
      const gaps = worker.profile_gaps || workerProfileGaps(worker);
      if (gaps.length) {
        showToast(`Profile needs attention: ${gaps[0]}`, "warning");
      }
    }
  };

  const applyLocal = (updater) => setDraftEntries((prev) => updater(prev));

  const assignReplacement = (originalEntry, suggestion) => {
    const replacement = newTempEntry(
      enrichEntry(
        {
          ...originalEntry,
          id: undefined,
          worker_profile_id: suggestion.worker_profile_id,
          worker_name: suggestion.worker_name,
          status: "scheduled",
          publish_status: "draft",
          replacement_for_schedule_id: originalEntry.id,
          change_note: `Replacement for ${originalEntry.worker_name}`,
        },
        { ...settings, _workers: workers },
      ),
    );
    applyLocal((prev) => {
      let next = upsertLocalEntry(prev, {
        ...originalEntry,
        status: "replaced",
        publish_status: "draft",
        _dirty: true,
        change_note: `Replaced by ${suggestion.worker_name}`,
      });
      next = upsertLocalEntry(next, replacement);
      return next;
    });
    setSuggestions(null);
    setReplaceContext(null);
    showToast(`Assigned ${suggestion.worker_name} as replacement`, "success");
  };

  const openAdd = (shiftId, streamId, roleId) => {
    const shift = (settings?.shifts || []).find((s) => String(s.id) === String(shiftId));
    setEditEntry(null);
    setForm({
      work_date: selectedDate,
      shift_id: shiftId || shift?.id || "",
      work_stream_id: streamId || "",
      role_id: roleId || "",
      worker_profile_id: "",
      start_time: shift?.start_time_default?.slice(0, 5) || "07:00",
      end_time: shift?.end_time_default?.slice(0, 5) || "15:00",
      break_minutes: settings?.default_break_minutes || 0,
      status: "scheduled",
      publish_status: "draft",
      notes: "",
    });
    setFormOpen(true);
  };

  const openEdit = (entry) => {
    setEditEntry(entry);
    setForm({
      work_date: String(entry.work_date).slice(0, 10),
      shift_id: entry.shift_id,
      work_stream_id: entry.work_stream_id || "",
      role_id: entry.role_id || "",
      worker_profile_id: entry.worker_profile_id,
      start_time: entry.start_time?.slice(0, 5),
      end_time: entry.end_time?.slice(0, 5),
      break_minutes: entry.break_minutes || 0,
      status: entry.status || "scheduled",
      publish_status: "draft",
      notes: entry.notes || "",
    });
    setFormOpen(true);
  };

  const commitLocalForm = () => {
    const hours = computeScheduledHours(form.start_time, form.end_time, form.break_minutes);
    const worker = workers.find((w) => String(w.id) === String(form.worker_profile_id));
    const rate = Number(worker?.default_hourly_rate || 0);
    const shift = (settings?.shifts || []).find((s) => String(s.id) === String(form.shift_id));
    const stream = (settings?.work_streams || []).find((s) => String(s.id) === String(form.work_stream_id));
    const role = (settings?.roles || []).find((r) => String(r.id) === String(form.role_id));
    const payload = enrichEntry(
      {
        ...(editEntry || {}),
        ...form,
        shift_id: Number(form.shift_id),
        worker_profile_id: Number(form.worker_profile_id),
        work_stream_id: form.work_stream_id ? Number(form.work_stream_id) : null,
        role_id: form.role_id ? Number(form.role_id) : null,
        scheduled_hours: hours,
        hourly_rate_snapshot: rate || null,
        worker_category_snapshot: worker?.worker_category || null,
        shift_snapshot: shift?.name || null,
        role_snapshot: role?.name || null,
        work_stream_snapshot: stream?.name || null,
        estimated_cost: rate ? hours * rate : 0,
        publish_status: "draft",
        _dirty: true,
      },
      settingsWithWorkers || { ...settings, _workers: workers },
    );
    applyLocal((prev) =>
      editEntry?.id ? upsertLocalEntry(prev, payload) : upsertLocalEntry(prev, newTempEntry(payload)),
    );
    if (formOtPreview?.overtime_risk) {
      showToast(
        `${worker?.worker_name || "Worker"} would exceed ${formOtPreview.threshold}h this week`,
        "warning",
      );
    }
    setFormOpen(false);
    setEditEntry(null);
  };

  const markAbsent = (entry) => {
    applyLocal((prev) =>
      upsertLocalEntry(prev, {
        ...entry,
        status: "sick",
        publish_status: "draft",
        _dirty: true,
        change_note: "Marked absent/sick",
      }),
    );
    showToast(`${entry.worker_name} marked sick — tap Replace to find coverage`, "warning");
  };

  const copyPreviousDay = () => {
    const prev = addDaysYmd(selectedDate, -1);
    const prevEntries = entriesForDate(draftEntries, prev);
    if (!prevEntries.length) {
      showToast("No shifts on the previous day to copy", "warning");
      return;
    }
    const copied = prevEntries.map((e) =>
      newTempEntry(
        enrichEntry(
          {
            ...e,
            id: undefined,
            work_date: selectedDate,
            publish_status: "draft",
            status: "scheduled",
          },
          { ...settings, _workers: workers },
        ),
      ),
    );
    applyLocal((prev) => [...prev, ...copied]);
    showToast(`Copied ${copied.length} shift(s) from ${prev}`, "success");
  };

  const loadSuggestions = async (plan, gap) => {
    try {
      const shiftId = plan?.shift_id || gap?.shift_id;
      const shift = (settings?.shifts || []).find((s) => String(s.id) === String(shiftId));
      const res = await getPayrollScheduleSuggestions({
        work_date: selectedDate,
        shift_id: shiftId,
        work_stream_id: gap?.work_stream_id,
        role_id: gap?.role_id,
        start_time: shift?.start_time_default,
        end_time: shift?.end_time_default,
      });
      setSuggestions({ ...res.data, shift_id: shiftId });
    } catch (e) {
      setError(e.response?.data?.error || "Suggestions failed");
    }
  };

  const saveDraft = async () => {
    setSaving(true);
    try {
      const res = await postPayrollScheduleSaveDraft({ entries: draftEntries });
      await loadPlan();
      showToast(`Draft saved (${res.data?.count ?? 0} entries)`, "success");
    } catch (e) {
      const msg = e.response?.data?.error || "Could not save draft.";
      setError(msg);
      showToast(msg, "error");
    } finally {
      setSaving(false);
    }
  };

  const publish = async () => {
    setSaving(true);
    try {
      if (hasUnsaved) await postPayrollScheduleSaveDraft({ entries: draftEntries });
      const res = await postPayrollSchedulePublish({ start_date: weekStart, end_date: weekEnd });
      await loadPlan();
      showToast(`Published ${res.data?.published_count ?? 0} shift(s)`, "success");
    } catch (e) {
      const msg = e.response?.data?.error || "Could not publish schedule.";
      setError(msg);
      showToast(msg, "error");
    } finally {
      setSaving(false);
    }
  };

  const weekDays = useMemo(() => {
    const d = [];
    for (let i = 0; i < 7; i += 1) d.push(addDaysYmd(weekStart, i));
    return d;
  }, [weekStart]);

  const formDrawer = (
    <Drawer
      anchor={isMobile ? "bottom" : "right"}
      open={formOpen}
      onClose={() => setFormOpen(false)}
      PaperProps={{
        sx: isMobile
          ? { borderRadius: "20px 20px 0 0", maxHeight: "90vh", px: 2, py: 2 }
          : { width: 400, px: 2, py: 2 },
      }}
    >
      <Typography variant="h6" fontWeight={800} sx={{ mb: 2 }}>
        {editEntry ? "Edit shift" : "Add to plan"}
      </Typography>
      <Stack spacing={2}>
        <TextField
          label="Date"
          type="date"
          size="small"
          InputLabelProps={{ shrink: true }}
          value={form.work_date || ""}
          onChange={(e) => setForm({ ...form, work_date: e.target.value })}
        />
        <FormControl size="small" fullWidth>
          <InputLabel>Worker</InputLabel>
          <Select
            label="Worker"
            value={form.worker_profile_id || ""}
            onChange={(e) => handleWorkerSelect(e.target.value)}
          >
            {workers.map((w) => (
              <MenuItem key={w.id} value={w.id}>
                {w.worker_name || w.display_name}
                {w.worker_category_label ? ` · ${w.worker_category_label}` : ""}
                {(w.profile_gaps || []).length ? " ⚠" : ""}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        {selectedFormWorker ? (
          <Box sx={{ p: 1.25, borderRadius: 2, bgcolor: SCHEDULE_THEME.accentSoft }}>
            <Typography variant="caption" color="text.secondary" display="block">
              From worker profile
            </Typography>
            <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ mt: 0.5 }}>
              {selectedFormWorker.worker_category_label ? (
                <Chip size="small" label={selectedFormWorker.worker_category_label} />
              ) : null}
              {selectedFormWorker.default_hourly_rate ? (
                <Chip size="small" variant="outlined" label={`$${Number(selectedFormWorker.default_hourly_rate).toFixed(2)}/hr`} />
              ) : (
                <Chip size="small" color="warning" label="Missing hourly rate" />
              )}
              {selectedFormWorker.max_hours_per_week ? (
                <Chip size="small" variant="outlined" label={`Max ${selectedFormWorker.max_hours_per_week}h/wk`} />
              ) : null}
            </Stack>
            {workerProfileUrl(selectedFormWorker.user_id) ? (
              <Button
                size="small"
                component={RouterLink}
                to={workerProfileUrl(selectedFormWorker.user_id)}
                target="_blank"
                rel="noopener"
                startIcon={<OpenInNewIcon />}
                sx={{ mt: 1 }}
              >
                Open worker profile
              </Button>
            ) : null}
          </Box>
        ) : null}
        <FormControl size="small" fullWidth>
          <InputLabel>Shift</InputLabel>
          <Select
            label="Shift"
            value={form.shift_id || ""}
            onChange={(e) => {
              const sh = (settings?.shifts || []).find((s) => String(s.id) === String(e.target.value));
              setForm({
                ...form,
                shift_id: e.target.value,
                start_time: sh?.start_time_default?.slice(0, 5),
                end_time: sh?.end_time_default?.slice(0, 5),
              });
            }}
          >
            {(settings?.shifts || [])
              .filter((s) => s.active)
              .map((s) => (
                <MenuItem key={s.id} value={s.id}>
                  {s.name}
                </MenuItem>
              ))}
          </Select>
        </FormControl>
        <Stack direction="row" spacing={1}>
          <TextField
            label="Start"
            type="time"
            size="small"
            fullWidth
            InputLabelProps={{ shrink: true }}
            value={form.start_time || ""}
            onChange={(e) => setForm({ ...form, start_time: e.target.value })}
          />
          <TextField
            label="End"
            type="time"
            size="small"
            fullWidth
            InputLabelProps={{ shrink: true }}
            value={form.end_time || ""}
            onChange={(e) => setForm({ ...form, end_time: e.target.value })}
          />
        </Stack>
        <FormControl size="small" fullWidth>
          <InputLabel>Stream</InputLabel>
          <Select
            label="Stream"
            value={form.work_stream_id || ""}
            onChange={(e) => setForm({ ...form, work_stream_id: e.target.value })}
          >
            {(formEligibleStreams.length ? formEligibleStreams : (settings?.work_streams || []).filter((s) => s.active)).map((s) => (
                <MenuItem key={s.id} value={s.id}>
                  {s.name}
                </MenuItem>
              ))}
          </Select>
        </FormControl>
        <FormControl size="small" fullWidth>
          <InputLabel>Role</InputLabel>
          <Select
            label="Role"
            value={form.role_id || ""}
            onChange={(e) => setForm({ ...form, role_id: e.target.value })}
          >
            {(formEligibleRoles.length ? formEligibleRoles : (settings?.roles || []).filter((r) => r.active)).map((r) => (
                <MenuItem key={r.id} value={r.id}>
                  {r.name}
                </MenuItem>
              ))}
          </Select>
        </FormControl>
        {formProfileWarnings.length ? (
          <Alert severity="warning">
            <Stack spacing={0.25}>
              {formProfileWarnings.map((w) => (
                <Typography key={w} variant="caption" display="block">
                  {w}
                </Typography>
              ))}
            </Stack>
          </Alert>
        ) : null}
        {formOtPreview ? (
          <Alert severity={formOtPreview.overtime_risk ? "warning" : "info"} icon={false}>
            After this shift: {formOtPreview.after.toFixed(1)}h this week
            {formOtPreview.overtime_risk
              ? ` — exceeds ${formOtPreview.threshold}h OT threshold`
              : ` · ${formOtPreview.hours_remaining.toFixed(1)}h before OT`}
          </Alert>
        ) : null}
        <Stack direction="row" spacing={1}>
          <Button fullWidth onClick={() => setFormOpen(false)}>
            Cancel
          </Button>
          <Button
            fullWidth
            variant="contained"
            onClick={commitLocalForm}
            disabled={!form.worker_profile_id || !form.shift_id}
          >
            {editEntry ? "Update plan" : "Add to plan"}
          </Button>
        </Stack>
      </Stack>
    </Drawer>
  );

  if (settingsView) {
    return (
      <Box sx={{ background: SCHEDULE_THEME.pageGradient, minHeight: "100%", mx: -1.2, px: 1.2, pb: 14 }}>
        <PayrollPlanningSettingsPanel
          onBack={() => {
            setSettingsView(false);
            loadPlan();
          }}
          onSaved={loadPlan}
        />
      </Box>
    );
  }

  return (
    <Box sx={{ background: SCHEDULE_THEME.pageGradient, minHeight: "100%", mx: -1.2, px: 1.2, pb: 14 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" sx={{ pt: 1, mb: 2 }}>
        <Box>
          <Typography variant="h5" fontWeight={800} sx={{ letterSpacing: "-0.03em" }}>
            Shift planner
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Live planning board — {publishedCount} published this week · draft changes private until publish
          </Typography>
        </Box>
        <Stack direction="row" spacing={0.5}>
          {canManageSettings ? (
            <IconButton color="primary" onClick={() => setSettingsView(true)} aria-label="Planning settings">
              <SettingsOutlinedIcon />
            </IconButton>
          ) : null}
          <IconButton color="primary" onClick={() => setShareOpen(true)} aria-label="Share roster">
            <IosShareIcon />
          </IconButton>
        </Stack>
      </Stack>

      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 2 }}>
        <Button size="small" variant={hasUnsaved ? "contained" : "outlined"} disabled={!hasUnsaved || saving} onClick={saveDraft}>
          Save draft
        </Button>
        <Button size="small" variant="contained" color="secondary" disabled={saving} onClick={publish}>
          Publish week
        </Button>
        <Button size="small" startIcon={<ContentCopyIcon />} onClick={copyPreviousDay}>
          Copy prev day
        </Button>
        <Button size="small" startIcon={<FilterListIcon />} onClick={() => setFiltersOpen((v) => !v)}>
          Filters
        </Button>
      </Stack>

      {fundingForecast ? <PayrollFundingForecastPanel forecast={fundingForecast} compact /> : null}

      {error ? (
        <Alert severity="error" sx={{ mb: 2, borderRadius: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      <Collapse in={filtersOpen}>
        <Card sx={{ ...SCHEDULE_THEME.card, mb: 2, p: 1.5 }}>
          <Stack spacing={1.5}>
            <TextField
              size="small"
              placeholder="Search worker…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              InputProps={{
                startAdornment: (
                  <InputAdornment position="start">
                    <SearchIcon fontSize="small" />
                  </InputAdornment>
                ),
              }}
            />
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <FormControl size="small" sx={{ minWidth: 120 }}>
                <InputLabel>Shift</InputLabel>
                <Select label="Shift" value={filterShift} onChange={(e) => setFilterShift(e.target.value)}>
                  <MenuItem value="">All</MenuItem>
                  {(settings?.shifts || []).map((s) => (
                    <MenuItem key={s.id} value={s.id}>
                      {s.name}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <FormControl size="small" sx={{ minWidth: 120 }}>
                <InputLabel>Stream</InputLabel>
                <Select label="Stream" value={filterStream} onChange={(e) => setFilterStream(e.target.value)}>
                  <MenuItem value="">All</MenuItem>
                  {(settings?.work_streams || []).map((s) => (
                    <MenuItem key={s.id} value={s.id}>
                      {s.name}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <FormControl size="small" sx={{ minWidth: 120 }}>
                <InputLabel>Category</InputLabel>
                <Select label="Category" value={filterCategory} onChange={(e) => setFilterCategory(e.target.value)}>
                  <MenuItem value="">All</MenuItem>
                  {WORKER_CATEGORY_OPTIONS.filter((o) => o.value !== "all").map((o) => (
                    <MenuItem key={o.value} value={o.value}>
                      {o.label}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <FormControl size="small" sx={{ minWidth: 120 }}>
                <InputLabel>Role</InputLabel>
                <Select label="Role" value={filterRole} onChange={(e) => setFilterRole(e.target.value)}>
                  <MenuItem value="">All</MenuItem>
                  {(settings?.roles || []).filter((r) => r.active).map((r) => (
                    <MenuItem key={r.id} value={r.id}>
                      {r.name}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <Chip
                label="OT risk only"
                clickable
                color={onlyOt ? "warning" : "default"}
                variant={onlyOt ? "filled" : "outlined"}
                onClick={() => setOnlyOt((v) => !v)}
              />
              <Chip
                label="Coverage gaps"
                clickable
                color={onlyGaps ? "error" : "default"}
                variant={onlyGaps ? "filled" : "outlined"}
                onClick={() => setOnlyGaps((v) => !v)}
              />
            </Stack>
          </Stack>
        </Card>
      </Collapse>

      <Tabs value={view} onChange={(_, v) => setView(v)} sx={{ mb: 1.5, minHeight: 40 }}>
        <Tab value="day" label="Day" sx={{ fontWeight: 700 }} />
        <Tab value="week" label="Week" sx={{ fontWeight: 700 }} />
      </Tabs>

      <Stack direction="row" alignItems="center" spacing={0.5} sx={{ mb: 2 }}>
        <IconButton onClick={() => setSelectedDate(addDaysYmd(selectedDate, view === "day" ? -1 : -7))}>
          <ChevronLeftIcon />
        </IconButton>
        <TextField
          type="date"
          size="small"
          value={selectedDate}
          onChange={(e) => setSelectedDate(e.target.value)}
          InputLabelProps={{ shrink: true }}
          sx={{ flex: 1 }}
        />
        <IconButton onClick={() => setSelectedDate(addDaysYmd(selectedDate, view === "day" ? 1 : 7))}>
          <ChevronRightIcon />
        </IconButton>
        <Button size="small" onClick={() => setSelectedDate(localDateYmd())}>
          Today
        </Button>
      </Stack>

      <Box sx={{ ...SCHEDULE_THEME.stickyBar, position: "sticky", top: 0, zIndex: 20, py: 1, mb: 2, mx: -0.5, px: 0.5 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: summaryCollapsed ? 0 : 1 }}>
          <Typography variant="subtitle2" fontWeight={800}>
            Live summary
            {hasUnsaved ? <Chip size="small" color="warning" label="Unsaved" sx={{ ml: 1 }} /> : null}
          </Typography>
          <Button size="small" onClick={() => setSummaryCollapsed((v) => !v)}>
            {summaryCollapsed ? "Expand" : "Collapse"}
          </Button>
        </Stack>
        <Collapse in={!summaryCollapsed}>
          <Stack direction="row" spacing={1} sx={{ overflowX: "auto", pb: 0.5 }}>
            <SummaryMetric label="People" value={activeSummary?.total_people ?? 0} />
            <SummaryMetric label="Morning" value={activeSummary?.morning_count ?? 0} />
            <SummaryMetric label="Afternoon" value={activeSummary?.afternoon_count ?? 0} />
            <SummaryMetric label="Rinse" value={activeSummary?.rinse_count ?? 0} />
            <SummaryMetric label="Drop Off" value={activeSummary?.drop_off_count ?? 0} />
            <SummaryMetric label="Hours" value={Number(activeSummary?.total_scheduled_hours || 0).toFixed(0)} />
            <SummaryMetric
              label="Est. cost"
              value={`$${Number(activeSummary?.estimated_payroll_cost || 0).toFixed(0)}`}
            />
            <SummaryMetric
              label="OT risk"
              value={activeSummary?.overtime_risk_count ?? 0}
              highlight={(activeSummary?.overtime_risk_count ?? 0) > 0}
            />
            <SummaryMetric
              label="Gaps"
              value={activeSummary?.open_coverage_gaps ?? 0}
              highlight={(activeSummary?.open_coverage_gaps ?? 0) > 0}
            />
          </Stack>
        </Collapse>
      </Box>

      {view === "day" && dayPlan && !dayPlanFull?.total_people && !loading ? (
        <ScheduleEmptyState
          icon={EventBusyOutlinedIcon}
          title="No shifts scheduled"
          description="Tap + to add a worker, or copy the previous day to get started."
          action={
            <Stack direction="row" spacing={1} justifyContent="center">
              <Button variant="contained" onClick={() => openAdd()}>
                Add shift
              </Button>
              <Button variant="outlined" onClick={copyPreviousDay}>
                Copy prev day
              </Button>
            </Stack>
          }
        />
      ) : null}

      {view === "day" && dayPlan && dayPlanFull?.total_people ? (
        <>
          {(dayPlan.coverage_gaps || []).filter((g) => g.status === "short").map((g) => (
            <Alert
              key={`${g.shift_id}-${g.role_id}`}
              severity="error"
              sx={{ mb: 1.5, borderRadius: 2 }}
              action={
                <Button color="inherit" size="small" onClick={() => loadSuggestions(null, g)}>
                  Suggest
                </Button>
              }
            >
              {g.shift_name} {g.work_stream_name} — need {g.required_count} {g.role_name}, have {g.scheduled_count}
            </Alert>
          ))}
          {(dayPlan.shift_plans || []).map((plan) => (
            <ShiftPlanCard
              key={plan.shift_id}
              plan={{
                ...plan,
                by_stream: Object.fromEntries(
                  Object.entries(plan.by_stream || {}).map(([k, entries]) => [
                    k,
                    entries.filter((e) => planningEntries.some((p) => p.id === e.id)),
                  ]),
                ),
                entries: (plan.entries || []).filter((e) => planningEntries.some((p) => p.id === e.id)),
                people_count: (plan.entries || []).filter((e) => planningEntries.some((p) => p.id === e.id)).length,
              }}
              workerStatsMap={workerStatsMap}
              onAdd={openAdd}
              onEdit={openEdit}
              onRemove={(id) => applyLocal((prev) => removeLocalEntry(prev, id))}
              onAbsent={markAbsent}
              onReplace={(e) => {
                setReplaceContext(e);
                loadSuggestions({ shift_id: e.shift_id, work_stream_id: e.work_stream_id, role_id: e.role_id }, null);
              }}
              onSuggest={loadSuggestions}
            />
          ))}
        </>
      ) : null}

      {view === "week" && weekSummary && !weekSummary.worker_stats?.length && !loading ? (
        <ScheduleEmptyState
          title="No workers loaded"
          description="Add payroll workers in People, then return to schedule."
        />
      ) : null}

      {view === "week" && weekSummary ? (
        <Stack spacing={1.5}>
          {(weekSummary.worker_stats || []).map((w) => {
            const stats = w.week_stats;
            if (!stats) return null;
            const wpid = w.worker_profile_id || w.id;
            if (onlyOt && !stats.overtime_risk) return null;
            return (
              <Card key={wpid} sx={SCHEDULE_THEME.card}>
                <CardContent sx={{ py: 1.5 }}>
                  <Stack direction="row" justifyContent="space-between" alignItems="center">
                    <Box>
                      <Typography fontWeight={700}>{w.worker_name || w.display_name}</Typography>
                      <Typography variant="caption" color="text.secondary">
                        {stats.scheduled_days} days · {stats.scheduled_hours.toFixed(1)}h sched ·{" "}
                        {Number(w.approved_hours || 0).toFixed(1)}h actual
                      </Typography>
                    </Box>
                    <Chip
                      size="small"
                      color={
                        stats.balance_label === "Overtime Risk"
                          ? "error"
                          : stats.balance_label === "Heavy"
                            ? "warning"
                            : stats.balance_label === "Underused"
                              ? "info"
                              : "success"
                      }
                      label={stats.balance_label}
                    />
                  </Stack>
                  <Stack direction="row" spacing={0.5} sx={{ mt: 1 }}>
                    {weekDays.map((d) => {
                      const n = (stats.entries || []).filter((e) => String(e.work_date).slice(0, 10) === d).length;
                      return (
                        <Box
                          key={d}
                          onClick={() => {
                            setSelectedDate(d);
                            setView("day");
                          }}
                          sx={{
                            flex: 1,
                            textAlign: "center",
                            py: 0.75,
                            borderRadius: 1.5,
                            bgcolor: n ? SCHEDULE_THEME.accentSoft : "action.hover",
                            cursor: "pointer",
                          }}
                        >
                          <Typography variant="caption">{d.slice(5)}</Typography>
                          <Typography variant="body2" fontWeight={700}>
                            {n || "—"}
                          </Typography>
                        </Box>
                      );
                    })}
                  </Stack>
                </CardContent>
              </Card>
            );
          })}
        </Stack>
      ) : null}

      {loading ? (
        <Typography variant="body2" color="text.secondary" sx={{ py: 4, textAlign: "center" }}>
          Loading plan…
        </Typography>
      ) : null}

      <Fab
        color="primary"
        sx={{ position: "fixed", bottom: 24, right: 24, boxShadow: "0 8px 32px rgba(99,102,241,0.4)" }}
        onClick={() => openAdd()}
      >
        <AddIcon />
      </Fab>

      {formDrawer}

      <Drawer
        anchor="bottom"
        open={!!suggestions}
        onClose={() => {
          setSuggestions(null);
          setReplaceContext(null);
        }}
        PaperProps={{ sx: { borderRadius: "20px 20px 0 0", maxHeight: "85vh", p: 2 } }}
      >
        <Typography variant="h6" fontWeight={800} sx={{ mb: 2 }}>
          {suggestions?.title || "Suggestions"}
        </Typography>
        <Stack spacing={1.5}>
          {(suggestions?.suggestions || []).map((s, idx) => (
            <Card key={s.worker_profile_id} variant="outlined" sx={{ borderRadius: 2 }}>
              <CardContent sx={{ py: 1.5 }}>
                <Stack direction="row" justifyContent="space-between">
                  <Typography fontWeight={700}>
                    {idx + 1}. {s.worker_name}
                  </Typography>
                  <Chip
                    size="small"
                    color={s.recommendation === "Best" ? "success" : s.recommendation?.includes("Avoid") ? "warning" : "default"}
                    label={s.recommendation}
                  />
                </Stack>
                {(s.reasons || []).map((r) => (
                  <Typography key={r} variant="caption" display="block" color="text.secondary">
                    {r}
                  </Typography>
                ))}
                <Button
                  size="small"
                  sx={{ mt: 1 }}
                  variant="contained"
                  onClick={() => {
                    if (replaceContext) {
                      assignReplacement(replaceContext, s);
                    } else {
                      openAdd(suggestions.shift_id);
                      setForm((f) => ({ ...f, worker_profile_id: s.worker_profile_id }));
                      setSuggestions(null);
                    }
                  }}
                >
                  Assign
                </Button>
              </CardContent>
            </Card>
          ))}
          {!suggestions?.suggestions?.length ? (
            <ScheduleEmptyState
              title="No replacements found"
              description="Try another shift, adjust filters, or check worker availability."
            />
          ) : null}
        </Stack>
      </Drawer>

      <ShareRosterDrawer
        open={shareOpen}
        onClose={() => setShareOpen(false)}
        defaultStart={weekStart}
        defaultEnd={weekEnd}
        publishedCount={publishedCount}
        settings={settings}
      />

      <Snackbar
        open={toast.open}
        autoHideDuration={4000}
        onClose={() => setToast((t) => ({ ...t, open: false }))}
        message={toast.message}
        anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
      />
    </Box>
  );
}
