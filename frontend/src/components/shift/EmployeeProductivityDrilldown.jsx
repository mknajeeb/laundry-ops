import { useMemo, useState } from "react";
import {
  Box,
  Chip,
  Collapse,
  Link,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import ShiftBagRecordRow from "./ShiftBagRecordRow";
import { formatFriendlyEtWall } from "../../utils/rinseTimeFormat";

function eventTs(bag) {
  return String(
    bag.processed_time
    || bag.processed_timestamp
    || bag.completion_time
    || bag.completion_timestamp
    || "",
  );
}

function resolveBagWeightLbs(bag) {
  if (bag.completed_lbs != null) return bag.completed_lbs;
  if (bag.processed_lbs != null) return bag.processed_lbs;
  if (bag.credited_lbs != null) return bag.credited_lbs;
  if (bag.post_clean_weight != null) return bag.post_clean_weight;
  if (bag.weight != null) return bag.weight;
  if (bag.weight_num != null) return bag.weight_num;
  if (bag.weight_lbs != null) return bag.weight_lbs;
  return null;
}

function normalizeProcessedBag(bag) {
  const completedLbs = resolveBagWeightLbs(bag);
  return {
    ...bag,
    completion_time: bag.completion_time || bag.processed_time || bag.processed_timestamp,
    completion_time_et: bag.completion_time_et || bag.processed_time_et,
    completion_signal: bag.completion_signal || bag.processed_signal,
    completed_lbs: completedLbs,
  };
}

function BagMobileCard({ bag, expanded, onToggle, referenceDateEt, statusLabel }) {
  const normalized = normalizeProcessedBag(bag);
  return (
    <Paper
      variant="outlined"
      onClick={onToggle}
      sx={{ p: 1.1, borderRadius: 1.5, cursor: "pointer" }}
    >
      <Stack spacing={0.5}>
        <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1}>
          <Box sx={{ minWidth: 0 }}>
            <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap">
              <Typography
                component="span"
                fontWeight={800}
                sx={{ fontSize: "0.95rem", wordBreak: "break-all", textAlign: "left", color: "primary.main" }}
              >
                {bag.bag_id}
              </Typography>
              {statusLabel ? (
                <Chip label={statusLabel} size="small" sx={{ fontWeight: 700, fontSize: "0.7rem" }} />
              ) : null}
            </Stack>
            <Typography variant="body2" color="text.secondary">
              {formatFriendlyEtWall(normalized.completion_time_et || normalized.completion_time)}
            </Typography>
          </Box>
          <Typography variant="body2" fontWeight={700} sx={{ whiteSpace: "nowrap" }}>
            {normalized.completed_lbs != null ? `${normalized.completed_lbs} lbs` : "—"}
          </Typography>
        </Stack>
        <Typography variant="body2" sx={{ wordBreak: "break-word" }}>
          {bag.customer_name || "—"}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {bag.service_type || bag.service_bucket || "—"} · {normalized.completion_signal || "—"}
        </Typography>
      </Stack>
      <Collapse in={expanded} unmountOnExit>
        <Box sx={{ mt: 1 }} onClick={(e) => e.stopPropagation()}>
          <ShiftBagRecordRow
            row={normalized}
            variant="at_vendor"
            referenceDateEt={referenceDateEt}
            defaultOpen
            friendlyTimeDisplay
          />
        </Box>
      </Collapse>
    </Paper>
  );
}

function BagTableSection({
  title,
  bags,
  expandedBagId,
  setExpandedBagId,
  referenceDateEt,
  statusForBag,
}) {
  const sortedBags = useMemo(
    () => [...(bags || [])].sort((a, b) => eventTs(a).localeCompare(eventTs(b))),
    [bags],
  );
  const expandedBag = sortedBags.find((b) => b.bag_id === expandedBagId);

  if (!sortedBags.length) {
    return (
      <Box sx={{ mb: 1.25 }}>
        <Typography variant="subtitle2" fontWeight={800} sx={{ mb: 0.75 }}>
          {title}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          None
        </Typography>
      </Box>
    );
  }

  return (
    <Box sx={{ mb: 1.25 }}>
      <Typography variant="subtitle2" fontWeight={800} sx={{ mb: 0.75 }}>
        {title}
      </Typography>
      <TableContainer component={Paper} variant="outlined" sx={{ borderRadius: 1.5, overflowX: "auto" }}>
        <Table size="small" aria-label={title}>
          <TableHead>
            <TableRow>
              <TableCell sx={{ fontWeight: 700, py: 1.1 }}>Time</TableCell>
              <TableCell sx={{ fontWeight: 700, py: 1.1 }}>Bag ID</TableCell>
              <TableCell sx={{ fontWeight: 700, py: 1.1 }}>Customer</TableCell>
              <TableCell sx={{ fontWeight: 700, py: 1.1 }}>Service</TableCell>
              <TableCell sx={{ fontWeight: 700, py: 1.1 }} align="right">Weight</TableCell>
              <TableCell sx={{ fontWeight: 700, py: 1.1 }}>Signal</TableCell>
              <TableCell sx={{ fontWeight: 700, py: 1.1 }}>Status</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {sortedBags.map((bag) => {
              const normalized = normalizeProcessedBag(bag);
              const statusLabel = statusForBag ? statusForBag(bag) : null;
              return (
                <TableRow
                  key={`${title}-${bag.bag_id}`}
                  selected={expandedBagId === bag.bag_id}
                  hover
                  onClick={() => setExpandedBagId((prev) => (prev === bag.bag_id ? null : bag.bag_id))}
                  sx={{ cursor: "pointer", "& td": { py: 1.1 } }}
                >
                  <TableCell sx={{ whiteSpace: "nowrap" }}>
                    {formatFriendlyEtWall(normalized.completion_time_et || normalized.completion_time)}
                  </TableCell>
                  <TableCell>
                    <Link
                      component="button"
                      type="button"
                      underline="hover"
                      fontWeight={700}
                      onClick={(e) => {
                        e.stopPropagation();
                        setExpandedBagId((prev) => (prev === bag.bag_id ? null : bag.bag_id));
                      }}
                    >
                      {bag.bag_id}
                    </Link>
                  </TableCell>
                  <TableCell sx={{ maxWidth: 180, wordBreak: "break-word" }}>{bag.customer_name || "—"}</TableCell>
                  <TableCell>{bag.service_type || bag.service_bucket || "—"}</TableCell>
                  <TableCell align="right">
                    {normalized.completed_lbs != null ? `${normalized.completed_lbs} lbs` : "—"}
                  </TableCell>
                  <TableCell>{normalized.completion_signal || "—"}</TableCell>
                  <TableCell>{statusLabel || "—"}</TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </TableContainer>
      {expandedBag ? (
        <Box sx={{ mt: 1 }}>
          <ShiftBagRecordRow
            key={expandedBag.bag_id}
            row={normalizeProcessedBag(expandedBag)}
            variant="at_vendor"
            referenceDateEt={referenceDateEt}
            defaultOpen
            friendlyTimeDisplay
          />
        </Box>
      ) : null}
    </Box>
  );
}

/** Drilldown for completed employee production credit. */
export default function EmployeeProductivityDrilldown({
  bags,
  referenceDateEt,
  bagsLoading = false,
}) {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("sm"));
  const [expandedBagId, setExpandedBagId] = useState(null);
  const completed = bags;

  if (bagsLoading || completed == null) {
    return (
      <Typography variant="body2" color="text.secondary">
        Loading bag details…
      </Typography>
    );
  }
  if (!completed.length) {
    return (
      <Typography variant="body2" color="text.secondary">
        No completed bags for this employee.
      </Typography>
    );
  }

  if (isMobile) {
    return (
      <Box sx={{ py: 0.5 }}>
        <Typography variant="subtitle2" fontWeight={800} sx={{ mb: 0.75 }}>
          Completed Bags
        </Typography>
        <Stack spacing={1}>
          {[...completed].sort((a, b) => eventTs(a).localeCompare(eventTs(b))).map((bag) => (
            <BagMobileCard
              key={`completed-${bag.bag_id}`}
              bag={bag}
              expanded={expandedBagId === bag.bag_id}
              onToggle={() => setExpandedBagId((prev) => (prev === bag.bag_id ? null : bag.bag_id))}
              referenceDateEt={referenceDateEt}
              statusLabel="Completed"
            />
          ))}
        </Stack>
      </Box>
    );
  }

  return (
    <Box sx={{ py: 0.5 }}>
      <BagTableSection
        title={`Completed Bags (${completed.length})`}
        bags={completed}
        expandedBagId={expandedBagId}
        setExpandedBagId={setExpandedBagId}
        referenceDateEt={referenceDateEt}
        statusForBag={() => "Completed"}
      />
    </Box>
  );
}

export function EmployeeProductivityDrilldownCollapse({ open, children }) {
  return (
    <Collapse in={open} unmountOnExit>
      {children}
    </Collapse>
  );
}
