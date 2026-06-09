import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Chip,
  Divider,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ShiftCountCard from "./ShiftCountCard";
import DrilldownCardGrid from "./DrilldownCardGrid";

function totalForFilter(section, rushFilter) {
  if (rushFilter === "rush") return section.rush_total ?? (section.rush_wf || 0) + (section.rush_hd || 0);
  if (rushFilter === "non_rush") return (section.nonrush_wf || 0) + (section.nonrush_hd || 0);
  return section.total ?? 0;
}

function blockReconciled(block) {
  if (!block) return true;
  if (block.parity_ok === false) return false;
  if (block.counts_add_up === false) return false;
  if (block.status_reconciled === false) return false;
  const status = block.status || {};
  const rush = block.rush_total ?? (block.rush_wf || 0) + (block.rush_hd || 0);
  const nonRush = (block.nonrush_wf || 0) + (block.nonrush_hd || 0);
  const unknown = block.unknown_needs_review || 0;
  if ((block.total ?? 0) !== rush + nonRush + unknown) return false;
  if ((block.total ?? 0) !== (status.pending ?? 0) + (status.completed ?? 0)) return false;
  if ((status.completed ?? 0) !== (status.left_sent ?? 0) + (status.still_at_facility ?? 0)) return false;
  return true;
}

function WorkloadBreakdown({ block, rushFilter, onDrilldown, activeTag, defaultExpanded = false }) {
  if (!block) return null;
  const cards = block.cards;

  return (
    <Accordion
      defaultExpanded={defaultExpanded}
      disableGutters
      elevation={0}
      sx={{ border: "none", "&:before": { display: "none" }, bgcolor: "transparent" }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ px: 0, minHeight: 40 }}>
        <Stack direction="row" alignItems="center" spacing={1} flexWrap="wrap">
          <Typography variant="subtitle2" fontWeight={800}>
            {block.title}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {totalForFilter(block, rushFilter)} total
          </Typography>
          {!blockReconciled(block) ? <Chip size="small" color="warning" label="Needs Review" /> : null}
        </Stack>
      </AccordionSummary>
      <AccordionDetails sx={{ px: 0, pt: 0 }}>
        {cards?.length ? (
          <DrilldownCardGrid cards={cards} onDrilldown={onDrilldown} activeTag={activeTag} rushFilter={rushFilter} />
        ) : null}
      </AccordionDetails>
    </Accordion>
  );
}

function trackerReconciled(tracker) {
  const recon = tracker?.reconciliation || {};
  if (recon.total_equals_entered_plus_carryover === false) return false;
  return [tracker?.entered_today, tracker?.carryover, tracker?.total_workload].every(blockReconciled);
}

export default function FacilityWorkloadSection({ tracker, rushFilter, onDrilldown, activeTag }) {
  if (!tracker) return null;
  const entered = tracker.entered_today || {};
  const carryover = tracker.carryover || {};
  const total = tracker.total_workload || {};
  const summaryCards = tracker.summary_cards;

  return (
    <Box sx={{ mb: 2.5 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" flexWrap="wrap" gap={1} sx={{ mb: 1 }}>
        <Box>
          <Typography variant="h6" fontWeight={800}>
            At Vendor / Facility Workload
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Bags at the facility for the selected ET day — entry rack: {tracker.entry_racks?.join(", ") || "VeeWash Dirty"}
          </Typography>
        </Box>
        {trackerReconciled(tracker) ? (
          <Chip size="small" color="success" variant="outlined" label="Reconciled ✓" />
        ) : (
          <Chip size="small" color="warning" label="Needs Review" />
        )}
      </Stack>

      <Paper elevation={0} sx={{ p: { xs: 1.25, md: 1.5 }, borderRadius: 2, border: "1px solid", borderColor: "divider", mb: 1.5 }}>
        <Typography variant="caption" fontWeight={700} color="text.secondary" display="block" sx={{ mb: 0.75 }}>
          Summary
        </Typography>
        <DrilldownCardGrid cards={summaryCards || []} onDrilldown={onDrilldown} activeTag={activeTag} rushFilter={rushFilter} />
      </Paper>

      <Paper elevation={0} sx={{ p: { xs: 1, md: 1.25 }, borderRadius: 2, border: "1px solid", borderColor: "divider" }}>
        <WorkloadBreakdown
          block={{ ...entered, title: "Received Today" }}
          rushFilter={rushFilter}
          onDrilldown={onDrilldown}
          activeTag={activeTag}
          defaultExpanded
        />
        <Divider sx={{ my: 0.5 }} />
        <WorkloadBreakdown block={{ ...carryover, title: "Carryover" }} rushFilter={rushFilter} onDrilldown={onDrilldown} activeTag={activeTag} />
        <Divider sx={{ my: 0.5 }} />
        <WorkloadBreakdown block={{ ...total, title: "Total Workload" }} rushFilter={rushFilter} onDrilldown={onDrilldown} activeTag={activeTag} />
      </Paper>
    </Box>
  );
}

export { blockReconciled, trackerReconciled };
