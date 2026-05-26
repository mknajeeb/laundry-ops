import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
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
import { getFoldingExceptionRules, putFoldingExceptionRules } from "../../api";

export default function FoldingExceptionRulesPanel() {
  const [rules, setRules] = useState(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

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
      const res = await putFoldingExceptionRules(rules);
      setRules(res.data);
      setMessage("Exception rules saved.");
    } catch (e) {
      setMessage(e?.response?.data?.error || "Save failed");
    } finally {
      setLoading(false);
    }
  };

  if (!rules) {
    return <Typography variant="body2" color="text.secondary">Loading exception rules…</Typography>;
  }

  return (
    <Paper sx={{ p: 2, mb: 3, border: "1px dashed", borderColor: "divider" }}>
      <Typography variant="subtitle1" fontWeight={800} gutterBottom>
        Exception rule thresholds
      </Typography>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 2 }}>
        Tenant-scoped. Recompute folding after changing rules to apply to existing bags.
      </Typography>
      {message ? (
        <Alert severity={message.includes("saved") ? "success" : "error"} sx={{ mb: 2 }} onClose={() => setMessage("")}>
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
      <Box sx={{ mt: 2 }}>
        <Button variant="contained" onClick={save} disabled={loading}>Save exception rules</Button>
      </Box>
    </Paper>
  );
}
