import { useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { recomputeFoldingPerformance } from "../api";
import { defaultWeekRange } from "../utils/foldingDateRange";

export default function PerformanceBackfillPage() {
  const initialWeek = defaultWeekRange();
  const [recomputeStart, setRecomputeStart] = useState(initialWeek.start);
  const [recomputeEnd, setRecomputeEnd] = useState(initialWeek.end);
  const [dateField, setDateField] = useState("date_clean");
  const [recomputeSummary, setRecomputeSummary] = useState(null);
  const [recomputing, setRecomputing] = useState(false);
  const [message, setMessage] = useState({ type: "", text: "" });

  const runRecompute = async () => {
    try {
      setRecomputing(true);
      setRecomputeSummary(null);
      const res = await recomputeFoldingPerformance({
        start_date: recomputeStart,
        end_date: recomputeEnd,
        date_field: dateField,
      });
      setRecomputeSummary(res.data?.summary || null);
      setMessage({ type: "success", text: "Backfill recompute finished." });
    } catch (e) {
      setMessage({ type: "error", text: e?.response?.data?.error || "Recompute failed" });
    } finally {
      setRecomputing(false);
    }
  };

  return (
    <Box sx={{ p: { xs: 2, md: 3 }, maxWidth: 900, mx: "auto" }}>
      <Typography variant="h4" fontWeight={800} gutterBottom>Performance Backfill</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Historical repair and recompute tools. Not required for normal nightly uploads.
      </Typography>
      {message.text ? <Alert severity={message.type || "info"} sx={{ mb: 2 }}>{message.text}</Alert> : null}
      <Paper sx={{ p: 2 }}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems="flex-end" flexWrap="wrap">
          <TextField type="date" size="small" label="Start" value={recomputeStart} onChange={(e) => setRecomputeStart(e.target.value)} InputLabelProps={{ shrink: true }} />
          <TextField type="date" size="small" label="End" value={recomputeEnd} onChange={(e) => setRecomputeEnd(e.target.value)} InputLabelProps={{ shrink: true }} />
          <FormControl size="small" sx={{ minWidth: 160 }}>
            <InputLabel>Date field</InputLabel>
            <Select label="Date field" value={dateField} onChange={(e) => setDateField(e.target.value)}>
              <MenuItem value="date_clean">date_clean</MenuItem>
              <MenuItem value="completed_at">completed_at</MenuItem>
            </Select>
          </FormControl>
          <Button variant="contained" onClick={runRecompute} disabled={recomputing}>
            {recomputing ? "Running…" : "Run backfill"}
          </Button>
        </Stack>
        {recomputeSummary ? (
          <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mt: 2 }}>
            <Chip label={`Processed: ${recomputeSummary.processed ?? 0}`} size="small" />
            <Chip label={`Skipped: ${recomputeSummary.skipped_not_completed ?? 0}`} size="small" />
            <Chip label={`Calculated: ${recomputeSummary.calculated ?? 0}`} size="small" color="success" />
            <Chip label={`Exceptions: ${recomputeSummary.exceptions ?? 0}`} size="small" color="warning" />
          </Stack>
        ) : null}
      </Paper>
    </Box>
  );
}
