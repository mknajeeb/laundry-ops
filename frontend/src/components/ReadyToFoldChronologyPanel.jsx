import { Fragment, useState } from "react";
import {
  Box,
  Chip,
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

const STATUS_LABELS = {
  waiting_to_fold: "Waiting to fold",
  folding_started: "Folding started",
  not_yet_ready: "Not yet ready",
};

const STATUS_COLORS = {
  waiting_to_fold: { bg: "#fff7ed", color: "#c2410c" },
  folding_started: { bg: "#ecfdf5", color: "#047857" },
  not_yet_ready: { bg: "#eff6ff", color: "#1d4ed8" },
};

function StatusChip({ status }) {
  const key = String(status || "").toLowerCase();
  const colors = STATUS_COLORS[key] || { bg: "#f3f4f6", color: "#374151" };
  return (
    <Chip
      label={STATUS_LABELS[key] || status || "—"}
      size="small"
      sx={{ bgcolor: colors.bg, color: colors.color, fontWeight: 700, fontSize: "0.75rem" }}
    />
  );
}

function formatWeight(weight) {
  if (weight == null || weight === "") return "—";
  const n = Number(weight);
  if (!Number.isFinite(n)) return String(weight);
  return `${n} lb`;
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
          <TableCell sx={{ fontWeight: 700 }}>Folding Start</TableCell>
          <TableCell sx={{ fontWeight: 700 }}>Status</TableCell>
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
            <TableCell>{formatDateTime(bag.folding_start_et) || "—"}</TableCell>
            <TableCell>
              <StatusChip status={bag.status} />
            </TableCell>
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

  return (
    <Fragment>
      <TableRow hover sx={{ "& > *": { borderBottom: "unset" } }}>
        <TableCell sx={{ width: 48 }}>
          <IconButton size="small" onClick={() => setOpen((v) => !v)} aria-label="Expand interval">
            {open ? <KeyboardArrowUpIcon /> : <KeyboardArrowDownIcon />}
          </IconButton>
        </TableCell>
        <TableCell sx={{ fontWeight: 700 }}>{interval.label}</TableCell>
        {showNewly ? (
          <TableCell align="right">{interval.newly_ready_count ?? 0}</TableCell>
        ) : null}
        {showCumulative ? (
          <TableCell align="right">{interval.available_count ?? 0}</TableCell>
        ) : null}
      </TableRow>
      <TableRow>
        <TableCell colSpan={showNewly && showCumulative ? 4 : 3} sx={{ py: 0, bgcolor: "grey.50" }}>
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
    if (viewMode === "cumulative") return (interval.available_count || 0) > 0;
    return (interval.newly_ready_count || 0) > 0 || (interval.available_count || 0) > 0;
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
            {showNewly ? <TableCell align="right">Newly Ready Bags</TableCell> : null}
            {showCumulative ? <TableCell align="right">Total Bags Available to Fold</TableCell> : null}
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
