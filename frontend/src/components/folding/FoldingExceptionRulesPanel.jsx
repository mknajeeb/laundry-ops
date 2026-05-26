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

  return (
    <Paper sx={{ p: 2, mb: 3, border: "1px dashed", borderColor: "divider" }}>
      <Typography variant="subtitle1" fontWeight={800} gutterBottom>
        Exception rule thresholds
      </Typography>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 2 }}>
        Save settings updates thresholds only. Recompute rewrites existing folding performance rows
        (no upload, registry, staging, or scan timestamp changes).
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

      <Stack direction={{ xs: "column", sm: "row" }} spacing={2} flexWrap="wrap" sx={{ mb: 2 }}>
        <TextField
          size="small"
          type="number"
          label="Min folding duration (minutes)"
          value={rules.min_duration_minutes ?? 10}
          onChange={(e) => setRules({ ...rules, min_duration_minutes: Number(e.target.value) })}
          sx={{ width: 220 }}
        />
        <TextField
          size="small"
          type="number"
          label="Max folding duration (minutes, 0=off)"
          value={rules.max_duration_minutes ?? 240}
          onChange={(e) => setRules({ ...rules, max_duration_minutes: Number(e.target.value) })}
          sx={{ width: 240 }}
          helperText={rules.max_duration_help || "0 disables max duration check"}
        />
      </Stack>
      <FormControl size="small" sx={{ minWidth: 360, mb: 2 }}>
        <InputLabel>Multiple folding scans</InputLabel>
        <Select
          label="Multiple folding scans"
          value={rules.multiple_folding_scans_behavior || "warning_use_earliest_default"}
          onChange={(e) => {
            const v = e.target.value;
            setRules({
              ...rules,
              multiple_folding_scans_behavior: v,
              rule_multiple_folding_scans: v === "exception",
            });
          }}
        >
          <MenuItem value="warning_use_earliest_default">
            Warning — use earliest scan, keep in scoring (default)
          </MenuItem>
          <MenuItem value="exception">Exception — block scoring</MenuItem>
        </Select>
      </FormControl>
      <Stack spacing={0.5}>
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
              checked={!!rules.multiple_clean_scans_as_exception}
              onChange={(e) => setRules({ ...rules, multiple_clean_scans_as_exception: e.target.checked })}
            />
          }
          label="Multiple clean scans = exception (off = warning only, still counts in scoring)"
        />
      </Stack>
      <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mt: 2 }}>
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
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
            Scan timestamps rewritten: {String(dryRunResult?.safety?.scan_timestamps_rewritten)} ·
            Registry/upload changed: {String(dryRunResult?.safety?.upload_staging_registry_rows_changed)}
          </Typography>
        </Box>
      </Collapse>

      <Dialog open={applyOpen} onClose={() => !busy && setApplyOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Apply recompute?</DialogTitle>
        <DialogContent>
          <Typography>
            Apply recompute for this organization using current rules? This updates folding performance
            statuses and scoring only. It does not change uploads, registry, staging, or scan timestamps.
            Reviewed/approved/excluded audit fields are preserved.
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
