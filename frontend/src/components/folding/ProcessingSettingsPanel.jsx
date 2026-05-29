import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Grid,
  Paper,
  TextField,
  Typography,
} from "@mui/material";
import { getProcessingSettings, putProcessingSettings } from "../../api";

function secondsToMinSec(total) {
  const s = Math.max(0, Number(total) || 0);
  const m = Math.floor(s / 60);
  const r = s % 60;
  return { minutes: m, seconds: r };
}

function minSecToSeconds(minutes, seconds) {
  return Math.max(0, (Number(minutes) || 0) * 60 + (Number(seconds) || 0));
}

function DurationField({ label, minutes, seconds, onChange }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
        {label}
      </Typography>
      <Grid container spacing={1}>
        <Grid item xs={6}>
          <TextField
            size="small"
            type="number"
            label="Min"
            value={minutes}
            onChange={(e) => onChange(Number(e.target.value), seconds)}
            inputProps={{ min: 0 }}
            fullWidth
          />
        </Grid>
        <Grid item xs={6}>
          <TextField
            size="small"
            type="number"
            label="Sec"
            value={seconds}
            onChange={(e) => onChange(minutes, Number(e.target.value))}
            inputProps={{ min: 0, max: 59 }}
            fullWidth
          />
        </Grid>
      </Grid>
    </Box>
  );
}

export default function ProcessingSettingsPanel() {
  const [fields, setFields] = useState(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const res = await getProcessingSettings();
      const d = res.data || {};
      setFields({
        weigh: secondsToMinSec(d.processing_weigh_seconds_per_bag),
        sort: secondsToMinSec(d.processing_sort_seconds_per_bag),
        wash: secondsToMinSec(d.processing_wash_seconds_per_bag),
        dry: secondsToMinSec(d.processing_dry_seconds_per_bag),
        rejectMinutes: d.reject_no_start_cleaning_minutes ?? 30,
        washingMinutes: d.washing_minutes ?? 30,
        dryingMinutes: d.drying_minutes ?? 40,
        rejectAfterIssueMinutes: d.reject_after_create_issue_minutes ?? 45,
        totalMinutes: d.total_minutes_per_bag,
      });
    } catch (e) {
      setMessage(e?.response?.data?.error || "Failed to load processing settings");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    if (!fields) return;
    try {
      setLoading(true);
      setMessage("");
      const body = {
        processing_weigh_seconds_per_bag: minSecToSeconds(fields.weigh.minutes, fields.weigh.seconds),
        processing_sort_seconds_per_bag: minSecToSeconds(fields.sort.minutes, fields.sort.seconds),
        processing_wash_seconds_per_bag: minSecToSeconds(fields.wash.minutes, fields.wash.seconds),
        processing_dry_seconds_per_bag: minSecToSeconds(fields.dry.minutes, fields.dry.seconds),
        reject_no_start_cleaning_minutes: Math.max(1, Number(fields.rejectMinutes) || 30),
        washing_minutes: Math.max(1, Number(fields.washingMinutes) || 30),
        drying_minutes: Math.max(1, Number(fields.dryingMinutes) || 40),
        reject_after_create_issue_minutes: Math.max(1, Number(fields.rejectAfterIssueMinutes) || 45),
      };
      const res = await putProcessingSettings(body);
      const d = res.data || {};
      setFields({
        weigh: secondsToMinSec(d.processing_weigh_seconds_per_bag),
        sort: secondsToMinSec(d.processing_sort_seconds_per_bag),
        wash: secondsToMinSec(d.processing_wash_seconds_per_bag),
        dry: secondsToMinSec(d.processing_dry_seconds_per_bag),
        rejectMinutes: d.reject_no_start_cleaning_minutes ?? 30,
        washingMinutes: d.washing_minutes ?? 30,
        dryingMinutes: d.drying_minutes ?? 40,
        rejectAfterIssueMinutes: d.reject_after_create_issue_minutes ?? 45,
        totalMinutes: d.total_minutes_per_bag,
      });
      setMessage("Processing time settings saved.");
    } catch (e) {
      setMessage(e?.response?.data?.error || "Save failed");
    } finally {
      setLoading(false);
    }
  };

  if (!fields) {
    return (
      <Typography variant="body2" color="text.secondary">
        Loading processing settings…
      </Typography>
    );
  }

  const totalSec = minSecToSeconds(fields.weigh.minutes, fields.weigh.seconds)
    + minSecToSeconds(fields.sort.minutes, fields.sort.seconds)
    + minSecToSeconds(fields.wash.minutes, fields.wash.seconds)
    + minSecToSeconds(fields.dry.minutes, fields.dry.seconds);

  return (
    <Paper sx={{ p: 2, mb: 3, border: "1px dashed", borderColor: "divider" }}>
      <Typography variant="subtitle1" fontWeight={800} gutterBottom>
        Processing time assumptions
      </Typography>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 2 }}>
        Estimated processing minutes per bag (weigh, sort, wash handling, dry handling). Stored in seconds;
        defaults total 7 min 30 sec per bag.
      </Typography>
      {message ? (
        <Alert
          severity={message.includes("saved") ? "success" : "error"}
          sx={{ mb: 2 }}
          onClose={() => setMessage("")}
        >
          {message}
        </Alert>
      ) : null}
      <Grid container spacing={2} sx={{ mb: 2 }}>
        <Grid item xs={12} sm={6} md={3}>
          <DurationField
            label="Weighing per bag"
            minutes={fields.weigh.minutes}
            seconds={fields.weigh.seconds}
            onChange={(m, s) => setFields({ ...fields, weigh: { minutes: m, seconds: s } })}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <DurationField
            label="Sorting per bag"
            minutes={fields.sort.minutes}
            seconds={fields.sort.seconds}
            onChange={(m, s) => setFields({ ...fields, sort: { minutes: m, seconds: s } })}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <DurationField
            label="Washing handling per bag"
            minutes={fields.wash.minutes}
            seconds={fields.wash.seconds}
            onChange={(m, s) => setFields({ ...fields, wash: { minutes: m, seconds: s } })}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <DurationField
            label="Drying handling per bag"
            minutes={fields.dry.minutes}
            seconds={fields.dry.seconds}
            onChange={(m, s) => setFields({ ...fields, dry: { minutes: m, seconds: s } })}
          />
        </Grid>
      </Grid>
      <TextField
        size="small"
        type="number"
        label="Reject if washing not started after X minutes"
        helperText="Legacy rule: no create-issue and start-cleaning does not occur within this many minutes after sorting/prep end."
        value={fields.rejectMinutes ?? 30}
        onChange={(e) => setFields({ ...fields, rejectMinutes: e.target.value })}
        inputProps={{ min: 1 }}
        sx={{ mb: 2, maxWidth: 360 }}
      />
      <TextField
        size="small"
        type="number"
        label="Default washing duration minutes"
        helperText="Expected IN_WASHING duration after LOAD_WASHER completes."
        value={fields.washingMinutes ?? 30}
        onChange={(e) => setFields({ ...fields, washingMinutes: e.target.value })}
        inputProps={{ min: 1 }}
        sx={{ mb: 2, maxWidth: 360 }}
      />
      <TextField
        size="small"
        type="number"
        label="Default drying duration minutes"
        helperText="Expected IN_DRYING duration after drying scan."
        value={fields.dryingMinutes ?? 40}
        onChange={(e) => setFields({ ...fields, dryingMinutes: e.target.value })}
        inputProps={{ min: 1 }}
        sx={{ mb: 2, maxWidth: 360 }}
      />
      <TextField
        size="small"
        type="number"
        label="Reject order if washing not started after create-issue within X minutes"
        helperText="ORDER_REJECTED_FULL: create-issue with no start-cleaning within this window."
        value={fields.rejectAfterIssueMinutes ?? 45}
        onChange={(e) => setFields({ ...fields, rejectAfterIssueMinutes: e.target.value })}
        inputProps={{ min: 1 }}
        sx={{ mb: 2, maxWidth: 420 }}
      />
      <Typography variant="body2" sx={{ mb: 2 }}>
        Total estimated per bag: {Math.floor(totalSec / 60)} min {totalSec % 60} sec
        {" "}({(totalSec / 60).toFixed(2)} minutes)
      </Typography>
      <Button variant="contained" onClick={save} disabled={loading}>
        Save processing settings
      </Button>
    </Paper>
  );
}
