import { Box, Typography } from "@mui/material";
import { formatEtDateTime } from "../../utils/shiftMonitorHelpers";

function fmtTime(iso, etLabel) {
  if (etLabel) return etLabel;
  if (!iso) return "—";
  return formatEtDateTime(iso);
}

function FreshnessRow({ label, value, note }) {
  return (
    <Typography variant="caption" color="text.secondary" display="block" sx={{ lineHeight: 1.45 }}>
      <Box component="span" fontWeight={700} color="text.primary">{label}: </Box>
      {value}
      {note ? (
        <Box component="span" color="warning.main" sx={{ ml: 0.5 }}>
          ({note})
        </Box>
      ) : null}
    </Typography>
  );
}

/** Scrape freshness lines for sync cards (started / pulled / updated / duration / rows). */
export default function SyncFreshnessDetails({ freshness, compact = false }) {
  const f = freshness || {};
  if (!f.scrape_started_at && !f.portal_pulled_at && !f.data_updated_at && f.rows_found == null) {
    return null;
  }

  const pulledNote = f.portal_pull_unavailable ? (f.portal_pull_note || "Portal pull time unavailable") : null;
  const pulledValue = f.portal_pull_unavailable
    ? fmtTime(f.scrape_started_at || f.data_updated_at, f.scrape_started_at_et || f.data_updated_at_et)
    : fmtTime(f.portal_pulled_at, f.portal_pulled_at_et);

  if (compact) {
    return (
      <Box sx={{ mt: 0.25 }}>
        <Typography variant="caption" color="text.secondary" display="block">
          Pulled: {pulledValue}
          {pulledNote ? ` (${pulledNote})` : ""}
        </Typography>
        <Typography variant="caption" color="text.secondary" display="block">
          Updated: {fmtTime(f.data_updated_at, f.data_updated_at_et)}
        </Typography>
      </Box>
    );
  }

  return (
    <Box sx={{ mt: 0.5 }}>
      <FreshnessRow
        label="Scrape started"
        value={fmtTime(f.scrape_started_at, f.scrape_started_at_et)}
      />
      <FreshnessRow label="Portal data pulled" value={pulledValue} note={pulledNote} />
      <FreshnessRow
        label="Data updated"
        value={fmtTime(f.data_updated_at, f.data_updated_at_et)}
      />
      <FreshnessRow label="Duration" value={f.duration_label || (f.duration_seconds != null ? `${f.duration_seconds}s` : "—")} />
      <FreshnessRow label="Rows found" value={f.rows_found != null ? String(f.rows_found) : "—"} />
      {f.scan_events_count != null ? (
        <FreshnessRow label="Scan-event rows" value={String(f.scan_events_count)} />
      ) : null}
      {f.imported_batch_id != null ? (
        <FreshnessRow label="Import batch" value={String(f.imported_batch_id)} />
      ) : null}
    </Box>
  );
}
