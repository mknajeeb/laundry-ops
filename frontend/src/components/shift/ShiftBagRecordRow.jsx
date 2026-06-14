import { useEffect, useState } from "react";
import {
  Box,
  Collapse,
  IconButton,
  Paper,
  Stack,
  Tab,
  Tabs,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { getFoldingPerformanceDetail } from "../../api";
import FoldingScanEventsTable from "../folding/FoldingScanEventsTable";
import {
  computeDueStatus,
  DUE_STATUS_COLORS,
  formatEddDisplay,
  formatEtDateTime,
  getRowEddIso,
} from "../../utils/shiftMonitorHelpers";

function DetailField({ label, value }) {
  if (value == null || value === "" || value === "—") return null;
  return (
    <Typography variant="body2">
      <Box component="span" fontWeight={600}>{label}: </Box>
      {value}
    </Typography>
  );
}

function DueStatusBlock({ row, referenceDateEt }) {
  const eddIso = getRowEddIso(row);
  const due = computeDueStatus(referenceDateEt, eddIso);
  return (
    <Box sx={{ mt: 0.75 }}>
      <Typography variant="body2" color="text.secondary">
        EDD: {formatEddDisplay(eddIso)}
      </Typography>
      <Typography variant="body2" fontWeight={700} sx={{ color: DUE_STATUS_COLORS[due.colorKey] || DUE_STATUS_COLORS.neutral }}>
        {due.label}
      </Typography>
    </Box>
  );
}

export default function ShiftBagRecordRow({ row, variant = "pipeline", referenceDateEt }) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState(0);
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const rushLabel = row.rush_label
    || (row.rush_bucket === "RUSH" ? "Rush" : row.rush_bucket === "NON_RUSH" ? "Non-Rush" : "Unknown Review");
  const serviceLabel = row.service_bucket || row.service_type || "—";
  const statusLabel = row.at_vendor_status
    || row.daily_classification
    || (row.facility_status
      ? row.facility_status.charAt(0).toUpperCase() + row.facility_status.slice(1)
      : "—");

  useEffect(() => {
    if (!open || variant === "rfv") {
      if (!open) {
        setDetail(null);
        setError(null);
      }
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    getFoldingPerformanceDetail(row.bag_id)
      .then((res) => {
        if (!cancelled) setDetail(res.data);
      })
      .catch((e) => {
        if (!cancelled) {
          setDetail(null);
          setError(e?.response?.data?.error || "Could not load scan events");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, row.bag_id, variant]);

  const scans = detail?.scan_events || detail?.scans || [];

  return (
    <Paper
      elevation={0}
      sx={{
        mb: 1,
        border: "1px solid",
        borderColor: "divider",
        borderRadius: 2,
        overflow: "hidden",
      }}
    >
      <Box
        sx={{
          p: 1.5,
          display: "flex",
          alignItems: "flex-start",
          gap: 1,
          cursor: "pointer",
        }}
        onClick={() => setOpen((v) => !v)}
      >
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="subtitle2" fontWeight={800} sx={{ wordBreak: "break-all" }}>
            {row.bag_id}
          </Typography>
          <Typography variant="body2" color="primary.main" fontWeight={600}>
            {row.customer_name || row.customer || "—"}
          </Typography>
          {referenceDateEt ? <DueStatusBlock row={row} referenceDateEt={referenceDateEt} /> : null}
          <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mt: 0.5 }}>
            <Typography variant="caption" fontWeight={700}>{rushLabel}</Typography>
            <Typography variant="caption" color="text.secondary">·</Typography>
            <Typography variant="caption" fontWeight={700}>{serviceLabel}</Typography>
            {variant !== "rfv" ? (
              <>
                <Typography variant="caption" color="text.secondary">·</Typography>
                <Typography variant="caption" fontWeight={700}>{statusLabel}</Typography>
              </>
            ) : null}
          </Stack>
        </Box>
        <IconButton
          size="small"
          aria-label={open ? "Collapse" : "Expand"}
          sx={{
            transform: open ? "rotate(180deg)" : "none",
            transition: "transform 0.2s",
          }}
        >
          <ExpandMoreIcon />
        </IconButton>
      </Box>
      <Collapse in={open}>
        <Box sx={{ px: 1.5, pb: 1.5, borderTop: "1px solid", borderColor: "divider", pt: 1 }}>
          {variant === "rfv" ? (
            <Stack spacing={0.5}>
              <DetailField label="Estimated delivery" value={row.estimated_delivery_raw} />
              <DetailField label="EDD (ET)" value={row.estimated_delivery_date_et} />
              <DetailField label="TODAY label" value={row.has_today_label ? "yes" : "no"} />
              <DetailField label="Presence source" value={row.presence_source || row.source} />
              <DetailField label="Reason" value={row.reason} />
            </Stack>
          ) : (
            <>
              <Tabs
                value={tab}
                onChange={(_, v) => setTab(v)}
                variant="fullWidth"
                sx={{ mb: 1, minHeight: 36 }}
              >
                <Tab label="Details" sx={{ minHeight: 36, py: 0.5 }} />
                <Tab label="Scans" sx={{ minHeight: 36, py: 0.5 }} />
              </Tabs>
              {tab === 0 ? (
                <Stack spacing={0.5}>
                  <DetailField label="Status" value={statusLabel} />
                  <DetailField label="Completion signal" value={row.completion_signal} />
                  <DetailField
                    label="Completion time"
                    value={row.completion_time_et || formatEtDateTime(row.completion_time)}
                  />
                  <DetailField
                    label="Sent to vendor"
                    value={row.sent_to_vendor_time_et || formatEtDateTime(row.sent_to_vendor_time)}
                  />
                  <DetailField label="EDD" value={row.estimated_delivery_date || row.date_clean} />
                  <DetailField label="Population source" value={row.population_source || row.inclusion_reason} />
                  <DetailField label="Presence run" value={row.presence_run_id || row.presence_source} />
                  <DetailField label="Reason" value={row.status_reason || row.reason || row.rush_reason} />
                </Stack>
              ) : null}
              {tab === 1 ? (
                loading ? (
                  <Typography variant="body2" color="text.secondary">Loading scans…</Typography>
                ) : error ? (
                  <Typography variant="body2" color="error.main">{error}</Typography>
                ) : scans.length ? (
                  <Box sx={{ overflowX: "auto", maxWidth: "100%" }}>
                    <FoldingScanEventsTable events={scans} collapseUploadDuplicates />
                  </Box>
                ) : (
                  <Typography variant="body2" color="text.secondary">No scan events for this bag.</Typography>
                )
              ) : null}
            </>
          )}
        </Box>
      </Collapse>
    </Paper>
  );
}
