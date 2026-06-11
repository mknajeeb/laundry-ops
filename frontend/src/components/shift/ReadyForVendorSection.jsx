import { Alert, Box, Typography } from "@mui/material";
import DrilldownCardGrid from "./DrilldownCardGrid";

export default function ReadyForVendorSection({
  rfv,
  rfvSync,
  rushFilter,
  onDrilldown,
  activeTag,
}) {
  const syncFailed = rfvSync?.failed || rfvSync?.latest_failed;
  const syncStale = rfvSync?.stale && !rfv?.zero_rows_success && !rfvSync?.zero_rows_success;
  const showWarning = !rfv?.live || syncFailed || syncStale;

  const cards = rfv?.cards?.length
    ? rfv.cards
    : [
        { label: "Ready for Vendor Total", count: rfv?.total ?? 0, drilldown_tag: "ready_for_vendor", clickable: true, needs_review: false },
        { label: "Rush", count: (rfv?.rush_wf ?? 0) + (rfv?.rush_hd ?? 0), drilldown_tag: "rfv_rush", clickable: true, needs_review: false },
        { label: "Non-Rush", count: (rfv?.nonrush_wf ?? 0) + (rfv?.nonrush_hd ?? 0), drilldown_tag: "rfv_non_rush", clickable: true, needs_review: false },
        { label: "WF", count: (rfv?.rush_wf ?? 0) + (rfv?.nonrush_wf ?? 0), drilldown_tag: "rfv_wf", clickable: true, needs_review: false },
        { label: "HD", count: (rfv?.rush_hd ?? 0) + (rfv?.nonrush_hd ?? 0), drilldown_tag: "rfv_hd", clickable: true, needs_review: false },
      ];

  return (
    <Box sx={{ mb: 2.5 }}>
      <Typography variant="h6" fontWeight={800} sx={{ mb: 0.5 }}>
        Ready for Vendor
      </Typography>
      {showWarning ? (
        <Alert severity="warning" sx={{ mb: 1, py: 0.5 }}>
          {rfv?.unavailable_reason || rfvSync?.message || "Ready for Vendor sync unavailable — refresh syncs"}
        </Alert>
      ) : null}
      <DrilldownCardGrid cards={cards} onDrilldown={onDrilldown} activeTag={activeTag} rushFilter={rushFilter} />
    </Box>
  );
}
