import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Chip,
  Paper,
  Stack,
  Typography,
  Button,
  CircularProgress,
  Divider,
} from "@mui/material";
import { getRinseScheduledScrapeStatus } from "../api";
import { formatRinseApiDateTime } from "../utils/rinseTimeFormat";

function statusColor(status) {
  const s = String(status || "").toLowerCase();
  if (s === "success") return "success";
  if (s === "running") return "info";
  if (s === "failed") return "error";
  if (s === "skipped" || s === "needs_attention") return "warning";
  return "default";
}

function Row({ label, value }) {
  return (
    <Stack direction="row" justifyContent="space-between" spacing={2} sx={{ py: 0.5 }}>
      <Typography variant="body2" color="text.secondary">{label}</Typography>
      <Typography variant="body2" fontWeight={600} sx={{ textAlign: "right", maxWidth: "65%" }}>
        {value ?? "—"}
      </Typography>
    </Stack>
  );
}

function RunTimingPanel({ title, run }) {
  if (!run) {
    return (
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Typography variant="subtitle1" fontWeight={700} gutterBottom>{title}</Typography>
        <Typography variant="body2" color="text.secondary">No scrape runs recorded yet.</Typography>
      </Paper>
    );
  }

  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack direction="row" alignItems="center" spacing={1} mb={1} flexWrap="wrap">
        <Typography variant="subtitle1" fontWeight={700}>{title}</Typography>
        <Chip size="small" label={run.scrape_status || run.status || "unknown"} color={statusColor(run.scrape_status || run.status)} />
        {run.imported_batch_id ? (
          <Chip size="small" variant="outlined" label={`Batch #${run.imported_batch_id}`} />
        ) : null}
      </Stack>

      {run.timing_summary ? (
        <Typography variant="body1" fontWeight={600} sx={{ mb: 1.5 }}>
          {run.timing_summary}
        </Typography>
      ) : null}

      <Typography variant="overline" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
        Scraper job
      </Typography>
      <Row label="Scrape started" value={formatRinseApiDateTime(run.scrape_started_at)} />
      <Row label="Scrape finished" value={formatRinseApiDateTime(run.scrape_finished_at)} />
      <Row
        label="Duration"
        value={run.scrape_duration_label || (run.scrape_duration_seconds != null ? `${run.scrape_duration_seconds}s` : "—")}
      />
      <Row label="Rows imported (portal)" value={run.rows_imported ?? run.portal_rows_count} />
      <Row label="Scan-event rows" value={run.scan_events_count} />

      <Divider sx={{ my: 1.5 }} />

      <Typography variant="overline" color="text.secondary" display="block">
        Upload batch (import)
      </Typography>
      <Row label="Imported batch ID" value={run.imported_batch_id} />
      <Row label="Batch created" value={formatRinseApiDateTime(run.batch_created_at)} />
      <Row label="Batch confirmed" value={formatRinseApiDateTime(run.batch_confirmed_at)} />
      <Row label="Batch state" value={run.batch_state} />

      <Divider sx={{ my: 1.5 }} />

      <Row
        label="Data last updated at"
        value={formatRinseApiDateTime(run.data_last_updated_at)}
      />
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
        Uses batch confirmed time when available; otherwise scrape finished time. Not the batch created time.
      </Typography>

      {run.error_message ? <Alert severity="error" sx={{ mt: 1 }}>{run.error_message}</Alert> : null}
    </Paper>
  );
}

export default function RinseScheduledSyncPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = async () => {
    try {
      setLoading(true);
      setError("");
      const res = await getRinseScheduledScrapeStatus();
      setData(res.data);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to load sync status");
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const latest = data?.latest_run;
  const lastSuccess = data?.last_success;

  return (
    <Box sx={{ p: { xs: 2, md: 3 }, maxWidth: 720, mx: "auto" }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2}>
        <Box>
          <Typography variant="h5" fontWeight={800}>Scheduled Rinse Sync</Typography>
          <Typography variant="body2" color="text.secondary">
            Scrape start/finish are job times. Batch created is when the draft import landed. Data last updated is when confirm/finalize finished.
          </Typography>
        </Box>
        <Button size="small" variant="outlined" onClick={load} disabled={loading}>Refresh</Button>
      </Stack>

      {error ? <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert> : null}
      {loading && !data ? <CircularProgress size={28} /> : null}

      {data ? (
        <Stack spacing={2}>
          <Paper variant="outlined" sx={{ p: 2 }}>
            <Stack direction="row" alignItems="center" spacing={1} mb={1}>
              <Typography variant="subtitle1" fontWeight={700}>Data last updated (org)</Typography>
              {data.currently_running ? <Chip size="small" label="Scrape running" color="info" /> : null}
            </Stack>
            <Typography variant="h6">
              {formatRinseApiDateTime(data.data_last_updated_at_et || data.data_last_updated_at) || "—"}
            </Typography>
            {data.timing_summary ? (
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                Last success: {data.timing_summary}
              </Typography>
            ) : null}
          </Paper>

          <RunTimingPanel title="Latest scrape run" run={latest} />
          {lastSuccess && lastSuccess.scrape_run_id !== latest?.scrape_run_id ? (
            <RunTimingPanel title="Last successful scrape" run={lastSuccess} />
          ) : null}

          <Paper variant="outlined" sx={{ p: 2 }}>
            <Typography variant="subtitle1" fontWeight={700} gutterBottom>Schedule</Typography>
            <Row label="Cron (UTC)" value={data.schedule_cron_utc} />
            <Row label="Interval" value={`${data.schedule_interval_minutes || 30} minutes`} />
            <Row label="Next run (estimate)" value={formatRinseApiDateTime(data.next_run_estimate_et || data.next_run_estimate_utc)} />
            <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: "block" }}>
              {data.timing_note || data.schedule_timezone_note}
            </Typography>
          </Paper>
        </Stack>
      ) : null}
    </Box>
  );
}
