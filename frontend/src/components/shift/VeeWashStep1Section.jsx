import { useMemo, useState } from "react";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Chip,
  Drawer,
  IconButton,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ShiftCountCard from "./ShiftCountCard";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

/**
 * Step-1 Shift Monitor headline: WF / HD × Total | Rush | Non-Rush.
 * Uses veewash_step1_summary from the lightweight API (bag_ids included).
 */

function BagChips({ ids }) {
  const list = ids || [];
  if (!list.length) {
    return (
      <Typography variant="caption" color="text.secondary">
        No bags in this bucket.
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
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
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

function TriStat({ label, total, rush, nonRush, onSelect, activeKey, prefix }) {
  const cell = (key, title, value, variant) => (
    <ShiftCountCard
      key={key}
      label={title}
      value={value}
      size="snapshot"
      variant={variant}
      active={activeKey === key}
      onClick={onSelect ? () => onSelect(key) : undefined}
    />
  );
  return (
    <Box sx={{ mb: 1.25 }}>
      <Typography variant="caption" fontWeight={700} color="text.secondary" sx={{ mb: 0.5, display: "block" }}>
        {label}
      </Typography>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
          gap: 0.75,
        }}
      >
        {cell(`${prefix}:total`, "Total", total, "total")}
        {cell(`${prefix}:rush`, "Rush", rush, "rush")}
        {cell(`${prefix}:non_rush`, "Non-Rush", nonRush, "info")}
      </Box>
    </Box>
  );
}

function ServicePanel({
  title,
  variant,
  totalSeg,
  rushSeg,
  nonRushSeg,
  onOpenBucket,
  activeKey,
}) {
  const accent = variant === "wf" ? VEEWASH_DASHBOARD.wfCharcoal : VEEWASH_DASHBOARD.hdTeal;
  const border = variant === "wf" ? VEEWASH_DASHBOARD.wfBorder : VEEWASH_DASHBOARD.hdBorder;
  const bg = variant === "wf" ? VEEWASH_DASHBOARD.wfBg : VEEWASH_DASHBOARD.hdBg;
  const prefix = variant;

  return (
    <Paper
      elevation={0}
      sx={{
        p: { xs: 1.25, sm: 1.5 },
        borderRadius: 2,
        border: "2px solid",
        borderColor: border,
        bgcolor: bg,
        height: "100%",
      }}
    >
      <Stack direction="row" alignItems="baseline" justifyContent="space-between" sx={{ mb: 1 }}>
        <Typography variant="subtitle1" fontWeight={800} sx={{ color: accent }}>
          {title}
        </Typography>
        <Typography variant="caption" color="text.secondary" fontWeight={600}>
          Active {totalSeg?.active_workload ?? 0}
        </Typography>
      </Stack>

      <TriStat
        label="New Today"
        total={totalSeg?.new_today ?? 0}
        rush={rushSeg?.new_today ?? 0}
        nonRush={nonRushSeg?.new_today ?? 0}
        prefix={`${prefix}:new`}
        activeKey={activeKey}
        onSelect={(key) => {
          const rushKey = key.endsWith(":rush") ? "rush" : key.endsWith(":non_rush") ? "non_rush" : "total";
          const seg = rushKey === "rush" ? rushSeg : rushKey === "non_rush" ? nonRushSeg : totalSeg;
          onOpenBucket({
            key,
            title: `${title} · New Today · ${rushKey === "total" ? "Total" : rushKey === "rush" ? "Rush" : "Non-Rush"}`,
            ids: seg?.bag_ids?.new_today || [],
            count: seg?.new_today ?? 0,
          });
        }}
      />

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
          gap: 0.75,
        }}
      >
        <ShiftCountCard
          label="Carryover"
          value={totalSeg?.carryover ?? 0}
          size="snapshot"
          variant={variant}
          active={activeKey === `${prefix}:carryover`}
          onClick={() =>
            onOpenBucket({
              key: `${prefix}:carryover`,
              title: `${title} · Carryover`,
              ids: totalSeg?.bag_ids?.carryover || [],
              count: totalSeg?.carryover ?? 0,
            })
          }
        />
        <ShiftCountCard
          label="Completed"
          value={totalSeg?.completed ?? 0}
          size="snapshot"
          variant="completed"
          active={activeKey === `${prefix}:completed`}
          onClick={() =>
            onOpenBucket({
              key: `${prefix}:completed`,
              title: `${title} · Completed`,
              ids: totalSeg?.bag_ids?.completed || [],
              count: totalSeg?.completed ?? 0,
            })
          }
        />
        <ShiftCountCard
          label="Pending"
          value={totalSeg?.pending ?? 0}
          size="snapshot"
          variant="pending"
          active={activeKey === `${prefix}:pending`}
          onClick={() =>
            onOpenBucket({
              key: `${prefix}:pending`,
              title: `${title} · Pending`,
              ids: totalSeg?.bag_ids?.pending || [],
              count: totalSeg?.pending ?? 0,
            })
          }
        />
        <ShiftCountCard
          label="Review Required"
          value={totalSeg?.exceptions?.review_required ?? 0}
          size="snapshot"
          warn
          active={activeKey === `${prefix}:review`}
          onClick={() =>
            onOpenBucket({
              key: `${prefix}:review`,
              title: `${title} · Review Required`,
              ids: totalSeg?.bag_ids?.review_required || [],
              count: totalSeg?.exceptions?.review_required ?? 0,
            })
          }
        />
      </Box>
    </Paper>
  );
}

export default function VeeWashStep1Section({ summary }) {
  const [drawer, setDrawer] = useState(null);

  const segments = summary?.segments || {};
  const all = segments.all || summary || {};
  const wf = segments.wf || {};
  const hd = segments.hd || {};
  const wfRush = segments.wf_rush || {};
  const wfNonRush = segments.wf_non_rush || {};
  const hdRush = segments.hd_rush || {};
  const hdNonRush = segments.hd_non_rush || {};

  const reviewCount = all?.exceptions?.review_required ?? summary?.exceptions?.review_required ?? 0;
  const reviewIds =
    all?.bag_ids?.review_required ||
    summary?.exceptions?.review_required_bag_ids ||
    [];

  const reconLines = useMemo(() => {
    const lines = summary?.reconciliation_lines || {};
    return {
      newToday:
        lines.new_today ||
        `New Today ${all.new_today ?? 0} = WF ${wf.new_today ?? 0} + HD ${hd.new_today ?? 0}`,
      active:
        lines.active_workload ||
        `Active Workload ${all.active_workload ?? 0} = Completed ${all.completed ?? 0}` +
          ` + Pending ${all.pending ?? 0} + Review Required ${reviewCount}`,
    };
  }, [summary, all, wf, hd, reviewCount]);

  if (!summary) return null;

  const openOverall = (key, title, ids, count) => {
    setDrawer({ key, title, ids: ids || [], count: count ?? (ids || []).length });
  };

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
              sx={{
                height: 20,
                fontSize: "0.68rem",
                fontWeight: 700,
                bgcolor: "rgba(255,255,255,0.2)",
                color: "#fff",
              }}
            />
          </Stack>
          <Typography variant="caption" sx={{ mt: 0.35, opacity: 0.9, display: "block", maxWidth: 640 }}>
            WF and HD enter on first VeeWash Dirty scan. Rush filters within each service.
            Completion uses canonical evidence. RFV is excluded.
          </Typography>
        </Box>

        <Box sx={{ p: { xs: 1.25, sm: 1.75 } }}>
          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: {
                xs: "repeat(2, 1fr)",
                sm: "repeat(3, 1fr)",
                md: "repeat(6, 1fr)",
              },
              gap: 1,
              mb: 1.25,
            }}
          >
            <ShiftCountCard
              label="New Today"
              value={all.new_today ?? 0}
              size="kpi"
              active={drawer?.key === "all:new"}
              onClick={() =>
                openOverall("all:new", "New Today", all.bag_ids?.new_today, all.new_today)
              }
            />
            <ShiftCountCard
              label="Carryover"
              value={all.carryover ?? 0}
              size="kpi"
              active={drawer?.key === "all:carryover"}
              onClick={() =>
                openOverall(
                  "all:carryover",
                  "Carryover",
                  all.bag_ids?.carryover,
                  all.carryover,
                )
              }
            />
            <ShiftCountCard
              label="Active Workload"
              value={all.active_workload ?? 0}
              size="kpi"
              variant="wf"
              active={drawer?.key === "all:active"}
              onClick={() =>
                openOverall(
                  "all:active",
                  "Active Workload",
                  [...(all.bag_ids?.new_today || []), ...(all.bag_ids?.carryover || [])],
                  all.active_workload,
                )
              }
            />
            <ShiftCountCard
              label="Completed"
              value={all.completed ?? 0}
              size="kpi"
              variant="completed"
              active={drawer?.key === "all:completed"}
              onClick={() =>
                openOverall(
                  "all:completed",
                  "Completed",
                  all.bag_ids?.completed,
                  all.completed,
                )
              }
            />
            <ShiftCountCard
              label="Pending"
              value={all.pending ?? 0}
              size="kpi"
              variant="pending"
              active={drawer?.key === "all:pending"}
              onClick={() =>
                openOverall("all:pending", "Pending", all.bag_ids?.pending, all.pending)
              }
            />
            <ShiftCountCard
              label="Review Required"
              value={reviewCount}
              size="kpi"
              warn
              active={drawer?.key === "all:review"}
              onClick={() =>
                openOverall("all:review", "Review Required", reviewIds, reviewCount)
              }
            />
          </Box>

          <Typography variant="caption" color="text.secondary" display="block" fontWeight={600}>
            {reconLines.newToday}
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1.5 }}>
            {reconLines.active}
          </Typography>

          <Typography variant="subtitle2" fontWeight={800} sx={{ mb: 1 }}>
            By service · Total | Rush | Non-Rush
          </Typography>
          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" },
              gap: 1.25,
            }}
          >
            <ServicePanel
              title="Wash & Fold"
              variant="wf"
              totalSeg={wf}
              rushSeg={wfRush}
              nonRushSeg={wfNonRush}
              onOpenBucket={setDrawer}
              activeKey={drawer?.key}
            />
            <ServicePanel
              title="Home Delivery"
              variant="hd"
              totalSeg={hd}
              rushSeg={hdRush}
              nonRushSeg={hdNonRush}
              onOpenBucket={setDrawer}
              activeKey={drawer?.key}
            />
          </Box>
        </Box>
      </Paper>

      {reviewCount > 0 ? (
        <Accordion
          disableGutters
          elevation={0}
          defaultExpanded
          sx={{
            borderRadius: "10px !important",
            border: "1px solid",
            borderColor: "#fca5a5",
            bgcolor: "#fef2f2",
            "&:before": { display: "none" },
            mb: 1.25,
          }}
        >
          <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ px: 1.25, minHeight: 44 }}>
            <Box>
              <Typography variant="body2" fontWeight={800} sx={{ color: "#991b1b" }}>
                Review Required · {reviewCount}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                Entered workload · no canonical completion · absent from trustworthy At-Vendor scrape
              </Typography>
            </Box>
          </AccordionSummary>
          <AccordionDetails sx={{ px: 1.25, pt: 0, pb: 1.25 }}>
            <BagChips ids={reviewIds} />
          </AccordionDetails>
        </Accordion>
      ) : null}

      <Drawer
        anchor="bottom"
        open={Boolean(drawer)}
        onClose={() => setDrawer(null)}
        PaperProps={{
          sx: {
            height: { xs: "70%", sm: "55vh" },
            maxHeight: "75vh",
            borderTopLeftRadius: { xs: 0, sm: 16 },
            borderTopRightRadius: { xs: 0, sm: 16 },
            p: { xs: 1.5, sm: 2 },
          },
        }}
      >
        <Stack direction="row" justifyContent="space-between" alignItems="flex-start" sx={{ mb: 1.25 }}>
          <Box sx={{ minWidth: 0, pr: 1 }}>
            <Typography variant="h6" fontWeight={800} sx={{ wordBreak: "break-word" }}>
              {drawer?.title || "Bags"}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {(drawer?.ids || []).length} bag{(drawer?.ids || []).length === 1 ? "" : "s"}
              {drawer?.count != null && drawer.count !== (drawer?.ids || []).length
                ? ` · expected ${drawer.count}`
                : ""}
            </Typography>
          </Box>
          <IconButton onClick={() => setDrawer(null)} aria-label="Close" size="small">
            <CloseIcon />
          </IconButton>
        </Stack>
        <Box sx={{ overflow: "auto" }}>
          <BagChips ids={drawer?.ids} />
        </Box>
      </Drawer>
    </Box>
  );
}
