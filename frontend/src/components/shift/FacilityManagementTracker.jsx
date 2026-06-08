import { Box, Chip, Divider, Paper, Stack, Typography } from "@mui/material";
import { filterByRush } from "../../utils/shiftMonitorHelpers";

const ACCENT = "#0097b2";

function CountCard({ label, value, sub, onClick, active, warn, compact }) {
  const display = value ?? "—";
  return (
    <Paper
      elevation={0}
      onClick={onClick}
      sx={{
        p: compact ? 1 : 1.25,
        borderRadius: 2,
        border: "1px solid",
        borderColor: active ? ACCENT : warn ? "error.main" : "divider",
        cursor: onClick ? "pointer" : "default",
        bgcolor: active ? "rgba(0,151,178,0.06)" : "background.paper",
        minHeight: compact ? 72 : 80,
      }}
    >
      <Typography variant={compact ? "h6" : "h5"} fontWeight={800} lineHeight={1.1} color={warn ? "error.main" : ACCENT}>
        {display}
      </Typography>
      <Typography variant="caption" fontWeight={700} display="block" sx={{ mt: 0.25 }}>
        {label}
      </Typography>
      {sub ? (
        <Typography variant="caption" color="text.secondary" display="block">
          {sub}
        </Typography>
      ) : null}
    </Paper>
  );
}

function bucketValue(section, bucket, rushFilter) {
  if (rushFilter === "rush" && bucket.startsWith("nonrush")) return 0;
  if (rushFilter === "non_rush" && bucket.startsWith("rush")) return 0;
  return section[bucket] ?? 0;
}

function totalForFilter(section, rushFilter) {
  if (rushFilter === "rush") return section.rush_total ?? (section.rush_wf || 0) + (section.rush_hd || 0);
  if (rushFilter === "non_rush") return section.nonrush_total ?? (section.nonrush_wf || 0) + (section.nonrush_hd || 0) + (section.unknown_needs_review || 0);
  return section.total ?? 0;
}

function ManagementSectionBlock({ block, rushFilter, onDrilldown, activeTag }) {
  if (!block) return null;
  const prefix = block.drilldown_prefix || "ft_total";
  const status = block.status || {};
  const open = (tag) => onDrilldown(tag);

  return (
    <Box sx={{ mb: 3 }}>
      <Stack direction="row" alignItems="baseline" spacing={1} sx={{ mb: 1 }}>
        <Typography variant="subtitle1" fontWeight={800}>
          {block.title}
        </Typography>
        {block.status_reconciled === false ? (
          <Chip size="small" color="warning" label="Counts need review" />
        ) : null}
      </Stack>

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "repeat(2, 1fr)", sm: "repeat(3, 1fr)", md: "repeat(4, 1fr)" },
          gap: 1,
          mb: 1.5,
        }}
      >
        <CountCard
          label="Total"
          value={totalForFilter(block, rushFilter)}
          onClick={() => open(prefix)}
          active={activeTag === prefix}
        />
        <CountCard
          label="Rush Total"
          value={rushFilter === "non_rush" ? 0 : block.rush_total}
          onClick={() => open(prefix)}
          active={activeTag === prefix}
        />
        <CountCard
          label="Non-Rush Total"
          value={rushFilter === "rush" ? 0 : block.nonrush_total}
          onClick={() => open(prefix)}
          active={activeTag === prefix}
        />
        <CountCard
          label="Rush WF"
          value={bucketValue(block, "rush_wf", rushFilter)}
          onClick={() => open(`${prefix}_rush_wf`)}
          active={activeTag === `${prefix}_rush_wf`}
          compact
        />
        <CountCard
          label="Rush HD"
          value={bucketValue(block, "rush_hd", rushFilter)}
          onClick={() => open(`${prefix}_rush_hd`)}
          active={activeTag === `${prefix}_rush_hd`}
          compact
        />
        <CountCard
          label="Non-Rush WF"
          value={bucketValue(block, "nonrush_wf", rushFilter)}
          onClick={() => open(`${prefix}_nonrush_wf`)}
          active={activeTag === `${prefix}_nonrush_wf`}
          compact
        />
        <CountCard
          label="Non-Rush HD"
          value={bucketValue(block, "nonrush_hd", rushFilter)}
          onClick={() => open(`${prefix}_nonrush_hd`)}
          active={activeTag === `${prefix}_nonrush_hd`}
          compact
        />
        {rushFilter === "all" && block.unknown_needs_review > 0 ? (
          <CountCard
            label="Unknown / Review"
            value={block.unknown_needs_review}
            onClick={() => open(`${prefix}_unknown_needs_review`)}
            active={activeTag === `${prefix}_unknown_needs_review`}
            warn
            compact
          />
        ) : null}
      </Box>

      <Typography variant="caption" fontWeight={700} color="text.secondary" display="block" sx={{ mb: 0.75 }}>
        Status
      </Typography>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "repeat(2, 1fr)", sm: "repeat(4, 1fr)" },
          gap: 1,
        }}
      >
        <CountCard
          label="Pending"
          value={status.pending ?? 0}
          onClick={() => open(`${prefix}_pending`)}
          active={activeTag === `${prefix}_pending`}
          compact
        />
        <CountCard
          label="Completed"
          value={status.completed ?? 0}
          onClick={() => open(`${prefix}_completed`)}
          active={activeTag === `${prefix}_completed`}
          compact
        />
        <CountCard
          label="Left / Sent"
          value={status.left_sent ?? 0}
          onClick={() => open(`${prefix}_left_sent`)}
          active={activeTag === `${prefix}_left_sent`}
          compact
        />
        <CountCard
          label="Still at Facility"
          value={status.still_at_facility ?? 0}
          onClick={() => open(`${prefix}_still_at_facility`)}
          active={activeTag === `${prefix}_still_at_facility`}
          compact
        />
      </Box>
    </Box>
  );
}

export default function FacilityManagementTracker({ tracker, rushFilter, onDrilldown, activeTag }) {
  if (!tracker) return null;
  const recon = tracker.reconciliation || {};

  return (
    <Box sx={{ mb: 3 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" flexWrap="wrap" gap={1} sx={{ mb: 1 }}>
        <Box>
          <Typography variant="h6" fontWeight={800}>
            Facility Tracker Today
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Management view for selected ET day — Entered, Carryover, and Total Workload
          </Typography>
          {tracker.entry_racks?.length ? (
            <Typography variant="caption" color="text.secondary" display="block">
              Entry racks: {tracker.entry_racks.join(", ")}
            </Typography>
          ) : null}
        </Box>
        {recon.total_equals_entered_plus_carryover === false ? (
          <Chip size="small" color="warning" label="Entered + Carryover ≠ Total" />
        ) : (
          <Chip size="small" variant="outlined" label={`Workload ${recon.total_workload ?? "—"} = Entered ${recon.entered_total ?? "—"} + Carryover ${recon.carryover_total ?? "—"}`} />
        )}
      </Stack>

      <Paper elevation={0} sx={{ p: { xs: 1.5, md: 2 }, borderRadius: 2, border: "1px solid", borderColor: "divider" }}>
        <ManagementSectionBlock
          block={tracker.entered_today}
          rushFilter={rushFilter}
          onDrilldown={onDrilldown}
          activeTag={activeTag}
        />
        <Divider sx={{ my: 1.5 }} />
        <ManagementSectionBlock
          block={tracker.carryover}
          rushFilter={rushFilter}
          onDrilldown={onDrilldown}
          activeTag={activeTag}
        />
        <Divider sx={{ my: 1.5 }} />
        <ManagementSectionBlock
          block={{ ...tracker.total_workload, title: "Total Facility Workload" }}
          rushFilter={rushFilter}
          onDrilldown={onDrilldown}
          activeTag={activeTag}
        />
      </Paper>
    </Box>
  );
}

export function facilityDrilldownRecords(records, tag, rushFilter) {
  if (!tag) return records || [];
  let out = (records || []).filter((r) => (r.drilldown_tags || []).includes(tag));
  return filterByRush(out, rushFilter);
}
