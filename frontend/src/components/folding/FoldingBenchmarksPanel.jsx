import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  FormControl,
  Grid,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { getFoldingBenchmarks, updateFoldingBenchmarks } from "../../api";

const FIELDS = [
  { key: "bags_per_hour_target", label: "Bags per hour target" },
  { key: "lbs_per_hour_target", label: "Lbs per hour target" },
  { key: "minutes_per_bag_target", label: "Minutes per bag target" },
  { key: "issue_free_percent_target", label: "Quality target (%)" },
];

export default function FoldingBenchmarksPanel() {
  const [form, setForm] = useState(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const res = await getFoldingBenchmarks();
      setForm(res.data || {});
    } catch (e) {
      setMessage(e?.response?.data?.error || "Failed to load benchmarks");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    if (!form) return;
    try {
      setLoading(true);
      setMessage("");
      await updateFoldingBenchmarks({
        bags_per_hour_target: form.bags_per_hour_target,
        lbs_per_hour_target: form.lbs_per_hour_target,
        minutes_per_bag_target: form.minutes_per_bag_target,
        issue_free_percent_target: form.issue_free_percent_target,
        week_start_day: form.week_start_day || "MONDAY",
      });
      setMessage("Benchmarks saved.");
      await load();
    } catch (e) {
      setMessage(e?.response?.data?.error || "Save failed");
    } finally {
      setLoading(false);
    }
  };

  if (!form) {
    return <Typography variant="body2" color="text.secondary">Loading benchmarks…</Typography>;
  }

  return (
    <Paper sx={{ p: 2 }}>
      <Typography variant="subtitle1" fontWeight={800} gutterBottom>Performance benchmarks</Typography>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 2 }}>
        Targets for leaderboard comparison and quality scoring.
      </Typography>
      {message ? (
        <Alert severity={message.includes("saved") ? "success" : "error"} sx={{ mb: 2 }} onClose={() => setMessage("")}>
          {message}
        </Alert>
      ) : null}
      <Grid container spacing={2} sx={{ mb: 2 }}>
        {FIELDS.map(({ key, label }) => (
          <Grid item xs={12} sm={6} md={3} key={key}>
            <TextField
              size="small"
              fullWidth
              type="number"
              label={label}
              value={form[key] ?? ""}
              onChange={(e) => setForm({ ...form, [key]: e.target.value })}
            />
          </Grid>
        ))}
        <Grid item xs={12} sm={6} md={3}>
          <FormControl size="small" fullWidth>
            <InputLabel>Week starts</InputLabel>
            <Select
              label="Week starts"
              value={form.week_start_day || "MONDAY"}
              onChange={(e) => setForm({ ...form, week_start_day: e.target.value })}
            >
              {["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"].map((d) => (
                <MenuItem key={d} value={d}>{d[0] + d.slice(1).toLowerCase()}</MenuItem>
              ))}
            </Select>
          </FormControl>
        </Grid>
      </Grid>
      <Button variant="contained" onClick={save} disabled={loading}>Save benchmarks</Button>
    </Paper>
  );
}
