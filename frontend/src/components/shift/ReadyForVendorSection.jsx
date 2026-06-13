import { Alert, Box, Typography } from "@mui/material";
import DrilldownCardGrid from "./DrilldownCardGrid";
import RushFilterChips from "./RushFilterChips";

function cardsForRushFilter(cards, rushFilter) {
  if (!cards?.length) return [];
  if (rushFilter === "all") {
    return cards.filter((c) => c.level === 1);
  }
  if (rushFilter === "rush") {
    const rushTotal = cards.find((c) => c.drilldown_tag === "rfv_rush" || c.label === "Rush");
    const children = cards.filter((c) => c.parent === "rush" || String(c.drilldown_tag || "").startsWith("rfv_rush"));
    return rushTotal ? [rushTotal, ...children] : children;
  }
  if (rushFilter === "non_rush") {
    const nonTotal = cards.find((c) => c.drilldown_tag === "rfv_non_rush" || c.label === "Non-Rush");
    const children = cards.filter((c) => c.parent === "non_rush" || String(c.drilldown_tag || "").includes("nonrush"));
    return nonTotal ? [nonTotal, ...children] : children;
  }
  return cards.filter((c) => c.level === 1);
}

export default function ReadyForVendorSection({
  rfv,
  rfvSync,
  rushFilter,
  onRushChange,
  onDrilldown,
  activeTag,
}) {
  const syncFailed = rfvSync?.failed || rfvSync?.latest_failed;
  const syncStale = rfvSync?.stale && !rfv?.zero_rows_success && !rfvSync?.zero_rows_success;
  const showWarning = !rfv?.live || syncFailed || syncStale;

  const cards = rfv?.cards?.length
    ? rfv.cards
    : [
        { label: "Ready for Vendor Total", count: rfv?.total ?? 0, drilldown_tag: "ready_for_vendor", clickable: true, level: 1 },
        { label: "Rush", count: rfv?.rush_total ?? 0, drilldown_tag: "rfv_rush", clickable: true, level: 1 },
        { label: "Non-Rush", count: rfv?.nonrush_total ?? 0, drilldown_tag: "rfv_non_rush", clickable: true, level: 1 },
      ];

  const visible = cardsForRushFilter(cards, rushFilter || "all");

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
      {onRushChange ? (
        <Box sx={{ mb: 1 }}>
          <Typography variant="caption" fontWeight={700} display="block" sx={{ mb: 0.25 }}>
            Rush
          </Typography>
          <RushFilterChips value={rushFilter} onChange={onRushChange} />
        </Box>
      ) : null}
      <DrilldownCardGrid cards={visible} onDrilldown={onDrilldown} activeTag={activeTag} rushFilter={rushFilter} />
    </Box>
  );
}
