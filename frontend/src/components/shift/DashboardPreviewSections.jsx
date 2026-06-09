import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ShiftCountCard from "./ShiftCountCard";
import { formatLastWash, shiftMetricValue } from "../../utils/shiftMonitorHelpers";

export function CollapsibleDashboardSection({ title, description, defaultExpanded = false, underReview, children, alert }) {
  return (
    <Accordion
      defaultExpanded={defaultExpanded}
      disableGutters
      elevation={0}
      sx={{ mb: 1.5, border: "1px solid", borderColor: "divider", borderRadius: 2, "&:before": { display: "none" } }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Box>
          <Typography fontWeight={700}>{title}</Typography>
          {description ? (
            <Typography variant="caption" color="text.secondary" display="block">
              {description}
            </Typography>
          ) : null}
        </Box>
      </AccordionSummary>
      <AccordionDetails>
        {underReview ? (
          <Alert severity="info" sx={{ mb: children ? 1.5 : 0 }}>
            Under Review — counts will appear here once verified.
          </Alert>
        ) : null}
        {alert}
        {children}
      </AccordionDetails>
    </Accordion>
  );
}

export function WipPreviewSection({ shiftStatus, pipeline, underReview }) {
  const weighed = shiftMetricValue(shiftStatus?.weighed);
  const notWeighed = shiftMetricValue(shiftStatus?.not_weighed);
  const yetToFold = shiftMetricValue(shiftStatus?.yet_to_fold);
  const pendingWashRush = pipeline?.pending_wash_rush;
  const pendingWashNonRush = pipeline?.pending_wash_nonrush;
  const hasCounts = [weighed, notWeighed, yetToFold, pendingWashRush, pendingWashNonRush].some((v) => v != null && v > 0);

  return (
    <CollapsibleDashboardSection
      title="WIP — Work In Process"
      description="Weighing through folding / HD cleaning progress"
      underReview={!hasCounts}
    >
      {hasCounts ? (
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "repeat(2, 1fr)", sm: "repeat(3, 1fr)", md: "repeat(4, 1fr)" },
            gap: 1,
          }}
        >
          <ShiftCountCard label="Weighed" value={weighed ?? 0} compact />
          <ShiftCountCard label="Not Weighed" value={notWeighed ?? 0} compact />
          <ShiftCountCard label="Pending Wash — Rush" value={pendingWashRush ?? 0} compact />
          <ShiftCountCard label="Pending Wash — Non-Rush" value={pendingWashNonRush ?? 0} compact />
          <ShiftCountCard label="Yet to Fold" value={yetToFold ?? 0} compact />
        </Box>
      ) : null}
    </CollapsibleDashboardSection>
  );
}

export function MonitorPreviewSection({ pipeline, underReview, onDrilldown, activeTag }) {
  const hasMonitor =
    pipeline?.last_rush_wash?.at ||
    pipeline?.last_nonrush_wash?.at ||
    pipeline?.last_wash_overall?.at ||
    (pipeline?.pending_wash_rush ?? 0) > 0 ||
    (pipeline?.pending_wash_nonrush ?? 0) > 0 ||
    (pipeline?.issues ?? 0) > 0 ||
    (pipeline?.workitems ?? 0) > 0;

  return (
    <CollapsibleDashboardSection
      title="Monitor"
      description="Last scan milestones and pending wash signals"
      underReview={!hasMonitor}
    >
      {hasMonitor ? (
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "repeat(2, 1fr)", sm: "repeat(3, 1fr)", md: "repeat(4, 1fr)" },
            gap: 1,
          }}
        >
          <ShiftCountCard label="Last Rush Wash" value=" " sub={formatLastWash(pipeline?.last_rush_wash, "—")} compact />
          <ShiftCountCard label="Last Non-Rush Wash" value=" " sub={formatLastWash(pipeline?.last_nonrush_wash, "—")} compact />
          <ShiftCountCard label="Last Wash Overall" value=" " sub={formatLastWash(pipeline?.last_wash_overall, "—")} compact />
          <ShiftCountCard label="Pending Wash — Rush" value={pipeline?.pending_wash_rush ?? 0} onClick={() => onDrilldown?.("pending_wash_rush")} active={activeTag === "pending_wash_rush"} compact />
          <ShiftCountCard label="Pending Wash — Non-Rush" value={pipeline?.pending_wash_nonrush ?? 0} onClick={() => onDrilldown?.("pending_wash_nonrush")} active={activeTag === "pending_wash_nonrush"} compact />
          <ShiftCountCard label="Create Issue" value={pipeline?.issues ?? 0} onClick={() => onDrilldown?.("issues")} active={activeTag === "issues"} compact />
          <ShiftCountCard label="Workitems Added" value={pipeline?.workitems ?? 0} onClick={() => onDrilldown?.("workitems")} active={activeTag === "workitems"} compact />
        </Box>
      ) : null}
    </CollapsibleDashboardSection>
  );
}

export function ExceptionsPreviewSection({ exceptions, underReview, onDrilldown, activeTag }) {
  const items = exceptions
    ? Object.entries(exceptions).filter(([, v]) => (v?.count ?? 0) > 0)
    : [];
  const hasData = items.length > 0;

  return (
    <CollapsibleDashboardSection title="Exceptions" description="Scan gaps, weight issues, and review queues" underReview={!hasData}>
      {hasData ? (
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "repeat(2, 1fr)", sm: "repeat(3, 1fr)", md: "repeat(4, 1fr)" },
            gap: 1,
          }}
        >
          {items.map(([key, item]) => (
            <ShiftCountCard
              key={key}
              label={key.replace(/_/g, " ")}
              value={item.count}
              onClick={item.drilldown_filter ? () => onDrilldown?.(item.drilldown_filter) : undefined}
              active={activeTag === item.drilldown_filter}
              compact
            />
          ))}
        </Box>
      ) : null}
    </CollapsibleDashboardSection>
  );
}

export function EmployeeActivityPlaceholder() {
  return (
    <CollapsibleDashboardSection title="Employee Activity" description="Performance rates — coming after workload verification" underReview />
  );
}
