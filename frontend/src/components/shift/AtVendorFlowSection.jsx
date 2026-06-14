import { useState } from "react";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Paper,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import MetricCardGrid from "./MetricCardGrid";
import RushFilterChips from "./RushFilterChips";
import ShiftCountCard from "./ShiftCountCard";
import { buildAtVendorHierarchy, buildAtVendorPortalSnapshot } from "../../utils/shiftMonitorHelpers";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

const MONITORING_COLLAPSE_THRESHOLD = 3;

/** At Vendor: Today's Workload (ET-day) vs Current Portal Snapshot (live presence). */
export default function AtVendorFlowSection({
  module,
  rushFilter,
  onRushChange,
  onDrilldown,
  activeKey,
}) {
  const av = module || {};
  const monitoringCount = av.completed_before_day_start_still_present_count ?? 0;
  const monitoringRows = av.completed_before_day_start_still_present_rows || [];
  const dailyReliable = av.daily_metrics_reliable !== false;
  const segment = rushFilter || "all";
  const monitoringCollapsedByDefault = monitoringCount > 0 && monitoringCount <= MONITORING_COLLAPSE_THRESHOLD;
  const [monitoringOpen, setMonitoringOpen] = useState(!monitoringCollapsedByDefault);

  const workloadSections = buildAtVendorHierarchy(av, segment);
  const portalSections = buildAtVendorPortalSnapshot(av);

  const handleCardClick = (card) => {
    if (!onDrilldown) return;
    onDrilldown({
      moduleKey: "at_vendor_flow",
      moduleTag: card.moduleTag,
      bucket: card.bucket,
      cardLabel: card.label,
      cardKey: card.key,
      expectedCount: card.count,
      moduleTitle: "At Vendor",
    });
  };

  return (
    <Box sx={{ mb: 3 }}>
      {!dailyReliable && av.daily_metrics_ui_warning ? (
        <Alert severity="warning" sx={{ mb: 2, py: 0.5 }}>
          {av.daily_metrics_ui_warning}
        </Alert>
      ) : null}

      <Paper
        elevation={0}
        sx={{
          mb: 2,
          borderRadius: 3,
          overflow: "hidden",
          border: "1px solid",
          borderColor: VEEWASH_DASHBOARD.primaryBlueBorder,
          bgcolor: "#ffffff",
          boxShadow: "0 4px 18px rgba(0, 60, 80, 0.1)",
        }}
      >
        <Box
          sx={{
            px: { xs: 1.5, sm: 2.25 },
            py: { xs: 1.25, sm: 1.5 },
            bgcolor: VEEWASH_DASHBOARD.workloadHeaderBg,
            color: "#fff",
          }}
        >
          <Typography variant="h6" fontWeight={800} sx={{ lineHeight: 1.2 }}>
            Today&apos;s Workload
          </Typography>
          <Typography variant="body2" sx={{ mt: 0.5, opacity: 0.92, maxWidth: 560 }}>
            Full ET-day workload including bags that already left the portal.
          </Typography>
        </Box>

        <Box sx={{ p: { xs: 1.5, sm: 2.25 } }}>
          <MetricCardGrid
            sections={workloadSections.filter((s) => s.key === "kpi")}
            onCardClick={handleCardClick}
            activeKey={activeKey}
          />

          <Box sx={{ my: 2 }}>
            <RushFilterChips value={segment} onChange={onRushChange} />
          </Box>

          <MetricCardGrid
            sections={workloadSections.filter((s) => s.key !== "kpi")}
            onCardClick={handleCardClick}
            activeKey={activeKey}
          />
        </Box>
      </Paper>

      <Paper
        elevation={0}
        sx={{
          p: { xs: 1.25, sm: 1.5 },
          mb: 1.5,
          borderRadius: 2.5,
          border: "1px solid",
          borderColor: VEEWASH_DASHBOARD.snapshotBorder,
          bgcolor: VEEWASH_DASHBOARD.snapshotBg,
          boxShadow: "none",
        }}
      >
        <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 0.35, color: VEEWASH_DASHBOARD.primaryBlueDark }}>
          Current Portal Snapshot
        </Typography>
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1.25 }}>
          Currently visible on Vendor Home.
          {av.portal_snapshot_scrape_at ? (
            <> · Vendor Home sync {String(av.portal_snapshot_scrape_at).replace("T", " ").slice(0, 19)}</>
          ) : null}
        </Typography>

        {av.portal_snapshot_presence_reconciliation?.active_at_vendor_presence_count != null
          && av.orders_at_veewash != null
          && av.portal_snapshot_presence_reconciliation.difference != null
          && av.portal_snapshot_presence_reconciliation.difference !== 0 ? (
          <Typography variant="caption" color="warning.main" display="block" sx={{ mb: 1 }}>
            Presence list ({av.portal_snapshot_presence_reconciliation.active_at_vendor_presence_count}) vs Vendor Home ({av.orders_at_veewash}): diff {av.portal_snapshot_presence_reconciliation.difference}
          </Typography>
        ) : null}

        <MetricCardGrid sections={portalSections} activeKey={activeKey} compact />
      </Paper>

      {monitoringCount > 0 ? (
        <Accordion
          expanded={monitoringOpen}
          onChange={(_, expanded) => setMonitoringOpen(expanded)}
          disableGutters
          elevation={0}
          sx={{
            borderRadius: "12px !important",
            border: "1px dashed",
            borderColor: VEEWASH_DASHBOARD.monitoringBorder,
            bgcolor: VEEWASH_DASHBOARD.monitoringBg,
            "&:before": { display: "none" },
          }}
        >
          <AccordionSummary
            expandIcon={<ExpandMoreIcon sx={{ color: VEEWASH_DASHBOARD.monitoringText }} />}
            sx={{ px: { xs: 1.5, sm: 2 }, minHeight: 48 }}
          >
            <Box>
              <Typography variant="body2" fontWeight={700} color={VEEWASH_DASHBOARD.monitoringText}>
                Monitoring Only · {monitoringCount}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                Excluded from Today&apos;s Workload
              </Typography>
            </Box>
          </AccordionSummary>
          <AccordionDetails sx={{ px: { xs: 1.5, sm: 2 }, pt: 0, pb: 1.5 }}>
            <Box sx={{ maxWidth: { xs: "100%", sm: 300 } }}>
              <ShiftCountCard
                label="Completed Earlier — Still at VeeWash"
                value={monitoringCount}
                sub={`${monitoringRows.length} record${monitoringRows.length === 1 ? "" : "s"}`}
                variant="monitoring"
                size="snapshot"
                onClick={() => onDrilldown?.({
                  moduleKey: "at_vendor_flow",
                  moduleTag: "completed_before_day_start_still_present",
                  cardLabel: "Completed Earlier — Still at VeeWash",
                  cardKey: "av_monitoring",
                  expectedCount: monitoringCount,
                  moduleTitle: "At Vendor (Monitoring)",
                })}
                active={activeKey === "av_monitoring"}
              />
            </Box>
          </AccordionDetails>
        </Accordion>
      ) : null}

      {av.changed_to_rush > 0 ? (
        <Box sx={{ mt: 1.5 }}>
          <ShiftCountCard
            label="Changed to Rush"
            value={av.changed_to_rush}
            onClick={() => onDrilldown?.({
              moduleKey: "at_vendor_flow",
              moduleTag: "mod_at_vendor_changed_rush",
              cardLabel: "Changed to Rush",
              cardKey: "av_changed_rush",
              expectedCount: av.changed_to_rush,
              moduleTitle: "At Vendor",
            })}
            active={activeKey === "av_changed_rush"}
            warn
          />
        </Box>
      ) : null}
    </Box>
  );
}
