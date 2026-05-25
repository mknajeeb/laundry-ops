import { useMemo, useState } from "react";
import {
  Alert,
  Box,
  Chip,
  Divider,
  Drawer,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tabs,
  Typography,
} from "@mui/material";
import { scanEventPurpose } from "../folding/FoldingScanEventsTable";
import { formatRinseScanTime, formatSystemDateTime, sortRinseScanEvents } from "../../utils/rinseTimeFormat";
import { formatDateTime, formatFoldingDuration, formatLbs, formatRate } from "../../utils/foldingFormat";
import { foldingExceptionLabel } from "../../utils/foldingExceptionLabels";

function FieldRow({ label, value }) {
  return (
    <Stack direction="row" spacing={1} sx={{ py: 0.25 }}>
      <Typography variant="body2" color="text.secondary" sx={{ minWidth: 160 }}>
        {label}
      </Typography>
      <Typography variant="body2" sx={{ wordBreak: "break-word" }}>
        {value ?? "—"}
      </Typography>
    </Stack>
  );
}

function SummaryTab({ detail }) {
  const s = detail?.registry_summary || detail?.registry || {};
  return (
    <Box>
      <FieldRow label="Bag ID" value={s.bag_id || detail?.bag_id} />
      <FieldRow label="Customer" value={s.customer ?? s.name_clean} />
      <FieldRow label="Completion status" value={s.completion_status} />
      <FieldRow label="Completion reason" value={s.completion_reason} />
      <FieldRow label="Completed at" value={formatDateTime(s.completed_at)} />
      <FieldRow label="Cleaning date" value={s.date_clean} />
      <FieldRow label="Weight" value={s.weight != null ? formatLbs(s.weight) : s.weight_num != null ? formatLbs(s.weight_num) : null} />
      <FieldRow label="Service / rush" value={[s.service_type, s.rush_type].filter(Boolean).join(" · ") || "—"} />
      <FieldRow label="Last upload batch" value={s.last_upload_batch_id} />
      <FieldRow label="Last staging order" value={s.last_staging_order_id} />
    </Box>
  );
}

function SectionLoadError({ sectionErrors, name }) {
  const msg = sectionErrors?.[name];
  if (!msg) return null;
  return (
    <Alert severity="warning" sx={{ mb: 1 }} variant="outlined">
      Could not load this section: {msg}
    </Alert>
  );
}

function UploadsTab({ uploadHistory, sectionErrors }) {
  const rows = uploadHistory || [];
  if (!rows.length) {
    return (
      <>
        <SectionLoadError sectionErrors={sectionErrors} name="upload_history" />
        <Typography variant="body2" color="text.secondary">No upload batch history for this bag.</Typography>
      </>
    );
  }
  return (
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>Batch</TableCell>
          <TableCell>State</TableCell>
          <TableCell>Batch date</TableCell>
          <TableCell>Row status</TableCell>
          <TableCell>Reason</TableCell>
          <TableCell>Created</TableCell>
          <TableCell>Confirmed</TableCell>
          <TableCell>Purged</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {rows.map((u) => (
          <TableRow key={u.upload_batch_id}>
            <TableCell>#{u.upload_batch_id}</TableCell>
            <TableCell>{u.batch_state || "—"}</TableCell>
            <TableCell>{u.batch_date || "—"}</TableCell>
            <TableCell>{u.row_status || (u.row_purged ? "—" : "—")}</TableCell>
            <TableCell>{u.reason || "—"}</TableCell>
            <TableCell>{formatDateTime(u.row_created_at || u.batch_created_at)}</TableCell>
            <TableCell>{formatDateTime(u.confirmed_at)}</TableCell>
            <TableCell>
              {u.raw_rows_purged ? (
                <Chip size="small" label="Raw purged" color="warning" variant="outlined" />
              ) : (
                "—"
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function UploadPurgedNotes({ uploadHistory }) {
  const notes = (uploadHistory || []).filter((u) => u.purged_message);
  if (!notes.length) return null;
  return (
    <Stack spacing={1} sx={{ mt: 2 }}>
      {notes.map((u) => (
        <Alert key={u.upload_batch_id} severity="info" variant="outlined">
          Batch #{u.upload_batch_id}: {u.purged_message}
        </Alert>
      ))}
    </Stack>
  );
}

function CheckoutTab({ stagingHistory, stagingActive, sectionErrors }) {
  const rows = stagingHistory || [];
  if (!rows.length && !stagingActive) {
    return (
      <>
        <SectionLoadError sectionErrors={sectionErrors} name="staging_history" />
        <Typography variant="body2" color="text.secondary">No checkout / staging rows for this bag.</Typography>
      </>
    );
  }
  return (
    <>
      {stagingActive ? (
        <Alert severity="info" sx={{ mb: 2 }}>
          Active in checkout — staging #{stagingActive.id}
        </Alert>
      ) : null}
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>ID</TableCell>
            <TableCell>Active</TableCell>
            <TableCell>Status</TableCell>
            <TableCell>Checkout</TableCell>
            <TableCell>Logistics</TableCell>
            <TableCell>Processing</TableCell>
            <TableCell>Rush</TableCell>
            <TableCell>Created</TableCell>
            <TableCell>Updated</TableCell>
            <TableCell>Checked out</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((s) => (
            <TableRow key={s.id}>
              <TableCell>{s.id}</TableCell>
              <TableCell>{s.active_in_checkout ? "Yes" : "No"}</TableCell>
              <TableCell>{s.status || "—"}</TableCell>
              <TableCell>{s.checkout_status || "—"}</TableCell>
              <TableCell>{s.logistics_status || "—"}</TableCell>
              <TableCell>{s.processing_status || "—"}</TableCell>
              <TableCell>{s.rush_type || "—"}</TableCell>
              <TableCell>{formatDateTime(s.created_at)}</TableCell>
              <TableCell>{formatDateTime(s.updated_at)}</TableCell>
              <TableCell>{formatDateTime(s.checked_out_at || s.closed_at)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </>
  );
}

function ScanTimelineTab({ scanEvents, sectionErrors }) {
  const sorted = useMemo(() => sortRinseScanEvents(scanEvents), [scanEvents]);
  if (!sorted.length) {
    return (
      <>
        <SectionLoadError sectionErrors={sectionErrors} name="scan_events" />
        <Typography variant="body2" color="text.secondary">
          No scan events found for this bag.
        </Typography>
      </>
    );
  }
  return (
    <Box>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
        rinse_bag_scan_events in true event order.
      </Typography>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>#</TableCell>
            <TableCell>Index</TableCell>
            <TableCell>Event</TableCell>
            <TableCell>Rack</TableCell>
            <TableCell>User</TableCell>
            <TableCell>Raw time</TableCell>
            <TableCell>Display (ET)</TableCell>
            <TableCell>Source batch</TableCell>
            <TableCell>Recorded</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {sorted.map((ev, idx) => (
            <TableRow key={ev.id ?? `${ev.scan_index}-${idx}`}>
              <TableCell>{idx + 1}</TableCell>
              <TableCell>{ev.scan_index ?? "—"}</TableCell>
              <TableCell>{scanEventPurpose(ev)}</TableCell>
              <TableCell>{ev.rack || "—"}</TableCell>
              <TableCell>{ev.user_name || "—"}</TableCell>
              <TableCell>{ev.time_scanned_raw || "—"}</TableCell>
              <TableCell>{formatRinseScanTime(ev)}</TableCell>
              <TableCell>{ev.source_upload_batch_id ? `#${ev.source_upload_batch_id}` : "—"}</TableCell>
              <TableCell>{formatDateTime(ev.created_at)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box>
  );
}

function FoldingTab({ folding, sectionErrors }) {
  if (!folding) {
    return (
      <>
        <SectionLoadError sectionErrors={sectionErrors} name="folding" />
        <SectionLoadError sectionErrors={sectionErrors} name="folding_performance" />
        <Typography variant="body2" color="text.secondary">No folding record found for this bag.</Typography>
      </>
    );
  }
  const perf = folding.performance || {};
  return (
    <Box>
      <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mb: 2 }}>
        <Chip label={folding.status || perf.status || "—"} size="small" />
        {folding.exception_code ? (
          <Chip label={folding.exception_code} size="small" color={folding.warning_only ? "warning" : "error"} variant="outlined" />
        ) : null}
        <Chip
          label={folding.included_in_scoring ? "In scoring" : "Not in scoring"}
          size="small"
          color={folding.included_in_scoring ? "success" : "default"}
          variant="outlined"
        />
        {folding.excluded_from_performance ? (
          <Chip label="Excluded" size="small" color="warning" />
        ) : null}
      </Stack>
      {folding.plain_english_reason ? (
        <Alert severity={folding.warning_only ? "warning" : "info"} sx={{ mb: 2 }}>
          {folding.plain_english_reason}
        </Alert>
      ) : folding.exception_code ? (
        <Alert severity="info" sx={{ mb: 2 }}>{foldingExceptionLabel(folding.exception_code)}</Alert>
      ) : null}
      <FieldRow label="Assigned user" value={perf.assigned_user_name} />
      <FieldRow label="Folding start" value={formatDateTime(perf.folding_start_at)} />
      <FieldRow label="Folding end" value={formatDateTime(perf.folding_end_at)} />
      <FieldRow label="Duration" value={formatFoldingDuration(perf.duration_seconds)} />
      <FieldRow label="Weight" value={formatLbs(folding.weight_lbs ?? perf.weight_lbs)} />
      <FieldRow label="Lbs/hr" value={formatRate(folding.lbs_per_hour)} />
      <FieldRow label="Bags/hr" value={formatRate(folding.bags_per_hour)} />
      <FieldRow label="Folding scans" value={folding.folding_scan_count ?? perf.folding_scan_count} />
      <FieldRow label="Clean scans (after fold)" value={folding.clean_scan_count ?? perf.clean_scan_count} />
      {folding.admin_notes ? <FieldRow label="Admin notes" value={folding.admin_notes} /> : null}
      {(folding.scans_used_for_calculation || []).length ? (
        <>
          <Typography variant="subtitle2" fontWeight={700} sx={{ mt: 2, mb: 1 }}>
            Scans used for calculation
          </Typography>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>ID</TableCell>
                <TableCell>Index</TableCell>
                <TableCell>Rack</TableCell>
                <TableCell>User</TableCell>
                <TableCell>Time</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {folding.scans_used_for_calculation.map((ev) => (
                <TableRow key={ev.id}>
                  <TableCell>{ev.id}</TableCell>
                  <TableCell>{ev.scan_index}</TableCell>
                  <TableCell>{ev.rack}</TableCell>
                  <TableCell>{ev.user_name}</TableCell>
                  <TableCell>{ev.time_scanned_raw || formatDateTime(ev.scanned_at_parsed)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </>
      ) : null}
      {(folding.override_history || []).length ? (
        <>
          <Typography variant="subtitle2" fontWeight={700} sx={{ mt: 2, mb: 1 }}>
            Override history
          </Typography>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>When</TableCell>
                <TableCell>Field</TableCell>
                <TableCell>Old</TableCell>
                <TableCell>New</TableCell>
                <TableCell>Notes</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {folding.override_history.map((o) => (
                <TableRow key={o.id}>
                  <TableCell>{formatDateTime(o.created_at)}</TableCell>
                  <TableCell>{o.field_name}</TableCell>
                  <TableCell>{o.old_value ?? "—"}</TableCell>
                  <TableCell>{o.new_value ?? "—"}</TableCell>
                  <TableCell>{o.notes || "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </>
      ) : null}
    </Box>
  );
}

function SourceTab({ scrapeSources, scheduledScrapeStatus, sectionErrors }) {
  const sources = scrapeSources || [];
  return (
    <Box>
      <SectionLoadError sectionErrors={sectionErrors} name="scrape_sources" />
      <SectionLoadError sectionErrors={sectionErrors} name="scheduled_scrape_status" />
      {sources.length ? (
        sources.map((src) => (
          <Box key={src.upload_batch_id ?? src.scrape_run_id ?? src.id} sx={{ mb: 2 }}>
            <Typography variant="subtitle2" fontWeight={700}>
              Scrape run #{src.scrape_run_id ?? src.id} → batch #{src.upload_batch_id ?? src.imported_batch_id}
            </Typography>
            <FieldRow label="Status" value={src.scrape_status ?? src.status} />
            <FieldRow label="Started" value={formatDateTime(src.scrape_started_at ?? src.started_at)} />
            <FieldRow label="Finished" value={formatDateTime(src.scrape_finished_at ?? src.finished_at)} />
            <FieldRow label="Portal rows" value={src.portal_rows_count ?? src.rows_imported} />
            <FieldRow label="Scan events" value={src.scan_events_count} />
            {src.error_message ? (
              <Alert severity="error" sx={{ mt: 1 }}>{src.error_message}</Alert>
            ) : null}
            <Divider sx={{ mt: 1 }} />
          </Box>
        ))
      ) : (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          No linked rinse_scrape_runs for upload batches on this bag.
        </Typography>
      )}
      {scheduledScrapeStatus?.data_last_updated_at_et ? (
        <Typography variant="caption" color="text.secondary">
          Org data last updated: {formatSystemDateTime(scheduledScrapeStatus.data_last_updated_at_et)}
        </Typography>
      ) : null}
    </Box>
  );
}

const TAB_IDS = ["summary", "uploads", "checkout", "scans", "folding", "source"];

export default function OrderSearchDetailDrawer({ open, onClose, detail, bagId, loading, detailError }) {
  const [tab, setTab] = useState(0);

  const panels = useMemo(() => {
    if (!detail) return null;
    return {
      summary: <SummaryTab detail={detail} />,
      uploads: (
        <>
          <UploadsTab uploadHistory={detail.upload_history} sectionErrors={detail.section_errors} />
          <UploadPurgedNotes uploadHistory={detail.upload_history} />
        </>
      ),
      checkout: (
        <CheckoutTab
          stagingHistory={detail.staging_history}
          stagingActive={detail.staging_active || detail.staging}
          sectionErrors={detail.section_errors}
        />
      ),
      scans: <ScanTimelineTab scanEvents={detail.scan_events} sectionErrors={detail.section_errors} />,
      folding: <FoldingTab folding={detail.folding} sectionErrors={detail.section_errors} />,
      source: (
        <SourceTab
          scrapeSources={detail.scrape_sources}
          scheduledScrapeStatus={detail.scheduled_scrape_status}
          sectionErrors={detail.section_errors}
        />
      ),
    };
  }, [detail]);

  const handleClose = () => {
    setTab(0);
    onClose?.();
  };

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={handleClose}
      PaperProps={{ sx: { width: { xs: "100%", sm: 520, md: 640 }, p: 2 } }}
    >
      <Typography variant="h6" fontWeight={800} gutterBottom>
        {detail?.bag_id || bagId || "Bag detail"}
      </Typography>
      {detailError ? (
        <Alert severity="error" sx={{ mb: 2 }}>
          {detailError}
        </Alert>
      ) : null}
      {detail?.section_errors?._request ? (
        <Alert severity="error" sx={{ mb: 2 }}>
          {detail.section_errors._request}
        </Alert>
      ) : null}
      {loading ? (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>Loading detail…</Typography>
      ) : null}
      {detail ? (
        <>
          <Tabs
            value={tab}
            onChange={(_, v) => setTab(v)}
            variant="scrollable"
            scrollButtons="auto"
            sx={{ mb: 2, borderBottom: 1, borderColor: "divider" }}
          >
            <Tab label="Summary" />
            <Tab label="Uploads" />
            <Tab label="Checkout" />
            <Tab label={`Scans (${(detail.scan_events || []).length})`} />
            <Tab label="Folding" />
            <Tab label="Source" />
          </Tabs>
          <Box sx={{ overflow: "auto", maxHeight: "calc(100vh - 140px)" }}>
            {panels[TAB_IDS[tab]]}
          </Box>
        </>
      ) : null}
    </Drawer>
  );
}
