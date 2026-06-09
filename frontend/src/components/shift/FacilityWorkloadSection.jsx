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

function bucketValue(section, bucket, rushFilter) {
  if (rushFilter === "rush" && bucket.startsWith("nonrush")) return null;
  if (rushFilter === "non_rush" && bucket.startsWith("rush")) return null;
  return section[bucket] ?? 0;
}

function totalForFilter(section, rushFilter) {
  if (rushFilter === "rush") return section.rush_total ?? (section.rush_wf || 0) + (section.rush_hd || 0);
  if (rushFilter === "non_rush") return (section.nonrush_wf || 0) + (section.nonrush_hd || 0);
  return section.total ?? 0;
}

function blockReconciled(block) {
  if (!block) return true;
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
  const prefix = block.drilldown_prefix || "ft_total";
  const status = block.status || {};
  const open = (tag) => onDrilldown(tag);

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
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "repeat(2, 1fr)", sm: "repeat(3, 1fr)", md: "repeat(4, 1fr)" },
            gap: 1,
            mb: 1,
          }}
        >
          <ShiftCountCard label="Total" value={totalForFilter(block, rushFilter)} onClick={() => open(prefix)} active={activeTag === prefix} compact />
          <ShiftCountCard
            label="Rush"
            value={rushFilter === "non_rush" ? null : block.rush_total}
            onClick={() => open(`${prefix}_rush`)}
            active={activeTag === `${prefix}_rush`}
            compact
            disabled={rushFilter === "non_rush"}
          />
          <ShiftCountCard
            label="Non-Rush"
            value={rushFilter === "rush" ? null : (block.nonrush_wf || 0) + (block.nonrush_hd || 0)}
            onClick={() => open(`${prefix}_non_rush`)}
            active={activeTag === `${prefix}_non_rush`}
            compact
            disabled={rushFilter === "rush"}
          />
          <ShiftCountCard label="Rush WF" value={bucketValue(block, "rush_wf", rushFilter)} onClick={() => open(`${prefix}_rush_wf`)} active={activeTag === `${prefix}_rush_wf`} compact />
          <ShiftCountCard label="Rush HD" value={bucketValue(block, "rush_hd", rushFilter)} onClick={() => open(`${prefix}_rush_hd`)} active={activeTag === `${prefix}_rush_hd`} compact />
          <ShiftCountCard label="Non-Rush WF" value={bucketValue(block, "nonrush_wf", rushFilter)} onClick={() => open(`${prefix}_nonrush_wf`)} active={activeTag === `${prefix}_nonrush_wf`} compact />
          <ShiftCountCard label="Non-Rush HD" value={bucketValue(block, "nonrush_hd", rushFilter)} onClick={() => open(`${prefix}_nonrush_hd`)} active={activeTag === `${prefix}_nonrush_hd`} compact />
          {rushFilter === "all" && (block.unknown_needs_review || 0) > 0 ? (
            <ShiftCountCard
              label="Unknown / Review"
              value={block.unknown_needs_review}
              onClick={() => open(`${prefix}_unknown_needs_review`)}
              active={activeTag === `${prefix}_unknown_needs_review`}
              warn
              compact
            />
          ) : null}
        </Box>
        <Typography variant="caption" fontWeight={700} color="text.secondary" display="block" sx={{ mb: 0.5 }}>
          Status
        </Typography>
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "repeat(2, 1fr)", sm: "repeat(4, 1fr)" },
            gap: 1,
          }}
        >
          <ShiftCountCard label="Pending" value={status.pending ?? 0} onClick={() => open(`${prefix}_pending`)} active={activeTag === `${prefix}_pending`} compact />
          <ShiftCountCard label="Completed" value={status.completed ?? 0} onClick={() => open(`${prefix}_completed`)} active={activeTag === `${prefix}_completed`} compact />
          <ShiftCountCard label="Sent / Left" value={status.left_sent ?? 0} onClick={() => open(`${prefix}_left_sent`)} active={activeTag === `${prefix}_left_sent`} compact />
          <ShiftCountCard label="Still at Facility" value={status.still_at_facility ?? 0} onClick={() => open(`${prefix}_still_at_facility`)} active={activeTag === `${prefix}_still_at_facility`} compact />
        </Box>
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
  const totalStatus = total.status || {};

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
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "repeat(2, 1fr)", sm: "repeat(3, 1fr)", md: "repeat(6, 1fr)" },
            gap: 1,
          }}
        >
          <ShiftCountCard label="Total Workload" value={totalForFilter(total, rushFilter)} onClick={() => onDrilldown("ft_total")} active={activeTag === "ft_total"} compact />
          <ShiftCountCard label="Received Today" value={totalForFilter(entered, rushFilter)} onClick={() => onDrilldown("ft_entered")} active={activeTag === "ft_entered"} compact />
          <ShiftCountCard label="Carryover" value={totalForFilter(carryover, rushFilter)} onClick={() => onDrilldown("ft_carryover")} active={activeTag === "ft_carryover"} compact />
          <ShiftCountCard label="Pending" value={totalStatus.pending ?? 0} onClick={() => onDrilldown("ft_total_pending")} active={activeTag === "ft_total_pending"} compact />
          <ShiftCountCard label="Completed" value={totalStatus.completed ?? 0} onClick={() => onDrilldown("ft_total_completed")} active={activeTag === "ft_total_completed"} compact />
          <ShiftCountCard label="Sent / Left" value={totalStatus.left_sent ?? 0} onClick={() => onDrilldown("ft_total_left_sent")} active={activeTag === "ft_total_left_sent"} compact />
        </Box>
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
