import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  Drawer,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Switch,
  Tab,
  Tabs,
  TextField,
  Typography,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import CloseIcon from "@mui/icons-material/Close";
import IconButton from "@mui/material/IconButton";
import { postPayrollScheduleGenerateRoster } from "../../api";
import PlanningDateRangePicker from "../datetime/PlanningDateRangePicker";
import { businessTodayYmd, weekEndFromStart, weekStartFromDate } from "../../utils/businessTime";
import { SCHEDULE_THEME } from "../../payroll/scheduleTheme";
import { newTempEntry } from "../../payroll/schedulePlanner";

const defaultOptions = (weekStart, weekEnd, settings) => ({
  start_date: weekStart,
  end_date: weekEnd,
  work_stream_ids: [],
  shift_ids: [],
  use_coverage_targets: true,
  avoid_overtime: true,
  balance_hours: true,
  prefer_strong_performers: true,
  active_workers_only: true,
  include_incomplete_profiles: false,
  clear_existing_drafts_in_range: true,
  max_hours_per_worker: settings?.max_hours_per_week || "",
  notes: "",
});

export default function GenerateRosterDrawer({
  open,
  onClose,
  weekStart,
  weekEnd,
  selectedDate,
  settings,
  onAcceptDraft,
  onPublishWeek,
}) {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("sm"));
  const [step, setStep] = useState("setup");
  const [tab, setTab] = useState("summary");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [opts, setOpts] = useState(() =>
    defaultOptions(weekStart, weekEnd, settings),
  );

  const weekStartsOn = settings?.week_starts_on ?? 0;

  useEffect(() => {
    if (!open) return;
    setStep("setup");
    setTab("summary");
    setResult(null);
    setError("");
    const ws = weekStart || weekStartFromDate(selectedDate || businessTodayYmd(), weekStartsOn);
    const we = weekEnd || weekEndFromStart(ws);
    setOpts(defaultOptions(ws, we, settings));
  }, [open, weekStart, weekEnd, selectedDate, settings, weekStartsOn]);

  const streams = useMemo(
    () => (settings?.work_streams || []).filter((s) => s.active),
    [settings],
  );
  const shifts = useMemo(() => (settings?.shifts || []).filter((s) => s.active), [settings]);

  const toggleId = (field, id) => {
    const cur = opts[field] || [];
    const sid = String(id);
    const next = cur.map(String).includes(sid) ? cur.filter((x) => String(x) !== sid) : [...cur, id];
    setOpts({ ...opts, [field]: next });
  };

  const runGenerate = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const body = {
        ...opts,
        shift_ids: (opts.shift_ids || []).map(Number).filter(Boolean),
        work_stream_ids: (opts.work_stream_ids || []).map(Number).filter(Boolean),
        max_hours_per_worker:
          opts.max_hours_per_worker === "" || opts.max_hours_per_worker == null
            ? null
            : Number(opts.max_hours_per_worker),
      };
      const res = await postPayrollScheduleGenerateRoster(body);
      setResult(res.data);
      setStep("results");
      setTab("summary");
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Generation failed");
    } finally {
      setLoading(false);
    }
  }, [opts]);

  const acceptDraft = () => {
    if (!result?.proposed_entries?.length) {
      onClose();
      return;
    }
    const entries = result.proposed_entries.map((e) =>
      newTempEntry({
        ...e,
        id: undefined,
        _roster_generated: true,
        publish_status: "draft",
        change_note: e.change_note || "Auto roster draft",
      }),
    );
    onAcceptDraft?.(entries, {
      clearRangeDrafts: opts.clear_existing_drafts_in_range,
      start_date: opts.start_date,
      end_date: opts.end_date,
    });
    onClose();
  };

  const clearGenerated = () => {
    onAcceptDraft?.([], {
      clearGeneratedOnly: true,
      start_date: opts.start_date,
      end_date: opts.end_date,
    });
    setResult(null);
    setStep("setup");
  };

  const summary = result?.summary;

  const setupForm = (
    <Stack spacing={2}>
      <Alert severity="info" icon={<AutoAwesomeIcon />}>
        Rule-based draft generator — nothing is published until you review and publish the week.
      </Alert>
      <PlanningDateRangePicker
        start={opts.start_date}
        end={opts.end_date}
        weekStartsOn={weekStartsOn}
        onChange={({ start, end }) =>
          setOpts((p) => ({
            ...p,
            ...(start != null ? { start_date: start } : {}),
            ...(end != null ? { end_date: end } : {}),
          }))
        }
      />
      <Box>
        <Typography variant="caption" color="text.secondary" fontWeight={700} display="block" sx={{ mb: 0.5 }}>
          Work streams to include
        </Typography>
        <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
          {streams.map((s) => (
            <Chip
              key={s.id}
              label={s.name}
              clickable
              color={(opts.work_stream_ids || []).map(String).includes(String(s.id)) ? "primary" : "default"}
              onClick={() => toggleId("work_stream_ids", s.id)}
              sx={{ minHeight: 36 }}
            />
          ))}
          <Chip
            label="All streams"
            variant="outlined"
            onClick={() => setOpts({ ...opts, work_stream_ids: [] })}
          />
        </Stack>
      </Box>
      <Box>
        <Typography variant="caption" color="text.secondary" fontWeight={700} display="block" sx={{ mb: 0.5 }}>
          Shifts to include
        </Typography>
        <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
          {shifts.map((s) => (
            <Chip
              key={s.id}
              label={s.name}
              clickable
              color={(opts.shift_ids || []).map(String).includes(String(s.id)) ? "primary" : "default"}
              onClick={() => toggleId("shift_ids", s.id)}
              sx={{ minHeight: 36 }}
            />
          ))}
          <Chip label="All shifts" variant="outlined" onClick={() => setOpts({ ...opts, shift_ids: [] })} />
        </Stack>
      </Box>
      <Stack spacing={0.5}>
        <FormControlLabel
          control={
            <Switch
              checked={opts.use_coverage_targets}
              onChange={(e) => setOpts({ ...opts, use_coverage_targets: e.target.checked })}
            />
          }
          label="Use coverage targets"
        />
        <FormControlLabel
          control={
            <Switch checked={opts.avoid_overtime} onChange={(e) => setOpts({ ...opts, avoid_overtime: e.target.checked })} />
          }
          label="Avoid overtime"
        />
        <FormControlLabel
          control={
            <Switch checked={opts.balance_hours} onChange={(e) => setOpts({ ...opts, balance_hours: e.target.checked })} />
          }
          label="Balance hours (prefer underused workers)"
        />
        <FormControlLabel
          control={
            <Switch
              checked={opts.prefer_strong_performers}
              onChange={(e) => setOpts({ ...opts, prefer_strong_performers: e.target.checked })}
            />
          }
          label="Prefer stronger performers"
        />
        <FormControlLabel
          control={
            <Switch
              checked={opts.active_workers_only}
              onChange={(e) => setOpts({ ...opts, active_workers_only: e.target.checked })}
            />
          }
          label="Active workers only"
        />
        <FormControlLabel
          control={
            <Switch
              checked={opts.include_incomplete_profiles}
              onChange={(e) => setOpts({ ...opts, include_incomplete_profiles: e.target.checked })}
            />
          }
          label="Include workers with incomplete profiles"
        />
        <FormControlLabel
          control={
            <Switch
              checked={opts.clear_existing_drafts_in_range}
              onChange={(e) => setOpts({ ...opts, clear_existing_drafts_in_range: e.target.checked })}
            />
          }
          label="Replace existing drafts in date range when accepting"
        />
      </Stack>
      <TextField
        label="Max hours per worker (generator cap)"
        type="number"
        size="small"
        value={opts.max_hours_per_worker}
        onChange={(e) => setOpts({ ...opts, max_hours_per_worker: e.target.value })}
        helperText="Optional weekly cap while building this draft"
      />
      <TextField
        label="Notes"
        size="small"
        multiline
        minRows={2}
        value={opts.notes}
        onChange={(e) => setOpts({ ...opts, notes: e.target.value })}
      />
      {error ? (
        <Alert severity="error" onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}
      <Button
        variant="contained"
        size="large"
        startIcon={loading ? <CircularProgress size={18} color="inherit" /> : <AutoAwesomeIcon />}
        disabled={loading || !opts.start_date}
        onClick={runGenerate}
        sx={{ minHeight: 48 }}
      >
        Generate draft roster
      </Button>
    </Stack>
  );

  const resultsView = result ? (
    <Stack spacing={2}>
      <Alert severity="success">{result.message}</Alert>
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
        <Chip label={`${summary?.assigned_count ?? 0} assigned`} color="primary" />
        <Chip label={`${summary?.gap_count ?? 0} gaps`} color={summary?.gap_count ? "warning" : "default"} />
        <Chip label={`${summary?.conflict_count ?? 0} conflicts`} color={summary?.conflict_count ? "error" : "default"} />
        <Chip label={`${summary?.total_scheduled_hours ?? 0}h`} variant="outlined" />
        <Chip label={`$${Number(summary?.estimated_payroll_cost || 0).toLocaleString()} est.`} variant="outlined" />
      </Stack>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable">
        <Tab value="summary" label="Summary" />
        <Tab value="assignments" label={`Assignments (${result.assignments?.length || 0})`} />
        <Tab value="gaps" label={`Gaps (${result.gap_report?.length || 0})`} />
        <Tab value="conflicts" label={`Conflicts (${result.conflict_report?.length || 0})`} />
      </Tabs>
      {tab === "summary" ? (
        <Stack spacing={1.5}>
          {(summary?.coverage_by_shift_role_stream || []).map((row) => (
            <Box key={`${row.shift}-${row.stream}-${row.role}`} sx={{ p: 1.25, borderRadius: 2, bgcolor: SCHEDULE_THEME.accentSoft }}>
              <Typography variant="body2" fontWeight={700}>
                {row.shift} · {row.stream} · {row.role}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {row.assignments} assignment(s) · {row.hours}h
              </Typography>
            </Box>
          ))}
          {summary?.workers_not_used?.length ? (
            <Alert severity="info">
              <Typography variant="subtitle2" fontWeight={700}>
                Workers not used ({summary.workers_not_used.length})
              </Typography>
              <Typography variant="caption" component="div">
                {summary.workers_not_used
                  .slice(0, 8)
                  .map((w) => w.worker_name)
                  .join(", ")}
                {summary.workers_not_used.length > 8 ? "…" : ""}
              </Typography>
            </Alert>
          ) : null}
          {summary?.workers_underused?.length ? (
            <Alert severity="warning">
              <Typography variant="subtitle2" fontWeight={700}>
                Still underused after draft
              </Typography>
              <Typography variant="caption" component="div">
                {summary.workers_underused
                  .slice(0, 6)
                  .map((w) => `${w.worker_name} (${w.projected_week_hours}h)`)
                  .join(", ")}
              </Typography>
            </Alert>
          ) : null}
        </Stack>
      ) : null}
      {tab === "assignments" ? (
        <Stack spacing={1} sx={{ maxHeight: 360, overflow: "auto" }}>
          {(result.assignments || []).map((a, i) => (
            <Box key={i} sx={{ p: 1.25, borderRadius: 2, border: "1px solid", borderColor: "divider" }}>
              <Typography variant="body2" fontWeight={700}>
                {a.worker_name}
              </Typography>
              <Typography variant="caption" color="text.secondary" display="block">
                {a.work_date} · {a.shift_name} · {a.work_stream_name} · {a.role_name}
              </Typography>
              <Typography variant="caption" sx={{ mt: 0.5, display: "block" }}>
                {a.summary || (a.reasons || []).join(" · ")}
              </Typography>
            </Box>
          ))}
        </Stack>
      ) : null}
      {tab === "gaps" ? (
        <Stack spacing={1} sx={{ maxHeight: 360, overflow: "auto" }}>
          {(result.gap_report || []).length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              No coverage gaps — all targets filled.
            </Typography>
          ) : (
            result.gap_report.map((g, i) => (
              <Alert key={i} severity="warning" sx={{ py: 0.5 }}>
                <Typography variant="body2" fontWeight={700}>
                  {g.day_label || g.work_date} {g.shift_name} {g.work_stream_name} {g.role_name}
                </Typography>
                <Typography variant="caption">
                  Required: {g.required} · Assigned: {g.assigned} · {g.reason}
                </Typography>
              </Alert>
            ))
          )}
        </Stack>
      ) : null}
      {tab === "conflicts" ? (
        <Stack spacing={1} sx={{ maxHeight: 360, overflow: "auto" }}>
          {(result.conflict_report || []).length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              No conflicts flagged.
            </Typography>
          ) : (
            result.conflict_report.map((c, i) => (
              <Alert key={i} severity="error" sx={{ py: 0.5 }}>
                <Typography variant="body2" fontWeight={700}>
                  {c.worker_name} — {c.work_date} {c.shift_name}
                </Typography>
                <Typography variant="caption">{(c.issues || []).join(" · ")}</Typography>
              </Alert>
            ))
          )}
        </Stack>
      ) : null}
      <Divider />
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
        <Button variant="contained" fullWidth onClick={acceptDraft} sx={{ minHeight: 44 }}>
          Accept draft into planner
        </Button>
        <Button variant="outlined" fullWidth onClick={() => setStep("setup")} sx={{ minHeight: 44 }}>
          Edit options
        </Button>
      </Stack>
      <Stack direction="row" spacing={1}>
        <Button size="small" onClick={runGenerate} disabled={loading}>
          Regenerate
        </Button>
        <Button size="small" color="inherit" onClick={clearGenerated}>
          Clear
        </Button>
        {onPublishWeek ? (
          <Button size="small" color="secondary" onClick={() => onPublishWeek()}>
            Publish after review…
          </Button>
        ) : null}
      </Stack>
    </Stack>
  ) : null;

  return (
    <Drawer
      anchor={isMobile ? "bottom" : "right"}
      open={open}
      onClose={onClose}
      PaperProps={{
        sx: isMobile
          ? { borderRadius: "20px 20px 0 0", maxHeight: "92vh", px: 2, py: 2 }
          : { width: { xs: "100%", sm: 480 }, maxWidth: "100vw", px: 2, py: 2 },
      }}
    >
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
        <Typography variant="h6" fontWeight={800}>
          {step === "setup" ? "Generate draft roster" : "Draft roster results"}
        </Typography>
        <IconButton onClick={onClose} aria-label="Close">
          <CloseIcon />
        </IconButton>
      </Stack>
      {step === "setup" ? setupForm : resultsView}
    </Drawer>
  );
}
