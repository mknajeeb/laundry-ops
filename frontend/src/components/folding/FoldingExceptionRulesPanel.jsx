import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import {
  applyFoldingExceptionRules,
  dryRunFoldingExceptionRules,
  getFoldingExceptionRules,
  putFoldingExceptionRules,
} from "../../api";

const MF_EARLIEST = "warning_use_earliest_folding";
const MF_LATEST = "warning_use_latest_folding";
const MF_EXCEPTION = "exception";
const MC_EARLIEST = "warning_use_earliest_clean";
const MC_LATEST = "warning_use_latest_clean";
const MC_EXCEPTION = "exception";
const MF_LEGACY = "warning_use_earliest_default";

function normalizeMfBehavior(rules) {
  const v = rules?.multiple_folding_scans_behavior;
  if (v === MF_EXCEPTION || v === "exception") return MF_EXCEPTION;
  if (v === MF_LATEST || v === "warning_use_latest_folding") return MF_LATEST;
  if (v === MF_EARLIEST || v === MF_LEGACY) return MF_EARLIEST;
  return rules?.rule_multiple_folding_scans ? MF_EXCEPTION : MF_EARLIEST;
}

function normalizeMcBehavior(rules) {
  const v = rules?.multiple_clean_scans_behavior;
  if (v === MC_EXCEPTION || v === "exception") return MC_EXCEPTION;
  if (v === MC_LATEST) return MC_LATEST;
  if (v === MC_EARLIEST) return MC_EARLIEST;
  return rules?.multiple_clean_scans_as_exception ? MC_EXCEPTION : MC_EARLIEST;
}

export default function FoldingExceptionRulesPanel({ onRecomputeApplied }) {
  const [rules, setRules] = useState(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [dryRunResult, setDryRunResult] = useState(null);
  const [applyOpen, setApplyOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const res = await getFoldingExceptionRules();
      setRules(res.data || {});
    } catch (e) {
      setMessage(e?.response?.data?.error || "Failed to load exception rules");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    try {
      setLoading(true);
      setMessage("");
      setDryRunResult(null);
      const res = await putFoldingExceptionRules(rules);
      setRules(res.data);
      setMessage(res.data?.recompute_notice || "Exception rules saved.");
    } catch (e) {
      setMessage(e?.response?.data?.error || "Save failed");
    } finally {
      setLoading(false);
    }
  };

  const runDryRun = async () => {
    try {
      setBusy(true);
      setMessage("");
      const res = await dryRunFoldingExceptionRules();
      setDryRunResult(res.data);
      setMessage("Dry-run complete (no rows written).");
    } catch (e) {
      setMessage(e?.response?.data?.error || "Dry-run failed");
    } finally {
      setBusy(false);
    }
  };

  const runApply = async () => {
    try {
      setBusy(true);
      setMessage("");
      const res = await applyFoldingExceptionRules();
      setApplyOpen(false);
      setDryRunResult(null);
      const s = res.data?.summary || {};
      setMessage(
        `Recompute applied: processed=${s.processed ?? res.data?.bags_processed ?? "?"}, `
        + `calculated=${s.calculated ?? "?"}, exceptions=${s.exceptions ?? "?"}.`
      );
      await load();
      if (onRecomputeApplied) await onRecomputeApplied();
    } catch (e) {
      setMessage(e?.response?.data?.error || "Apply recompute failed");
    } finally {
      setBusy(false);
    }
  };

  if (!rules) {
    return <Typography variant="body2" color="text.secondary">Loading exception rules…</Typography>;
  }

  const pc = dryRunResult?.proposed_changes || {};
  const mfVal = normalizeMfBehavior(rules);
  const mcVal = normalizeMcBehavior(rules);

  return (
    <Paper sx={{ p: 2, mb: 3, border: "1px dashed", borderColor: "divider" }}>
      <Typography variant="subtitle1" fontWeight={800} gutterBottom>
        Exception rule thresholds
      </Typography>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
        Save settings updates thresholds only. Recompute rewrites stored folding performance
        (status, exception_code, warning_codes, scoring) — not scan timestamps or registry.
      </Typography>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 2 }}>
        Priority when multiple rules apply: (1) min duration (2) max duration (3) missing clean
        (4) missing folding (5) clean before folding (6) multiple clean (7) multiple folding.
        Lower-priority scan issues may appear as secondary warnings on the record.
      </Typography>

      {rules.recompute_needed ? (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Rules changed — recompute needed to apply to existing bags.
          {rules.last_recompute_at ? ` Last recompute: ${rules.last_recompute_at}.` : ""}
        </Alert>
      ) : null}

      {message ? (
        <Alert
          severity={
            message.includes("saved") || message.includes("applied") || message.includes("Dry-run")
              ? "success"
              : "error"
          }
          sx={{ mb: 2 }}
          onClose={() => setMessage("")}
        >
          {message}
        </Alert>
      ) : null}

      <Typography variant="subtitle2" fontWeight={700} sx={{ mt: 1, mb: 1 }}>
        Duration
      </Typography>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2} flexWrap="wrap" sx={{ mb: 1 }}>
        <FormControlLabel
          control={
            <Switch
              checked={rules.rule_min_duration_enabled !== false}
              onChange={(e) => setRules({ ...rules, rule_min_duration_enabled: e.target.checked })}
            />
          }
          label="Time less than minimum = exception"
        />
        <TextField
          size="small"
          type="number"
          label="Minimum (minutes)"
          value={rules.min_duration_minutes ?? 10}
          onChange={(e) => setRules({ ...rules, min_duration_minutes: Number(e.target.value) })}
          sx={{ width: 160 }}
          disabled={rules.rule_min_duration_enabled === false}
        />
      </Stack>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2} flexWrap="wrap" sx={{ mb: 2 }}>
        <FormControlLabel
          control={
            <Switch
              checked={rules.rule_max_duration_enabled !== false}
              onChange={(e) => setRules({ ...rules, rule_max_duration_enabled: e.target.checked })}
            />
          }
          label="Time more than maximum = exception"
        />
        <TextField
          size="small"
          type="number"
          label="Maximum (minutes, 0=off)"
          value={rules.max_duration_minutes ?? 240}
          onChange={(e) => setRules({ ...rules, max_duration_minutes: Number(e.target.value) })}
          sx={{ width: 200 }}
          disabled={rules.rule_max_duration_enabled === false}
          helperText={rules.max_duration_help || "0 disables max when enabled"}
        />
      </Stack>

      <Divider sx={{ my: 2 }} />

      <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
        Missing / timing
      </Typography>
      <Stack spacing={0.5} sx={{ mb: 2 }}>
        <FormControlLabel
          control={
            <Switch
              checked={!!rules.rule_missing_clean}
              onChange={(e) => setRules({ ...rules, rule_missing_clean: e.target.checked })}
            />
          }
          label="Missing clean scan = exception"
        />
        <FormControlLabel
          control={
            <Switch
              checked={!!rules.rule_missing_folding}
              onChange={(e) => setRules({ ...rules, rule_missing_folding: e.target.checked })}
            />
          }
          label="Missing folding scan = exception"
        />
        <FormControlLabel
          control={
            <Switch
              checked={!!rules.rule_clean_before_folding}
              onChange={(e) => setRules({ ...rules, rule_clean_before_folding: e.target.checked })}
            />
          }
          label="Clean before folding = exception"
        />
        <FormControlLabel
          control={
            <Switch
              checked={!!rules.rule_overlap_invalid_timing}
              onChange={(e) => setRules({ ...rules, rule_overlap_invalid_timing: e.target.checked })}
            />
          }
          label="Overlap / invalid timing = exception"
        />
      </Stack>

      <Divider sx={{ my: 2 }} />

      <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
        Multiple scans
      </Typography>
      <Stack direction={{ xs: "column", md: "row" }} spacing={2} flexWrap="wrap" sx={{ mb: 2 }}>
        <FormControl size="small" sx={{ minWidth: 360 }}>
          <InputLabel>Multiple clean scans</InputLabel>
          <Select
            label="Multiple clean scans"
            value={mcVal}
            onChange={(e) => {
              const v = e.target.value;
              setRules({
                ...rules,
                multiple_clean_scans_behavior: v,
                multiple_clean_scans_as_exception: v === MC_EXCEPTION,
              });
            }}
          >
            <MenuItem value={MC_EARLIEST}>
              Warning only — use earliest clean scan, keep in scoring
            </MenuItem>
            <MenuItem value={MC_LATEST}>
              Warning only — use latest clean scan, keep in scoring
            </MenuItem>
            <MenuItem value={MC_EXCEPTION}>
              Exception — exclude from scoring
            </MenuItem>
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: 360 }}>
          <InputLabel>Multiple folding scans</InputLabel>
          <Select
            label="Multiple folding scans"
            value={mfVal}
            onChange={(e) => {
              const v = e.target.value;
              setRules({
                ...rules,
                multiple_folding_scans_behavior: v,
                rule_multiple_folding_scans: v === MF_EXCEPTION,
              });
            }}
          >
            <MenuItem value={MF_EARLIEST}>
              Warning only — use earliest folding scan, keep in scoring (default)
            </MenuItem>
            <MenuItem value={MF_LATEST}>
              Warning only — use latest folding scan, keep in scoring
            </MenuItem>
            <MenuItem value={MF_EXCEPTION}>
              Exception — exclude from scoring
            </MenuItem>
          </Select>
        </FormControl>
      </Stack>

      <Stack direction="row" spacing={1} flexWrap="wrap">
        <Button variant="contained" onClick={save} disabled={loading}>Save exception rules</Button>
        <Button variant="outlined" onClick={runDryRun} disabled={busy || loading}>Dry-run recompute</Button>
        <Button variant="outlined" color="warning" onClick={() => setApplyOpen(true)} disabled={busy || loading}>
          Apply recompute
        </Button>
      </Stack>

      <Collapse in={Boolean(dryRunResult)}>
        <Box sx={{ mt: 2, p: 1.5, bgcolor: "grey.50", borderRadius: 1 }}>
          <Typography variant="subtitle2" fontWeight={700} gutterBottom>Dry-run summary</Typography>
          <Typography variant="body2">
            Bags evaluated: {dryRunResult?.total_completed_bags_evaluated ?? "—"}
          </Typography>
          <Typography variant="body2">
            CALCULATED → EXCEPTION: {pc.calculated_to_exception ?? 0} · EXCEPTION → CALCULATED:{" "}
            {pc.exception_to_calculated ?? 0} · Warning-only: {pc.warning_only ?? 0} · Unchanged:{" "}
            {pc.unchanged ?? 0}
          </Typography>
          {dryRunResult?.proposed_exception_code_counts ? (
            <Typography variant="caption" display="block" sx={{ mt: 1 }}>
              Too short (primary): {dryRunResult.proposed_exception_code_counts.FOLDING_DURATION_TOO_SHORT ?? 0}
              {" · "}
              Multiple folding (primary exception):{" "}
              {dryRunResult.proposed_exception_code_counts.MULTIPLE_FOLDING_SCANS ?? 0}
              {" · "}
              Multiple folding (secondary warning):{" "}
              {dryRunResult.proposed_warning_code_counts?.MULTIPLE_FOLDING_SCANS ?? 0}
            </Typography>
          ) : null}
        </Box>
      </Collapse>

      <Dialog open={applyOpen} onClose={() => !busy && setApplyOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Apply recompute?</DialogTitle>
        <DialogContent>
          <Typography>
            Apply recompute for this organization using current rules? This updates folding performance
            statuses and scoring only.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setApplyOpen(false)} disabled={busy}>Cancel</Button>
          <Button variant="contained" color="warning" onClick={runApply} disabled={busy}>
            {busy ? "Applying…" : "Apply recompute"}
          </Button>
        </DialogActions>
      </Dialog>
    </Paper>
  );
}
