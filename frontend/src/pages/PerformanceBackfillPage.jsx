import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
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
import { Link as RouterLink } from "react-router-dom";
import { getCleanerTicketPresenceSummary, recomputeFoldingPerformance, runCleanerTicketPresenceScrape } from "../api";
import { defaultWeekRange } from "../utils/foldingDateRange";

function SettingsNav() {
  const links = [
    { to: "/management/rinse-wf", label: "Management" },
    { to: "/performance/settings", label: "Settings" },
    { to: "/performance/user-mapping", label: "User mapping" },
    { to: "/performance/backfill", label: "Historical Repair / Admin Tools" },
  ];
  return (
    <Stack direction="row" spacing={2} flexWrap="wrap" sx={{ mb: 3 }}>
      {links.map(({ to, label }) => (
        <Typography key={to} component={RouterLink} to={to} variant="body2" sx={{ textDecoration: "none", fontWeight: 600 }}>
          {label}
        </Typography>
      ))}
    </Stack>
  );
}

export default function PerformanceBackfillPage() {
  const initialWeek = defaultWeekRange();
  const [recomputeStart, setRecomputeStart] = useState(initialWeek.start);
  const [recomputeEnd, setRecomputeEnd] = useState(initialWeek.end);
  const [dateField, setDateField] = useState("date_clean");
  const [recomputeSummary, setRecomputeSummary] = useState(null);
  const [recomputing, setRecomputing] = useState(false);
  const [message, setMessage] = useState({ type: "", text: "" });
  const [portalStatus, setPortalStatus] = useState("ready_for_vendor");
  const [presenceDryRun, setPresenceDryRun] = useState(true);
  const [markMissing, setMarkMissing] = useState(false);
  const [presenceRunning, setPresenceRunning] = useState(false);
  const [presenceResult, setPresenceResult] = useState(null);
  const [presenceSummary, setPresenceSummary] = useState(null);

  useEffect(() => {
    getCleanerTicketPresenceSummary()
      .then((res) => setPresenceSummary(res.data?.counts || []))
      .catch(() => setPresenceSummary(null));
  }, [presenceResult]);

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

  const runPresenceScrape = async (dryRun) => {
    try {
      setPresenceRunning(true);
      setPresenceResult(null);
      const res = await runCleanerTicketPresenceScrape({
        portal_status: portalStatus,
        dry_run: dryRun,
        mark_missing: markMissing,
      });
      setPresenceResult(res.data || null);
      setMessage({
        type: "success",
        text: dryRun ? "Portal presence dry run finished." : "Portal presence scrape applied.",
      });
    } catch (e) {
      setMessage({ type: "error", text: e?.response?.data?.error || "Portal presence scrape failed" });
    } finally {
      setPresenceRunning(false);
    }
  };

  return (
    <Box sx={{ p: { xs: 2, md: 3 }, maxWidth: 900, mx: "auto" }}>
      <Typography variant="h4" fontWeight={800} gutterBottom>Historical Repair / Admin Tools</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Historical repair and Rinse Sync admin. Not required for normal daily work.
      </Typography>
      <SettingsNav />
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
            {recomputing ? "Running…" : "Run historical repair"}
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

      <Typography variant="h6" fontWeight={700} sx={{ mt: 4, mb: 1 }}>
        Rinse Sync Admin
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Pull current Rinse portal Ready for Vendor / At Vendor data into the presence table.
        Does not update orders_staging. Requires admin + tenant flag enable_ready_for_vendor_scrape.
      </Typography>
      {presenceSummary?.length ? (
        <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mb: 2 }}>
          {presenceSummary.map((row) => (
            <Chip
              key={`${row.portal_status}-${row.active}`}
              size="small"
              label={`${row.portal_status} (active=${row.active}): ${row.cnt}`}
            />
          ))}
        </Stack>
      ) : null}
      <Paper sx={{ p: 2 }}>
        <Stack spacing={2}>
          <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems="flex-end" flexWrap="wrap">
            <FormControl size="small" sx={{ minWidth: 200 }}>
              <InputLabel>Portal status</InputLabel>
              <Select label="Portal status" value={portalStatus} onChange={(e) => setPortalStatus(e.target.value)}>
                <MenuItem value="ready_for_vendor">ready_for_vendor</MenuItem>
                <MenuItem value="at_vendor">at_vendor</MenuItem>
              </Select>
            </FormControl>
            <FormControlLabel
              control={<Switch checked={markMissing} onChange={(e) => setMarkMissing(e.target.checked)} />}
              label="Mark missing from scrape inactive"
            />
          </Stack>
          <Stack direction="row" spacing={1} flexWrap="wrap">
            <Button variant="outlined" onClick={() => runPresenceScrape(true)} disabled={presenceRunning}>
              {presenceRunning && presenceDryRun ? "Running…" : "Dry Run Rinse Sync"}
            </Button>
            <Button
              variant="contained"
              color="warning"
              onClick={() => {
                setPresenceDryRun(false);
                runPresenceScrape(false);
              }}
              disabled={presenceRunning}
            >
              {presenceRunning && !presenceDryRun ? "Applying…" : "Apply Rinse Sync"}
            </Button>
          </Stack>
          {presenceResult ? (
            <Stack spacing={1}>
              <Typography variant="body2"><strong>Source URL:</strong> {presenceResult.source_url || "—"}</Typography>
              <Stack direction="row" spacing={1} flexWrap="wrap">
                <Chip size="small" label={`Found: ${presenceResult.rows_found ?? 0}`} />
                <Chip size="small" label={`Insert: ${presenceResult.rows_inserted ?? 0}`} />
                <Chip size="small" label={`Update: ${presenceResult.rows_updated ?? 0}`} />
                <Chip size="small" label={`Unchanged: ${presenceResult.rows_unchanged ?? 0}`} />
                <Chip size="small" label={`Missing: ${presenceResult.rows_missing ?? 0}`} color="warning" />
                <Chip size="small" label={presenceResult.dry_run ? "Dry run" : "Applied"} color={presenceResult.dry_run ? "default" : "success"} />
              </Stack>
            </Stack>
          ) : null}
        </Stack>
      </Paper>
    </Box>
  );
}
