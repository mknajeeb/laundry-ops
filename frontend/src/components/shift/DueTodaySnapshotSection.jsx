import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Chip,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import DrilldownCardGrid from "./DrilldownCardGrid";

export default function DueTodaySnapshotSection({
  snapshot,
  rushFilter,
  onDrilldown,
  activeTag,
}) {
  if (!snapshot) return null;

  const vhView = snapshot.vendor_home_view || {};
  const internalView = snapshot.internal_scan_view || snapshot;
  const vhDueCards = vhView.due_today_cards || [];
  const internalCards = internalView.cards || snapshot.cards || [];
  const breakdownCards = internalView.breakdown_cards || snapshot.breakdown_cards || [];
  const wip = snapshot.wip || {};
  const wipCards = wip.cards || [];
  const reconciled = snapshot.reconciliation?.vendor_home_parity_ok === true;

  return (
    <Box sx={{ mb: 2.5 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" flexWrap="wrap" gap={1} sx={{ mb: 1 }}>
        <Box>
          <Typography variant="h6" fontWeight={800}>
            Due Today Snapshot
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Vendor Home due-today vs scan-inferred due-today (EDD = {snapshot.view_date || "today"})
          </Typography>
        </Box>
        <Chip size="small" color={reconciled ? "success" : "warning"} variant="outlined" label={reconciled ? "Reconciled ✓" : "Needs Review"} />
      </Stack>

      {vhView.alert ? (
        <Alert severity="warning" sx={{ mb: 1.5 }}>
          {vhView.alert}
        </Alert>
      ) : null}

      <Paper elevation={0} sx={{ p: { xs: 1.25, md: 1.5 }, borderRadius: 2, border: "1px solid", borderColor: "divider", mb: 1.5 }}>
        <Typography variant="caption" fontWeight={700} color="primary.main" display="block" sx={{ mb: 0.75 }}>
          A. Vendor Home View {vhView.manual_reference_only ? "(manual screenshot reference)" : "(portal presence)"}
        </Typography>
        <DrilldownCardGrid cards={vhDueCards} onDrilldown={onDrilldown} activeTag={activeTag} rushFilter={rushFilter} />
        {vhView.manual_reference_only ? (
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
            Manual Vendor Home reference — no record-level list available.
          </Typography>
        ) : null}
      </Paper>

      <Paper elevation={0} sx={{ p: { xs: 1.25, md: 1.5 }, borderRadius: 2, border: "1px solid", borderColor: "divider", mb: 1.5 }}>
        <Typography variant="caption" fontWeight={700} color="text.secondary" display="block" sx={{ mb: 0.75 }}>
          B. Internal Scan View
        </Typography>
        <DrilldownCardGrid cards={internalCards} onDrilldown={onDrilldown} activeTag={activeTag} rushFilter={rushFilter} />
      </Paper>

      <Paper elevation={0} sx={{ p: { xs: 1, md: 1.25 }, borderRadius: 2, border: "1px solid", borderColor: "divider", mb: 1.5 }}>
        <Accordion
          defaultExpanded={false}
          disableGutters
          elevation={0}
          sx={{ border: "none", "&:before": { display: "none" }, bgcolor: "transparent" }}
        >
          <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ px: 0, minHeight: 40 }}>
            <Typography variant="subtitle2" fontWeight={800}>
              Internal Scan — Due today breakdown
            </Typography>
          </AccordionSummary>
          <AccordionDetails sx={{ px: 0, pt: 0 }}>
            <DrilldownCardGrid cards={breakdownCards} onDrilldown={onDrilldown} activeTag={activeTag} rushFilter={rushFilter} />
          </AccordionDetails>
        </Accordion>
      </Paper>

      <Paper elevation={0} sx={{ p: { xs: 1, md: 1.25 }, borderRadius: 2, border: "1px solid", borderColor: "divider" }}>
        <Typography variant="caption" fontWeight={700} color="text.secondary" display="block" sx={{ mb: 1 }}>
          Scan-Inferred Due Today WIP ({wip.summary?.total ?? 0} pending)
        </Typography>
        <DrilldownCardGrid cards={wipCards} onDrilldown={onDrilldown} activeTag={activeTag} rushFilter={rushFilter} />
      </Paper>
    </Box>
  );
}
