import { useCallback, useEffect, useState } from "react";
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
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
  CircularProgress,
  Divider,
} from "@mui/material";
import { Link as RouterLink } from "react-router-dom";
import { getRinseScheduledScrapeRuns, getRinseScheduledScrapeStatus } from "../api";
import { formatSystemDateTime } from "../utils/rinseTimeFormat";

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

function SyncStatusPanel({ title, sync }) {
  if (!sync) {
    return (
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Typography variant="subtitle1" fontWeight={700} gutterBottom>{title}</Typography>
        <Typography variant="body2" color="text.secondary">No runs recorded yet.</Typography>
      </Paper>
    );
  }
  const run = sync.latest_run || sync.last_success || sync.run || sync;
  const chipStatus = sync.status || run?.status || "unknown";
  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack direction="row" alignItems="center" spacing={1} mb={1} flexWrap="wrap">
        <Typography variant="subtitle1" fontWeight={700}>{title}</Typography>
        <Chip size="small" label={chipStatus} color={statusColor(chipStatus)} />
        {sync.enabled === false ? <Chip size="small" variant="outlined" label="disabled" /> : null}
      </Stack>
      <Row label="Latest attempt" value={formatSystemDateTime(sync.latest_attempt_at || sync.last_refreshed_at || run?.finished_at || run?.last_finished_at)} />
      <Row label="Last success" value={formatSystemDateTime(sync.last_success_at || sync.last_success?.finished_at)} />
      <Row label="Last refreshed" value={formatSystemDateTime(sync.last_refreshed_at || run?.finished_at || run?.last_finished_at)} />
      <Row label="Last started" value={formatSystemDateTime(run?.started_at || run?.scrape_started_at || sync.last_started_at)} />
      <Row label="Last finished" value={formatSystemDateTime(run?.finished_at || run?.scrape_finished_at || sync.last_finished_at)} />
      <Row label="Duration" value={run?.duration_label || sync.duration_label || (run?.duration_seconds != null ? `${run.duration_seconds}s` : "—")} />
      <Row label="Rows found" value={run?.rows_found ?? run?.portal_rows_count ?? run?.rows_imported} />
      <Row label="Active rows" value={sync.active_rows ?? run?.active_rows} />
      <Row label="Rows inserted" value={run?.rows_inserted} />
      <Row label="Rows updated" value={run?.rows_updated} />
      <Row label="Rows unchanged" value={run?.rows_unchanged} />
      <Row label="Pages visited" value={run?.pages_visited} />
      {(sync.error || sync.error_message || run?.error_message) ? (
        <Alert severity="error" sx={{ mt: 1 }}>{String(sync.error || sync.error_message || run?.error_message)}</Alert>
      ) : null}
      {sync.skipped_reason ? (
        <Alert severity="warning" sx={{ mt: 1 }}>{String(sync.skipped_reason)}</Alert>
      ) : null}
    </Paper>
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
      <Row label="Scrape started" value={formatSystemDateTime(run.scrape_started_at)} />
      <Row label="Scrape finished" value={formatSystemDateTime(run.scrape_finished_at)} />
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
      <Row label="Batch created" value={formatSystemDateTime(run.batch_created_at)} />
      <Row label="Batch confirmed" value={formatSystemDateTime(run.batch_confirmed_at)} />
      <Row label="Batch state" value={run.batch_state} />

      <Divider sx={{ my: 1.5 }} />

      <Row
        label="Data last updated at"
        value={formatSystemDateTime(run.data_last_updated_at)}
      />
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
        Uses batch confirmed time when available; otherwise scrape finished time. Not the batch created time.
      </Typography>

      {run.error_message ? <Alert severity="error" sx={{ mt: 1 }}>{run.error_message}</Alert> : null}
    </Paper>
  );
}

const RANGE_OPTIONS = [
  { value: "today", label: "Today" },
  { value: "yesterday", label: "Yesterday" },
  { value: "last_3_days", label: "Last 3 days" },
  { value: "custom", label: "Custom range" },
];

export default function RinseScheduledSyncPage() {
  const [data, setData] = useState(null);
  const [runsData, setRunsData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [range, setRange] = useState("today");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setError("");
      const params = { range };
      if (range === "custom") {
        if (!fromDate || !toDate) {
          setError("Select from and to dates for custom range.");
          setLoading(false);
          return;
        }
        params.from_date = fromDate;
        params.to_date = toDate;
      }
      const [statusRes, runsRes] = await Promise.all([
        getRinseScheduledScrapeStatus(),
        getRinseScheduledScrapeRuns(params),
      ]);
      setData(statusRes.data);
      setRunsData(runsRes.data);
    } catch (e) {
      setError(e?.response?.data?.error || "Failed to load sync status");
      setData(null);
      setRunsData(null);
    } finally {
      setLoading(false);
    }
  }, [range, fromDate, toDate]);

  useEffect(() => {
    load();
  }, [load]);

  const latest = data?.latest_run;
  const lastSuccess = data?.last_success;
  const runs = runsData?.runs || [];

  return (
    <Box sx={{ p: { xs: 2, md: 3 }, maxWidth: 1200, mx: "auto" }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2} flexWrap="wrap" useFlexGap>
        <Box>
          <Typography variant="h5" fontWeight={800}>Scheduled Rinse Sync</Typography>
          <Typography variant="body2" color="text.secondary">
            Run list uses America/New_York calendar dates. Batch headers are kept after raw row purge.
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
              {formatSystemDateTime(data.data_last_updated_at_et || data.data_last_updated_at) || "—"}
            </Typography>
            {data.timing_summary ? (
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                Last success: {data.timing_summary}
              </Typography>
            ) : null}
          </Paper>

          <SyncStatusPanel title="At Vendor Sync" sync={data.at_vendor_sync} />
          {data.ready_for_vendor_sync?.enabled ? (
            <SyncStatusPanel title="Ready for Vendor Sync" sync={data.ready_for_vendor_sync} />
          ) : null}

          <RunTimingPanel title="Latest At Vendor scrape run" run={latest} />
          {lastSuccess && lastSuccess.scrape_run_id !== latest?.scrape_run_id ? (
            <RunTimingPanel title="Last successful scrape" run={lastSuccess} />
          ) : null}

          <Paper variant="outlined" sx={{ p: 2 }}>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ sm: "center" }} mb={2}>
              <Typography variant="subtitle1" fontWeight={700} sx={{ flex: 1 }}>
                Today&apos;s Rinse Sync Runs
              </Typography>
              <FormControl size="small" sx={{ minWidth: 160 }}>
                <InputLabel>Date filter</InputLabel>
                <Select label="Date filter" value={range} onChange={(e) => setRange(e.target.value)}>
                  {RANGE_OPTIONS.map((o) => (
                    <MenuItem key={o.value} value={o.value}>{o.label}</MenuItem>
                  ))}
                </Select>
              </FormControl>
              {range === "custom" ? (
                <>
                  <TextField size="small" type="date" label="From" InputLabelProps={{ shrink: true }} value={fromDate} onChange={(e) => setFromDate(e.target.value)} />
                  <TextField size="small" type="date" label="To" InputLabelProps={{ shrink: true }} value={toDate} onChange={(e) => setToDate(e.target.value)} />
                </>
              ) : null}
            </Stack>
            {runsData ? (
              <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
                {runsData.from_date} – {runsData.to_date} ({runsData.timezone})
              </Typography>
            ) : null}
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Run ID</TableCell>
                    <TableCell>Status</TableCell>
                    <TableCell>Scrape started</TableCell>
                    <TableCell>Data available</TableCell>
                    <TableCell>Job finished</TableCell>
                    <TableCell>Duration</TableCell>
                    <TableCell align="right">Batch</TableCell>
                    <TableCell align="right">Portal</TableCell>
                    <TableCell align="right">Scan ev.</TableCell>
                    <TableCell align="right">Accepted</TableCell>
                    <TableCell align="right">Rejected</TableCell>
                    <TableCell align="right">Needs att.</TableCell>
                    <TableCell>Error</TableCell>
                    <TableCell align="right">Actions</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {runs.map((run) => (
                    <TableRow key={run.run_id || run.scrape_run_id} hover>
                      <TableCell>{run.run_id || run.scrape_run_id}</TableCell>
                      <TableCell>
                        <Chip size="small" label={run.status || run.scrape_status} color={statusColor(run.status || run.scrape_status)} />
                      </TableCell>
                      <TableCell>{formatSystemDateTime(run.scrape_started_at)}</TableCell>
                      <TableCell>{formatSystemDateTime(run.data_available_at)}</TableCell>
                      <TableCell>{formatSystemDateTime(run.job_finished_at || run.scrape_finished_at)}</TableCell>
                      <TableCell>{run.scrape_duration_label || run.scrape_duration_seconds || "—"}</TableCell>
                      <TableCell align="right">{run.imported_batch_id ?? "—"}</TableCell>
                      <TableCell align="right">{run.portal_rows_count ?? run.rows_imported ?? "—"}</TableCell>
                      <TableCell align="right">{run.scan_events_count ?? "—"}</TableCell>
                      <TableCell align="right">{run.accepted_rows ?? "—"}</TableCell>
                      <TableCell align="right">{run.rejected_rows ?? "—"}</TableCell>
                      <TableCell align="right">{run.needs_attention_rows ?? "—"}</TableCell>
                      <TableCell sx={{ maxWidth: 160 }}>
                        <Typography variant="caption" noWrap title={run.error_message || ""}>
                          {run.error_message || "—"}
                        </Typography>
                      </TableCell>
                      <TableCell align="right">
                        {run.imported_batch_id ? (
                          <Button size="small" component={RouterLink} to="/upload" state={{ batchId: run.imported_batch_id }}>
                            View batch
                          </Button>
                        ) : null}
                      </TableCell>
                    </TableRow>
                  ))}
                  {!runs.length ? (
                    <TableRow>
                      <TableCell colSpan={14}>
                        <Typography variant="body2" color="text.secondary">No runs in this date range.</Typography>
                      </TableCell>
                    </TableRow>
                  ) : null}
                </TableBody>
              </Table>
            </TableContainer>
          </Paper>

          <Paper variant="outlined" sx={{ p: 2 }}>
            <Typography variant="subtitle1" fontWeight={700} gutterBottom>Schedule</Typography>
            <Row label="Cron (UTC)" value={data.schedule_cron_utc} />
            <Row label="Interval" value={`${data.schedule_interval_minutes || 30} minutes`} />
            <Row label="Next run (estimate)" value={formatSystemDateTime(data.next_run_estimate_et || data.next_run_estimate_utc)} />
            <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: "block" }}>
              {data.timing_note || data.schedule_timezone_note}
            </Typography>
          </Paper>
        </Stack>
      ) : null}
    </Box>
  );
}
