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
import WorkloadReportStats from "./WorkloadReportStats";
import {
  buildAtVendorHierarchy,
  buildAtVendorPortalSnapshot,
  buildWorkloadReportStats,
} from "../../utils/shiftMonitorHelpers";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

const MONITORING_COLLAPSE_THRESHOLD = 3;

/** At Vendor workload — Operations Mode (today) vs Reporting Mode (historical / ranges). */
export default function AtVendorFlowSection({
  module,
  rushFilter,
  onRushChange,
  onDrilldown,
  activeKey,
  isLiveView = true,
  isOperationsMode: isOperationsModeProp,
}) {
  const isOperationsMode = isOperationsModeProp ?? isLiveView;
  const av = module || {};
  const monitoringCount = av.completed_before_day_start_still_present_count ?? 0;
  const monitoringRows = av.completed_before_day_start_still_present_rows || [];
  const dailyReliable = av.daily_metrics_reliable !== false;
  const segment = rushFilter || "all";
  const monitoringCollapsedByDefault = monitoringCount > 0 && monitoringCount <= MONITORING_COLLAPSE_THRESHOLD;
  const [monitoringOpen, setMonitoringOpen] = useState(!monitoringCollapsedByDefault);

  const workloadSections = buildAtVendorHierarchy(av, segment, { historical: !isOperationsMode });
  const portalSections = isOperationsMode ? buildAtVendorPortalSnapshot(av) : [];
  const reportStats = !isOperationsMode ? buildWorkloadReportStats(av) : null;

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

  const workloadTitle = isOperationsMode ? "Today\u2019s Workload" : "Workload Summary";
  const workloadSubtitle = isOperationsMode
    ? "Full ET-day workload including bags that already left the portal."
    : "Daily workload report for the selected period — no live portal data.";

  return (
    <Box sx={{ mb: 2.5 }}>
      {!dailyReliable && av.daily_metrics_ui_warning ? (
        <Alert severity="warning" sx={{ mb: 1.5, py: 0.5 }}>
          {av.daily_metrics_ui_warning}
        </Alert>
      ) : null}

      <Paper
        elevation={0}
        sx={{
          mb: 1.5,
          borderRadius: 2,
          overflow: "hidden",
          border: "1px solid",
          borderColor: isOperationsMode
            ? VEEWASH_DASHBOARD.primaryBlueBorder
            : VEEWASH_DASHBOARD.snapshotBorder,
          bgcolor: "#ffffff",
          boxShadow: VEEWASH_DASHBOARD.cardShadow,
        }}
      >
        {isOperationsMode ? (
          <Box
            sx={{
              px: { xs: 1.25, sm: 1.75 },
              py: { xs: 1, sm: 1.25 },
              bgcolor: VEEWASH_DASHBOARD.workloadHeaderBg,
              color: "#fff",
            }}
          >
            <Typography variant="h6" fontWeight={800} sx={{ lineHeight: 1.2, fontSize: "1.125rem" }}>
              {workloadTitle}
            </Typography>
            <Typography variant="caption" sx={{ mt: 0.35, opacity: 0.9, display: "block", maxWidth: 560 }}>
              {workloadSubtitle}
            </Typography>
          </Box>
        ) : (
          <Box sx={{ px: { xs: 1.25, sm: 1.75 }, pt: 1.25, pb: 0.5 }}>
            <Typography variant="h6" fontWeight={800} color="text.primary" sx={{ fontSize: "1.125rem" }}>
              {workloadTitle}
            </Typography>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.35 }}>
              {workloadSubtitle}
            </Typography>
          </Box>
        )}

        <Box sx={{ p: { xs: 1.25, sm: 1.75 } }}>
          {!isOperationsMode ? <WorkloadReportStats stats={reportStats} /> : null}

          <MetricCardGrid
            sections={workloadSections.filter((s) => s.key === "kpi")}
            onCardClick={handleCardClick}
            activeKey={activeKey}
          />

          <Box sx={{ my: 1.5 }}>
            <RushFilterChips value={segment} onChange={onRushChange} />
          </Box>

          <MetricCardGrid
            sections={workloadSections.filter((s) => s.key !== "kpi")}
            onCardClick={handleCardClick}
            activeKey={activeKey}
          />
        </Box>
      </Paper>

      {isOperationsMode ? (
        <Paper
          elevation={0}
          sx={{
            p: { xs: 1, sm: 1.25 },
            mb: 1.25,
            borderRadius: 2,
            border: "1px solid",
            borderColor: VEEWASH_DASHBOARD.snapshotBorder,
            bgcolor: VEEWASH_DASHBOARD.snapshotBg,
            boxShadow: "none",
          }}
        >
          <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 0.25, color: VEEWASH_DASHBOARD.primaryBlueDark, fontSize: "0.9375rem" }}>
            Current Portal Snapshot
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
            Currently visible on Vendor Home.
            {av.portal_snapshot_scrape_at ? (
              <> · Vendor Home sync {String(av.portal_snapshot_scrape_at).replace("T", " ").slice(0, 19)}</>
            ) : null}
          </Typography>

          {av.portal_snapshot_presence_reconciliation?.active_at_vendor_presence_count != null
            && av.orders_at_veewash != null
            && av.portal_snapshot_presence_reconciliation.difference != null
            && av.portal_snapshot_presence_reconciliation.difference !== 0 ? (
            <Typography variant="caption" color="warning.main" display="block" sx={{ mb: 0.75 }}>
              Presence list ({av.portal_snapshot_presence_reconciliation.active_at_vendor_presence_count}) vs Vendor Home ({av.orders_at_veewash}): diff {av.portal_snapshot_presence_reconciliation.difference}
            </Typography>
          ) : null}

          <MetricCardGrid sections={portalSections} activeKey={activeKey} compact />
        </Paper>
      ) : null}

      {isOperationsMode && monitoringCount > 0 ? (
        <Accordion
          expanded={monitoringOpen}
          onChange={(_, expanded) => setMonitoringOpen(expanded)}
          disableGutters
          elevation={0}
          sx={{
            borderRadius: "10px !important",
            border: "1px solid",
            borderColor: VEEWASH_DASHBOARD.monitoringBorder,
            bgcolor: VEEWASH_DASHBOARD.monitoringBg,
            "&:before": { display: "none" },
          }}
        >
          <AccordionSummary
            expandIcon={<ExpandMoreIcon sx={{ color: VEEWASH_DASHBOARD.monitoringText }} />}
            sx={{ px: { xs: 1.25, sm: 1.5 }, minHeight: 44 }}
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
          <AccordionDetails sx={{ px: { xs: 1.25, sm: 1.5 }, pt: 0, pb: 1.25 }}>
            <Box sx={{ maxWidth: { xs: "100%", sm: 260 } }}>
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

      {isOperationsMode && av.changed_to_rush > 0 ? (
        <Box sx={{ mt: 1.25, maxWidth: 260 }}>
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
            size="snapshot"
          />
        </Box>
      ) : null}
    </Box>
  );
}
