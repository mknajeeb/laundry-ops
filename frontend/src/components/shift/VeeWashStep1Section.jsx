import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Chip,
  Paper,
  Stack,
  Tooltip,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import ShiftCountCard from "./ShiftCountCard";
import RushFilterChips from "./RushFilterChips";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

/**
 * Step 1 authoritative Shift Monitor headline (VeeWash Orders DB model).
 * Rendered ONLY when module.veewash_step1_active === true. Replaces the legacy
 * headline totals so the two are never shown side by side. Read-only.
 */
function BagList({ ids }) {
  const list = ids || [];
  if (list.length === 0) {
    return (
      <Typography variant="caption" color="text.secondary">
        No bags in this category.
      </Typography>
    );
  }
  return (
    <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
      {list.map((id) => (
        <Chip
          key={id}
          label={id}
          size="small"
          sx={{
            fontFamily: "monospace",
            fontSize: "0.72rem",
            height: 22,
            bgcolor: "#f1f5f9",
            border: "1px solid #e2e8f0",
          }}
        />
      ))}
    </Stack>
  );
}

function ExceptionAccordion({ label, count, ids, tone }) {
  return (
    <Accordion
      disableGutters
      elevation={0}
      sx={{
        borderRadius: "10px !important",
        border: "1px solid",
        borderColor: tone?.border || VEEWASH_DASHBOARD.monitoringBorder,
        bgcolor: tone?.bg || VEEWASH_DASHBOARD.monitoringBg,
        "&:before": { display: "none" },
        mb: 0.75,
      }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ px: 1.25, minHeight: 42 }}>
        <Typography variant="body2" fontWeight={700} sx={{ color: tone?.text || "text.primary" }}>
          {label} · {count}
        </Typography>
      </AccordionSummary>
      <AccordionDetails sx={{ px: 1.25, pt: 0, pb: 1.25 }}>
        <BagList ids={ids} />
      </AccordionDetails>
    </Accordion>
  );
}

export default function VeeWashStep1Section({ summary, segment = "all", onRushChange }) {
  if (!summary) return null;
  const segments = summary.segments || {};
  const seg = segments[segment] || segments.all || summary;
  const exc = seg.exceptions || {};
  const bagIds = seg.bag_ids || {};
  const exceptionsTotal =
    exc.total ??
    (exc.disappeared_without_completion || 0) +
      (exc.missing_workload_entry_scan || 0) +
      (exc.completed_awaiting_workload_assignment || 0);

  // Reconciliation lines reflect the active segment (stay correct under filtering).
  const reconWorkload =
    `Active Workload ${seg.active_workload} = Completed ${seg.completed}` +
    ` + Pending ${seg.pending} + Disappeared ${exc.disappeared_without_completion || 0}`;
  const reconOperational =
    `Total Operational Orders ${seg.total_operational_orders} = Active Workload ${seg.active_workload}` +
    ` + Missing Entry ${exc.missing_workload_entry_scan || 0}` +
    ` + Completed Awaiting Assignment ${exc.completed_awaiting_workload_assignment || 0}`;

  return (
    <Box sx={{ mb: 2.5 }}>
      <Paper
        elevation={0}
        sx={{
          mb: 1.5,
          borderRadius: 2,
          overflow: "hidden",
          border: "1px solid",
          borderColor: VEEWASH_DASHBOARD.primaryBlueBorder,
          bgcolor: "#ffffff",
          boxShadow: VEEWASH_DASHBOARD.cardShadow,
        }}
      >
        <Box
          sx={{
            px: { xs: 1.25, sm: 1.75 },
            py: { xs: 1, sm: 1.25 },
            bgcolor: VEEWASH_DASHBOARD.workloadHeaderBg,
            color: "#fff",
          }}
        >
          <Stack direction="row" alignItems="center" spacing={0.75}>
            <Typography variant="h6" fontWeight={800} sx={{ lineHeight: 1.2, fontSize: "1.125rem" }}>
              Today&apos;s Workload
            </Typography>
            <Chip
              label="Step 1"
              size="small"
              sx={{ height: 20, fontSize: "0.68rem", fontWeight: 700, bgcolor: "rgba(255,255,255,0.2)", color: "#fff" }}
            />
          </Stack>
          <Typography variant="caption" sx={{ mt: 0.35, opacity: 0.9, display: "block", maxWidth: 620 }}>
            Rack scan establishes the day; unfinished work carries forward; disappearances and
            missing entry scans go to exceptions. VeeWash Orders DB only.
          </Typography>
        </Box>

        <Box sx={{ p: { xs: 1.25, sm: 1.75 } }}>
          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: { xs: "repeat(2, 1fr)", sm: "repeat(3, 1fr)", md: "repeat(6, 1fr)" },
              gap: 1,
            }}
          >
            <ShiftCountCard label="New Today" value={seg.new_today} size="kpi" />
            <ShiftCountCard label="Carryover" value={seg.carryover} size="kpi" />
            <ShiftCountCard label="Active Workload" value={seg.active_workload} size="kpi" variant="wf" />
            <ShiftCountCard label="Completed" value={seg.completed} size="kpi" />
            <ShiftCountCard label="Pending" value={seg.pending} size="kpi" variant="pending" />
            <ShiftCountCard label="Exceptions" value={exceptionsTotal} size="kpi" warn />
          </Box>

          <Box sx={{ mt: 1, mb: 1.25 }}>
            <Tooltip title={`${reconWorkload}\n${reconOperational}`} arrow>
              <Stack direction="row" alignItems="center" spacing={0.5} sx={{ color: "text.secondary", cursor: "help" }}>
                <InfoOutlinedIcon sx={{ fontSize: 15 }} />
                <Typography variant="caption" sx={{ fontWeight: 600 }}>
                  {reconWorkload}
                </Typography>
              </Stack>
            </Tooltip>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.25, pl: 2.5 }}>
              {reconOperational}
            </Typography>
          </Box>

          <RushFilterChips value={segment} onChange={onRushChange} />
        </Box>
      </Paper>

      {/* Current-day exceptions (bag lists). */}
      <Paper
        elevation={0}
        sx={{
          p: { xs: 1.25, sm: 1.75 },
          mb: 1.25,
          borderRadius: 2,
          border: "1px solid",
          borderColor: VEEWASH_DASHBOARD.monitoringBorder,
          bgcolor: VEEWASH_DASHBOARD.monitoringBg,
          boxShadow: "none",
        }}
      >
        <Typography variant="subtitle2" fontWeight={800} sx={{ mb: 0.75 }}>
          Current Exceptions · {exceptionsTotal}
        </Typography>
        <ExceptionAccordion
          label="Disappeared without completion"
          count={exc.disappeared_without_completion || 0}
          ids={bagIds.disappeared_without_completion}
          tone={{ border: "#fca5a5", bg: "#fef2f2", text: "#991b1b" }}
        />
        <ExceptionAccordion
          label="Missing workload-entry scan"
          count={exc.missing_workload_entry_scan || 0}
          ids={bagIds.missing_workload_entry_scan}
          tone={{ border: "#fdba74", bg: "#fff7ed", text: "#9a3412" }}
        />
        <ExceptionAccordion
          label="Completed awaiting workload assignment"
          count={exc.completed_awaiting_workload_assignment || 0}
          ids={bagIds.completed_awaiting_workload_assignment}
          tone={{ border: "#93c5fd", bg: "#eff6ff", text: "#1e40af" }}
        />
      </Paper>

      {/* Historical unresolved backlog — separate, read-only, excluded from today. */}
      {summary.historical_unresolved_backlog > 0 ? (
        <Accordion
          disableGutters
          elevation={0}
          sx={{
            mb: 1.25,
            borderRadius: "10px !important",
            border: "1px dashed",
            borderColor: VEEWASH_DASHBOARD.snapshotBorder,
            bgcolor: "#fafafa",
            "&:before": { display: "none" },
          }}
        >
          <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ px: 1.25, minHeight: 44 }}>
            <Box>
              <Typography variant="body2" fontWeight={700} color="text.secondary">
                Historical Unresolved Backlog · {summary.historical_unresolved_backlog}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                Read-only · not included in today&apos;s workload or exception totals
              </Typography>
            </Box>
          </AccordionSummary>
          <AccordionDetails sx={{ px: 1.25, pt: 0, pb: 1.25 }}>
            <BagList ids={summary.historical_unresolved_backlog_bag_ids} />
          </AccordionDetails>
        </Accordion>
      ) : null}
    </Box>
  );
}
