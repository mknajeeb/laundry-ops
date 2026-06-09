import { Alert, Box, Chip, Stack, Typography } from "@mui/material";
import ShiftCountCard from "./ShiftCountCard";
import RushFilterChips from "./RushFilterChips";
import { formatDateTime } from "../../utils/foldingFormat";
import { syncStatusSubtext } from "../../utils/shiftMonitorHelpers";

function bucketValue(section, bucket, rushFilter) {
  if (rushFilter === "rush" && bucket.startsWith("nonrush")) return null;
  if (rushFilter === "non_rush" && bucket.startsWith("rush")) return null;
  return section[bucket] ?? 0;
}

function rushTotal(section, rushFilter) {
  if (rushFilter === "non_rush") return null;
  return section.rush_total ?? (section.rush_wf || 0) + (section.rush_hd || 0);
}

function nonRushTotal(section, rushFilter) {
  if (rushFilter === "rush") return null;
  return (section.nonrush_wf || 0) + (section.nonrush_hd || 0);
}

export default function ReadyForVendorSection({
  rfv,
  rfvLive,
  rfvSync,
  rfvSyncSub,
  rfvSyncStale,
  rushFilter,
  onRushFilterChange,
  onDrilldown,
  activeTag,
}) {
  const syncSub = rfvSyncSub || syncStatusSubtext({ sync_status: rfvSync, last_refreshed_at: rfv?.last_refreshed_at }, "Ready for Vendor Sync");

  return (
    <Box sx={{ mb: 2.5 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" flexWrap="wrap" gap={1} sx={{ mb: 1 }}>
        <Box>
          <Typography variant="h6" fontWeight={800}>
            Ready for Vendor
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Live queue from Ready for Vendor sync — selected ET date rush rules apply
          </Typography>
        </Box>
        {rfvLive && rfv.counts_add_up ? (
          <Chip size="small" color="success" variant="outlined" label="Reconciled ✓" />
        ) : rfvLive && rfv.counts_add_up === false ? (
          <Chip size="small" color="warning" label="Needs Review" />
        ) : null}
      </Stack>

      {!rfvLive ? (
        <Alert severity="warning" sx={{ mb: 1.5 }}>
          {rfv?.unavailable_reason || "Ready for Vendor: Sync stale"}
          {rfv?.last_refreshed_at ? ` · Last refresh: ${formatDateTime(rfv.last_refreshed_at)}` : ""}
        </Alert>
      ) : rfv.data_quality_warning ? (
        <Alert severity={rfv.zero_rows_success ? "info" : "error"} sx={{ mb: 1.5 }}>
          {rfv.data_quality_warning}
        </Alert>
      ) : rfvSyncStale ? (
        <Alert severity="warning" sx={{ mb: 1.5 }}>{syncSub}</Alert>
      ) : null}

      {rfvLive ? <RushFilterChips value={rushFilter} onChange={onRushFilterChange} sx={{ mb: 1 }} /> : null}

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "repeat(2, 1fr)", sm: "repeat(3, 1fr)", md: "repeat(4, 1fr)" },
          gap: 1,
        }}
      >
        {rfvLive ? (
          <>
            <ShiftCountCard
              label="Total Orders"
              value={rfv.total}
              sub={syncSub}
              onClick={() => onDrilldown("ready_for_vendor")}
              active={activeTag === "ready_for_vendor"}
            />
            <ShiftCountCard
              label="Rush"
              value={rushTotal(rfv, rushFilter)}
              onClick={() => onDrilldown("rfv_rush")}
              active={activeTag === "rfv_rush"}
              disabled={rushFilter === "non_rush"}
            />
            <ShiftCountCard
              label="Non-Rush"
              value={nonRushTotal(rfv, rushFilter)}
              onClick={() => onDrilldown("rfv_non_rush")}
              active={activeTag === "rfv_non_rush"}
              disabled={rushFilter === "rush"}
            />
            <ShiftCountCard
              label="Rush WF"
              value={bucketValue(rfv, "rush_wf", rushFilter)}
              onClick={() => onDrilldown("rfv_rush_wf")}
              active={activeTag === "rfv_rush_wf"}
              compact
            />
            <ShiftCountCard
              label="Rush HD"
              value={bucketValue(rfv, "rush_hd", rushFilter)}
              onClick={() => onDrilldown("rfv_rush_hd")}
              active={activeTag === "rfv_rush_hd"}
              compact
            />
            <ShiftCountCard
              label="Non-Rush WF"
              value={bucketValue(rfv, "nonrush_wf", rushFilter)}
              onClick={() => onDrilldown("rfv_nonrush_wf")}
              active={activeTag === "rfv_nonrush_wf"}
              compact
            />
            <ShiftCountCard
              label="Non-Rush HD"
              value={bucketValue(rfv, "nonrush_hd", rushFilter)}
              onClick={() => onDrilldown("rfv_nonrush_hd")}
              active={activeTag === "rfv_nonrush_hd"}
              compact
            />
            {rushFilter === "all" && (rfv.unknown_needs_review || 0) > 0 ? (
              <ShiftCountCard
                label="Unknown / Review"
                value={rfv.unknown_needs_review}
                onClick={() => onDrilldown("rfv_unknown_needs_review")}
                active={activeTag === "rfv_unknown_needs_review"}
                warn
                compact
              />
            ) : null}
          </>
        ) : (
          <ShiftCountCard label="Ready for Vendor" value="—" sub={rfv?.unavailable_reason || syncSub || "Refresh Both Syncs"} />
        )}
      </Box>
    </Box>
  );
}
