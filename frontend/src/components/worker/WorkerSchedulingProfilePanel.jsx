import { useCallback, useEffect, useMemo, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Divider,
  FormControl,
  FormControlLabel,
  InputLabel,
  LinearProgress,
  MenuItem,
  OutlinedInput,
  Paper,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import SaveIcon from "@mui/icons-material/Save";
import {
  getPayrollWorkerSchedulingProfile,
  putPayrollWorkerSchedulingProfile,
  putUserGeofences,
} from "../../api";
import SchedulingReadinessChip from "./SchedulingReadinessChip";
import WorkerAvailabilityEditor from "./WorkerAvailabilityEditor";
import WorkerSkillsEditor from "./WorkerSkillsEditor";
import { emptyAvailabilityWeek, profileCompleteness } from "../../payroll/workerSchedulingProfile";

function ProfileSection({ title, hint, children }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
      <Typography variant="subtitle1" fontWeight={700} gutterBottom>
        {title}
      </Typography>
      {hint ? (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          {hint}
        </Typography>
      ) : null}
      {children}
    </Paper>
  );
}

export default function WorkerSchedulingProfilePanel({ userId, payrollRow, canEdit, onSaved }) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [bundle, setBundle] = useState(null);
  const [form, setForm] = useState({});

  const load = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    setError("");
    try {
      const res = await getPayrollWorkerSchedulingProfile(userId);
      const data = res.data || {};
      setBundle(data);
      const w = data.worker || {};
      setForm({
        default_hourly_rate: w.default_hourly_rate ?? "",
        max_hours_per_week: w.max_hours_per_week ?? "",
        overtime_threshold: w.overtime_threshold ?? "",
        preferred_shift_id: w.preferred_shift_id ?? "",
        preferred_role_id: w.preferred_role_id ?? "",
        can_work_rinse: w.can_work_rinse !== false,
        can_work_drop_off: w.can_work_drop_off !== false,
        can_work_both: w.can_work_both !== false,
        active: w.active !== false,
        notes: w.notes || "",
        availability: w.availability?.length ? w.availability : emptyAvailabilityWeek(),
        role_skills: w.role_skills || [],
        geofence_ids: w.geofence_ids || [],
      });
    } catch (e) {
      setError(e.response?.data?.error || "Could not load scheduling profile.");
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    load();
  }, [load]);

  const workerPreview = useMemo(() => {
    if (!bundle?.worker) return null;
    return {
      ...bundle.worker,
      ...form,
      availability: form.availability,
      role_skills: form.role_skills,
      geofence_ids: form.geofence_ids,
    };
  }, [bundle, form]);

  const completeness = useMemo(
    () => (workerPreview ? profileCompleteness(workerPreview) : bundle?.completeness),
    [workerPreview, bundle],
  );

  const perf = bundle?.worker?.performance_preview;

  const save = async () => {
    setSaving(true);
    setError("");
    try {
      await putUserGeofences(userId, { geofence_ids: form.geofence_ids || [] });
      const res = await putPayrollWorkerSchedulingProfile(userId, {
        default_hourly_rate: form.default_hourly_rate === "" ? null : Number(form.default_hourly_rate),
        max_hours_per_week: form.max_hours_per_week === "" ? null : Number(form.max_hours_per_week),
        overtime_threshold: form.overtime_threshold === "" ? null : Number(form.overtime_threshold),
        preferred_shift_id: form.preferred_shift_id || null,
        preferred_role_id: form.preferred_role_id || null,
        can_work_rinse: form.can_work_rinse,
        can_work_drop_off: form.can_work_drop_off,
        can_work_both: form.can_work_both,
        active: form.active,
        notes: form.notes,
        availability: form.availability,
        role_skills: form.role_skills,
      });
      setBundle(res.data);
      onSaved?.(res.data);
    } catch (e) {
      setError(e.response?.data?.error || "Save failed.");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <Box sx={{ py: 4, textAlign: "center" }}>
        <CircularProgress size={28} />
      </Box>
    );
  }

  const settings = bundle?.settings || {};
  const geofences = bundle?.geofences || [];
  const displayName =
    payrollRow?.first_name || payrollRow?.last_name
      ? `${payrollRow?.first_name || ""} ${payrollRow?.last_name || ""}`.trim()
      : bundle?.worker?.worker_name;

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" flexWrap="wrap" useFlexGap sx={{ mb: 2 }}>
        <Box>
          <Typography variant="h6" fontWeight={700}>
            Scheduling & payroll setup
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Master profile for {displayName || "worker"} — consumed by Shift planner (not duplicated there).
          </Typography>
        </Box>
        <Stack direction="row" spacing={1} alignItems="center">
          <SchedulingReadinessChip worker={workerPreview} />
          {canEdit ? (
            <Button variant="contained" startIcon={<SaveIcon />} disabled={saving} onClick={save}>
              Save scheduling profile
            </Button>
          ) : null}
        </Stack>
      </Stack>

      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      <Paper variant="outlined" sx={{ p: 2, mb: 2, bgcolor: "action.hover" }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
          <Typography variant="subtitle2" fontWeight={700}>
            Profile complete: {completeness?.score ?? 0}%
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {completeness?.passed ?? 0}/{completeness?.total ?? 0} checks
          </Typography>
        </Stack>
        <LinearProgress variant="determinate" value={completeness?.score ?? 0} sx={{ mb: 1, height: 8, borderRadius: 1 }} />
        {(completeness?.missing || []).length ? (
          <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
            {(completeness?.missing || []).map((m) => (
              <Chip key={m} size="small" color="warning" variant="outlined" label={m} />
            ))}
          </Stack>
        ) : (
          <Typography variant="body2" color="success.main">
            All scheduling profile checks passed.
          </Typography>
        )}
      </Paper>

      <ProfileSection title="Basic worker info" hint="Name and phone are edited on Payroll tab. Category syncs from employment category.">
        <Stack spacing={1.5}>
          <TextField size="small" label="Worker name" value={displayName || ""} disabled fullWidth />
          <TextField size="small" label="Phone" value={bundle?.worker?.mobile || payrollRow?.mobile || "—"} disabled fullWidth />
          <Stack direction="row" spacing={1}>
            <Chip label={bundle?.worker?.worker_category_label || "Category —"} size="small" />
            <Chip label={form.active ? "Active" : "Inactive"} size="small" color={form.active ? "success" : "default"} />
          </Stack>
          {canEdit ? (
            <FormControlLabel
              control={<Checkbox checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} />}
              label="Active for scheduling"
            />
          ) : null}
          <TextField
            size="small"
            label="Scheduling notes"
            multiline
            minRows={2}
            fullWidth
            disabled={!canEdit}
            value={form.notes}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
          />
        </Stack>
      </ProfileSection>

      <ProfileSection title="Payroll setup" hint="Rate and hours limits feed estimated labor cost and overtime warnings in the planner.">
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
          <TextField
            size="small"
            label="Default hourly rate ($)"
            type="number"
            fullWidth
            disabled={!canEdit}
            value={form.default_hourly_rate}
            onChange={(e) => setForm({ ...form, default_hourly_rate: e.target.value })}
          />
          <TextField
            size="small"
            label="Max hours / week"
            type="number"
            fullWidth
            disabled={!canEdit}
            value={form.max_hours_per_week}
            onChange={(e) => setForm({ ...form, max_hours_per_week: e.target.value })}
          />
          <TextField
            size="small"
            label="OT threshold (hrs)"
            type="number"
            fullWidth
            disabled={!canEdit}
            helperText={`Org default: ${settings.overtime_threshold_hours ?? 40}h`}
            value={form.overtime_threshold}
            onChange={(e) => setForm({ ...form, overtime_threshold: e.target.value })}
          />
        </Stack>
        <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: "block" }}>
          Payment category/rule and batch funding — next payroll phase.
        </Typography>
      </ProfileSection>

      <ProfileSection title="Scheduling preferences">
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} sx={{ mb: 1.5 }}>
          <FormControl size="small" fullWidth disabled={!canEdit}>
            <InputLabel>Preferred shift</InputLabel>
            <Select
              label="Preferred shift"
              value={form.preferred_shift_id || ""}
              onChange={(e) => setForm({ ...form, preferred_shift_id: e.target.value })}
            >
              <MenuItem value="">—</MenuItem>
              {(settings.shifts || []).filter((s) => s.active).map((s) => (
                <MenuItem key={s.id} value={s.id}>
                  {s.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl size="small" fullWidth disabled={!canEdit}>
            <InputLabel>Preferred role</InputLabel>
            <Select
              label="Preferred role"
              value={form.preferred_role_id || ""}
              onChange={(e) => setForm({ ...form, preferred_role_id: e.target.value })}
            >
              <MenuItem value="">—</MenuItem>
              {(settings.roles || []).filter((r) => r.active).map((r) => (
                <MenuItem key={r.id} value={r.id}>
                  {r.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </Stack>
        {canEdit ? (
          <Stack direction="row" spacing={2} flexWrap="wrap">
            <FormControlLabel
              control={<Checkbox checked={form.can_work_rinse} onChange={(e) => setForm({ ...form, can_work_rinse: e.target.checked })} />}
              label="Can work Rinse"
            />
            <FormControlLabel
              control={<Checkbox checked={form.can_work_drop_off} onChange={(e) => setForm({ ...form, can_work_drop_off: e.target.checked })} />}
              label="Can work Drop Off"
            />
            <FormControlLabel
              control={<Checkbox checked={form.can_work_both} onChange={(e) => setForm({ ...form, can_work_both: e.target.checked })} />}
              label="Can work Both"
            />
          </Stack>
        ) : null}
      </ProfileSection>

      <ProfileSection title="Weekly availability">
        {canEdit ? (
          <WorkerAvailabilityEditor
            value={form.availability}
            onChange={(availability) => setForm({ ...form, availability })}
            shifts={settings.shifts}
          />
        ) : (
          <Typography variant="body2" color="text.secondary">
            {(form.availability || []).filter((a) => !a.unavailable_flag).length} day(s) configured
          </Typography>
        )}
      </ProfileSection>

      <ProfileSection title="Role & work stream skills">
        {canEdit ? (
          <WorkerSkillsEditor
            value={form.role_skills}
            onChange={(role_skills) => setForm({ ...form, role_skills })}
            roles={settings.roles}
            streams={settings.work_streams}
          />
        ) : (
          <Typography variant="body2">{(form.role_skills || []).length} skill(s) assigned</Typography>
        )}
      </ProfileSection>

      <ProfileSection title="Location compatibility" hint="Where this worker can be scheduled. Edited here; planner warns on mismatches.">
        {canEdit ? (
          <FormControl fullWidth size="small">
            <InputLabel>Locations</InputLabel>
            <Select
              multiple
              label="Locations"
              value={(form.geofence_ids || []).map(String)}
              onChange={(e) => {
                const v = e.target.value;
                setForm({ ...form, geofence_ids: (typeof v === "string" ? v.split(",") : v).map(Number) });
              }}
              input={<OutlinedInput label="Locations" />}
              renderValue={(sel) =>
                sel.map((id) => geofences.find((g) => String(g.id) === String(id))?.name || id).join(", ")
              }
            >
              {geofences.map((g) => (
                <MenuItem key={g.id} value={String(g.id)}>
                  <Checkbox checked={(form.geofence_ids || []).map(String).includes(String(g.id))} size="small" />
                  {g.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        ) : (
          <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
            {(bundle?.worker?.assigned_locations || []).map((g) => (
              <Chip key={g.id} label={g.name} size="small" />
            ))}
            {!(bundle?.worker?.assigned_locations || []).length ? (
              <Typography variant="body2" color="text.secondary">
                No locations assigned
              </Typography>
            ) : null}
          </Stack>
        )}
      </ProfileSection>

      <ProfileSection title="Performance mapping">
        {perf?.available ? (
          <Stack spacing={0.5}>
            <Typography variant="body2">
              Linked: <strong>{perf.rinse_user_name}</strong>
            </Typography>
            {perf.avg_bags_per_hour != null ? (
              <Typography variant="caption" color="text.secondary">
                ~{perf.avg_bags_per_hour} bags/hr (30d) · {perf.bags_30d} bags
              </Typography>
            ) : null}
          </Stack>
        ) : (
          <Typography variant="body2" color="text.secondary">
            {perf?.message || "No performance mapping yet. Link Rinse user in Folding maintenance."}
          </Typography>
        )}
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
          Attendance reliability and lateness tracking — planned for a later phase.
        </Typography>
      </ProfileSection>

      <Divider sx={{ my: 2 }} />
      <Button component={RouterLink} to="/payroll" startIcon={<OpenInNewIcon />}>
        Open shift planner
      </Button>
    </Box>
  );
}
