import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Paper,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import DrilldownCardGrid from "./DrilldownCardGrid";

export default function FacilityWipSection({ wip, rushFilter, onDrilldown, activeTag }) {
  if (!wip) return null;

  const wfCards = wip.wf_cards || [];
  const hdCards = wip.hd_cards || [];

  return (
    <Box sx={{ mb: 2.5 }}>
        <Typography variant="h6" fontWeight={800} sx={{ mb: 0.5 }}>
          WIP — Scan-Inferred Yet to Process
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          Scan-based in-progress breakdown ({wip.summary?.total ?? 0} bags) — not Vendor Home portal state
        </Typography>

      <Paper elevation={0} sx={{ p: { xs: 1, md: 1.25 }, borderRadius: 2, border: "1px solid", borderColor: "divider" }}>
        <Accordion
          defaultExpanded
          disableGutters
          elevation={0}
          sx={{ border: "1px solid", borderColor: "divider", borderRadius: 1, mb: 1, "&:before": { display: "none" } }}
        >
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography fontWeight={600}>WF WIP ({wip.wf?.total ?? 0})</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <DrilldownCardGrid cards={wfCards} onDrilldown={onDrilldown} activeTag={activeTag} rushFilter={rushFilter} />
          </AccordionDetails>
        </Accordion>
        <Accordion
          defaultExpanded
          disableGutters
          elevation={0}
          sx={{ border: "1px solid", borderColor: "divider", borderRadius: 1, "&:before": { display: "none" } }}
        >
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography fontWeight={600}>HD WIP ({wip.hd?.total ?? 0})</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <DrilldownCardGrid cards={hdCards} onDrilldown={onDrilldown} activeTag={activeTag} rushFilter={rushFilter} />
          </AccordionDetails>
        </Accordion>
      </Paper>
    </Box>
  );
}
