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
import { PendingWhyBadge } from "./RushPendingWhyPanel";
import BagWeightSummary from "./BagWeightSummary";
import {
  computeDueStatus,
  DUE_STATUS_COLORS,
  formatEddDisplay,
  getBagWeightParts,
  getRowEddIso,
  isWfBag,
} from "../../utils/shiftMonitorHelpers";
import { formatLbs } from "../../utils/foldingFormat";
import { formatFriendlyEtWall, formatFriendlyScanTime, formatIsoEtWall } from "../../utils/rinseTimeFormat";

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

export default function ShiftBagRecordRow({
  row,
  variant = "pipeline",
  referenceDateEt,
  defaultOpen = false,
  friendlyTimeDisplay = false,
}) {
  const formatTime = friendlyTimeDisplay ? formatFriendlyEtWall : formatIsoEtWall;
  const formatScanTime = friendlyTimeDisplay ? formatFriendlyScanTime : undefined;
  const [open, setOpen] = useState(defaultOpen);
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
  const weightParts = getBagWeightParts(row);

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
          <BagWeightSummary row={row} />
          {row.exception_reason_label ? (
            <Typography
              variant="caption"
              fontWeight={700}
              color="warning.dark"
              display="block"
              sx={{ mt: 0.5 }}
            >
              Needs verification: {row.exception_reason_label}
            </Typography>
          ) : null}
          {variant === "at_vendor" ? <PendingWhyBadge row={row} /> : null}
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
                    value={formatTime(row.completion_time_et || row.completion_time)}
                  />
                  <DetailField
                    label="Sent to vendor"
                    value={formatTime(row.sent_to_vendor_time_et || row.sent_to_vendor_time)}
                  />
                  <DetailField label="EDD" value={row.estimated_delivery_date || row.date_clean} />
                  <DetailField label="Population source" value={row.population_source || row.inclusion_reason} />
                  <DetailField label="Presence run" value={row.presence_run_id || row.presence_source} />
                  <DetailField label="Investigation reason" value={row.exception_reason_label} />
                  <DetailField label="Reason" value={row.status_reason || row.reason || row.rush_reason} />
                  {isWfBag(row) ? (
                    <>
                      <DetailField
                        label="Pre-clean weight"
                        value={
                          weightParts.pre != null
                            ? `${formatLbs(weightParts.pre)} lbs · ${formatTime(row.pre_clean_weight_time_et || row.pre_clean_weight_time)}`
                            : null
                        }
                      />
                      <DetailField
                        label="Post-clean weight"
                        value={
                          weightParts.post != null
                            ? `${formatLbs(weightParts.post)} lbs · ${formatTime(row.post_clean_weight_time_et || row.post_clean_weight_time)}`
                            : null
                        }
                      />
                      <DetailField
                        label="Weight difference"
                        value={
                          weightParts.delta != null
                            ? `${formatLbs(weightParts.delta)} lbs`
                            : null
                        }
                      />
                    </>
                  ) : null}
                  {row.at_vendor_status === "Pending" && row.pending_why_label ? (
                    <DetailField label="Why pending" value={row.pending_why_label} />
                  ) : null}
                </Stack>
              ) : null}
              {tab === 1 ? (
                loading ? (
                  <Typography variant="body2" color="text.secondary">Loading scans…</Typography>
                ) : error ? (
                  <Typography variant="body2" color="error.main">{error}</Typography>
                ) : scans.length ? (
                  <Box sx={{ overflowX: "auto", maxWidth: "100%" }}>
                    <FoldingScanEventsTable
                      events={scans}
                      collapseUploadDuplicates
                      formatTime={formatScanTime}
                    />
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
