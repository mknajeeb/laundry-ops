import { Fragment, useState } from "react";
import {
  Box,
  Collapse,
  IconButton,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import KeyboardArrowDownIcon from "@mui/icons-material/KeyboardArrowDown";
import KeyboardArrowUpIcon from "@mui/icons-material/KeyboardArrowUp";
import { formatDateTime } from "../utils/foldingFormat";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";

/** Subtle alternating hour-block tint (~6% primary blue). */
const HOUR_BLOCK_TINTED = "rgba(25, 71, 149, 0.06)";
const HOUR_BLOCK_TINTED_HOVER = "rgba(25, 71, 149, 0.10)";
const HOUR_BLOCK_PLAIN = "#ffffff";
const HOUR_BLOCK_PLAIN_HOVER = "rgba(0, 0, 0, 0.03)";

function formatWeight(weight) {
  if (weight == null || weight === "") return "—";
  const n = Number(weight);
  if (!Number.isFinite(n)) return String(weight);
  return `${n} lb`;
}

function intervalParts(interval) {
  const raw = String(interval?.interval_start_et || "");
  const match = raw.match(/T(\d{2}):(\d{2})/);
  if (match) {
    return { hour: Number(match[1]), minute: Number(match[2]) };
  }
  const d = new Date(raw);
  if (!Number.isNaN(d.getTime())) {
    return { hour: d.getHours(), minute: d.getMinutes() };
  }
  return { hour: 0, minute: 0 };
}

function hourBlockStyles(interval) {
  const { hour, minute } = intervalParts(interval);
  const tinted = hour % 2 === 1;
  return {
    bgcolor: tinted ? HOUR_BLOCK_TINTED : HOUR_BLOCK_PLAIN,
    hoverBg: tinted ? HOUR_BLOCK_TINTED_HOVER : HOUR_BLOCK_PLAIN_HOVER,
    isHourStart: minute === 0,
  };
}

function cumulativeCount(interval) {
  return interval.cumulative_ready_count ?? interval.available_count ?? 0;
}

function IntervalBagTable({ bags, onBagClick }) {
  if (!bags?.length) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ py: 1 }}>
        No bags in this interval.
      </Typography>
    );
  }

  return (
    <Table size="small" sx={{ bgcolor: "#fff" }}>
      <TableHead>
        <TableRow sx={{ bgcolor: "grey.50" }}>
          <TableCell sx={{ fontWeight: 700 }}>Bag ID</TableCell>
          <TableCell sx={{ fontWeight: 700 }}>Drying Scan</TableCell>
          <TableCell sx={{ fontWeight: 700 }}>Ready to Fold</TableCell>
          <TableCell sx={{ fontWeight: 700 }}>Dryer</TableCell>
          <TableCell sx={{ fontWeight: 700 }}>Weight</TableCell>
          <TableCell sx={{ fontWeight: 700 }}>Order Type</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {bags.map((bag) => (
          <TableRow key={`${bag.bag_id}-${bag.ready_to_fold_et}`} hover>
            <TableCell>
              <Typography
                component="button"
                onClick={() => onBagClick?.(bag)}
                sx={{
                  border: 0,
                  background: "none",
                  p: 0,
                  color: VEEWASH_DASHBOARD.primaryBlue,
                  fontWeight: 700,
                  cursor: "pointer",
                  fontSize: "0.875rem",
                }}
              >
                {bag.bag_id}
              </Typography>
            </TableCell>
            <TableCell>{formatDateTime(bag.drying_scan_et) || "—"}</TableCell>
            <TableCell>{formatDateTime(bag.ready_to_fold_et) || "—"}</TableCell>
            <TableCell>{bag.dryer_rack || "—"}</TableCell>
            <TableCell>{formatWeight(bag.weight)}</TableCell>
            <TableCell>{bag.order_type || bag.service_type || "—"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function IntervalRow({ interval, viewMode, onBagClick }) {
  const [open, setOpen] = useState(false);
  const showNewly = viewMode === "newly_ready" || viewMode === "both";
  const showCumulative = viewMode === "cumulative" || viewMode === "both";
  const { bgcolor, hoverBg, isHourStart } = hourBlockStyles(interval);
  const timeWeight = isHourStart ? 800 : 600;
  const colSpan = 2 + (showNewly ? 1 : 0) + (showCumulative ? 1 : 0);

  return (
    <Fragment>
      <TableRow
        hover
        sx={{
          bgcolor,
          "& > *": { borderBottom: "unset" },
          "&:hover": { bgcolor: hoverBg },
          "&.MuiTableRow-hover:hover": { bgcolor: hoverBg },
        }}
      >
        <TableCell sx={{ width: 48, bgcolor: "inherit" }}>
          <IconButton size="small" onClick={() => setOpen((v) => !v)} aria-label="Expand interval">
            {open ? <KeyboardArrowUpIcon /> : <KeyboardArrowDownIcon />}
          </IconButton>
        </TableCell>
        <TableCell sx={{ fontWeight: timeWeight, bgcolor: "inherit" }}>{interval.label}</TableCell>
        {showNewly ? (
          <TableCell align="right" sx={{ bgcolor: "inherit" }}>
            {interval.newly_ready_count ?? 0}
          </TableCell>
        ) : null}
        {showCumulative ? (
          <TableCell align="right" sx={{ fontWeight: timeWeight, bgcolor: "inherit" }}>
            {cumulativeCount(interval)}
          </TableCell>
        ) : null}
      </TableRow>
      <TableRow>
        <TableCell colSpan={colSpan} sx={{ py: 0, bgcolor: open ? "grey.50" : bgcolor }}>
          <Collapse in={open} timeout="auto" unmountOnExit>
            <Box sx={{ py: 1.5, px: 1 }}>
              <IntervalBagTable bags={interval.bags || []} onBagClick={onBagClick} />
            </Box>
          </Collapse>
        </TableCell>
      </TableRow>
    </Fragment>
  );
}

export default function ReadyToFoldChronologyPanel({
  intervals = [],
  viewMode = "both",
  onBagClick,
}) {
  const showNewly = viewMode === "newly_ready" || viewMode === "both";
  const showCumulative = viewMode === "cumulative" || viewMode === "both";
  const visible = intervals.filter((interval) => {
    if (viewMode === "newly_ready") return (interval.newly_ready_count || 0) > 0;
    if (viewMode === "cumulative") return cumulativeCount(interval) > 0;
    return (interval.newly_ready_count || 0) > 0 || cumulativeCount(interval) > 0;
  });

  if (!visible.length) {
    return null;
  }

  return (
    <TableContainer
      component={Paper}
      elevation={0}
      sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2 }}
    >
      <Table size="small" sx={{ minWidth: 520 }}>
        <TableHead>
          <TableRow sx={{ bgcolor: VEEWASH_DASHBOARD.primaryBlue, "& th": { color: "#fff", fontWeight: 700 } }}>
            <TableCell />
            <TableCell>Time</TableCell>
            {showNewly ? <TableCell align="right">New Bags Ready</TableCell> : null}
            {showCumulative ? <TableCell align="right">Cumulative Bags Ready</TableCell> : null}
          </TableRow>
        </TableHead>
        <TableBody>
          {visible.map((interval) => (
            <IntervalRow
              key={interval.interval_start_et || interval.label}
              interval={interval}
              viewMode={viewMode}
              onBagClick={onBagClick}
            />
          ))}
        </TableBody>
      </Table>
      <Stack direction="row" justifyContent="flex-end" sx={{ px: 1.5, py: 1 }}>
        <Typography variant="caption" color="text.secondary">
          Showing {visible.length} of {intervals.length} intervals with activity
        </Typography>
      </Stack>
    </TableContainer>
  );
}
