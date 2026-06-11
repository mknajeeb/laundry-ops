import { Box, Typography } from "@mui/material";
import DrilldownCardGrid from "./DrilldownCardGrid";

export default function FacilityWipSection({ wip, rushFilter, onDrilldown, activeTag }) {
  if (!wip) return null;

  const wfCards = wip.wf_cards || [];
  const hdCards = wip.hd_cards || [];

  return (
    <Box sx={{ mb: 2.5 }}>
      <Typography variant="h6" fontWeight={800} sx={{ mb: 0.5 }}>
        Production WIP
      </Typography>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1.5 }}>
        Scan-inferred production breakdown — WF and HD workflows
      </Typography>

      <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 0.75 }}>
        WF WIP ({wip.wf?.total ?? 0} in progress)
      </Typography>
      <DrilldownCardGrid cards={wfCards} onDrilldown={onDrilldown} activeTag={activeTag} rushFilter={rushFilter} />
      <Typography variant="subtitle2" fontWeight={700} sx={{ mt: 2, mb: 0.75 }}>
        HD WIP ({wip.hd?.total ?? 0} in progress)
      </Typography>
      <DrilldownCardGrid cards={hdCards} onDrilldown={onDrilldown} activeTag={activeTag} rushFilter={rushFilter} />
    </Box>
  );
}
