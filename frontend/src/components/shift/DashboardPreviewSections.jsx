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

function WipCardGrid({ items, onDrilldown, activeTag }) {
  return (
    <Box
      sx={{
        display: "grid",
        gridTemplateColumns: { xs: "repeat(2, 1fr)", sm: "repeat(3, 1fr)", md: "repeat(4, 1fr)" },
        gap: 1,
      }}
    >
      {items.map(({ label, value, tag }) => (
        <ShiftCountCard
          key={label}
          label={label}
          value={value ?? 0}
          onClick={tag && onDrilldown ? () => onDrilldown(tag) : undefined}
          active={tag && activeTag === tag}
          compact
        />
      ))}
    </Box>
  );
}

export function WipPreviewSection({ wip, shiftStatus, pipeline, underReview, onDrilldown, activeTag }) {
  const summary = wip?.summary || {};
  const wf = wip?.wf || {};
  const hd = wip?.hd || {};
  const hasWipPayload = Boolean(wip?.summary);

  const summaryItems = [
    { label: "Total WIP", value: summary.total },
    { label: "WF WIP", value: summary.wf_total ?? wf.total },
    { label: "HD WIP", value: summary.hd_total ?? hd.total },
    { label: "Rush WIP", value: summary.rush_total, tag: "pipeline_work" },
    { label: "Non-Rush WIP", value: summary.non_rush_total },
  ];

  const wfItems = [
    { label: "WF Total", value: wf.total, tag: "wip_wf" },
    { label: "WF Weighed", value: wf.weighed, tag: "wf_weighed" },
    { label: "WF Not Weighed", value: wf.not_weighed, tag: "wf_not_weighed" },
    { label: "WF Pending Wash — Rush", value: wf.pending_wash_rush ?? pipeline?.pending_wash_rush, tag: "wf_pending_wash_rush" },
    { label: "WF Pending Wash — Non-Rush", value: wf.pending_wash_nonrush ?? pipeline?.pending_wash_nonrush, tag: "wf_pending_wash_nonrush" },
    { label: "WF Pending Folding", value: wf.pending_folding ?? shiftMetricValue(shiftStatus?.yet_to_fold), tag: "wf_pending_folding" },
  ];

  const hdItems = [
    { label: "HD Total", value: hd.total, tag: "wip_hd" },
    { label: "HD Not Started", value: hd.not_started, tag: "hd_not_started" },
    { label: "HD Started Cleaning", value: hd.started_cleaning, tag: "hd_started_cleaning" },
    { label: "HD Completed", value: hd.completed, tag: "hd_completed" },
    { label: "HD Sent / Left", value: hd.sent_left, tag: "hd_sent_left" },
    { label: "HD Still at Facility", value: hd.still_at_facility, tag: "hd_still_at_facility" },
  ];

  const hasCounts =
    hasWipPayload &&
    [...summaryItems, ...wfItems, ...hdItems].some((item) => Number(item.value || 0) > 0);

  return (
    <CollapsibleDashboardSection
      title="WIP — Work In Process"
      description="WF weighing/folding and HD cleaning progress — separate workflows"
      underReview={underReview && !hasCounts}
      defaultExpanded
    >
      {hasCounts ? (
        <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <Box>
            <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
              WIP Summary
            </Typography>
            <WipCardGrid items={summaryItems} onDrilldown={onDrilldown} activeTag={activeTag} />
          </Box>
          <Accordion disableGutters elevation={0} sx={{ border: "1px solid", borderColor: "divider", borderRadius: 1, "&:before": { display: "none" } }}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography fontWeight={600}>WF WIP ({wf.total ?? 0})</Typography>
            </AccordionSummary>
            <AccordionDetails>
              <WipCardGrid items={wfItems} onDrilldown={onDrilldown} activeTag={activeTag} />
            </AccordionDetails>
          </Accordion>
          <Accordion disableGutters elevation={0} sx={{ border: "1px solid", borderColor: "divider", borderRadius: 1, "&:before": { display: "none" } }}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography fontWeight={600}>HD WIP ({hd.total ?? 0})</Typography>
            </AccordionSummary>
            <AccordionDetails>
              <WipCardGrid items={hdItems} onDrilldown={onDrilldown} activeTag={activeTag} />
            </AccordionDetails>
          </Accordion>
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
      description="Last scan milestones and pending wash signals (WF pending wash; HD uses HD WIP)"
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
          <ShiftCountCard label="Pending Wash — Rush (WF)" value={pipeline?.pending_wash_rush ?? 0} onClick={() => onDrilldown?.("wf_pending_wash_rush")} active={activeTag === "wf_pending_wash_rush"} compact />
          <ShiftCountCard label="Pending Wash — Non-Rush (WF)" value={pipeline?.pending_wash_nonrush ?? 0} onClick={() => onDrilldown?.("wf_pending_wash_nonrush")} active={activeTag === "wf_pending_wash_nonrush"} compact />
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
    <CollapsibleDashboardSection title="Exceptions" description="Scan gaps, weight issues, and review queues" underReview={underReview && !hasData}>
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
