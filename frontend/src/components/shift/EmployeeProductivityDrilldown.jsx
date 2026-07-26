import { useMemo, useState } from "react";
import {
  Box,
  Button,
  Chip,
  Collapse,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import ShiftBagRecordRow from "./ShiftBagRecordRow";
import CopyableBagId from "../CopyableBagId";
import { bagHasMissingPre, resolveBagWeightLbs } from "../../utils/employeeProductivityHelpers";
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

function fmtLbs(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return `${Number(v).toFixed(1)} lb`;
}

function WeightCell({ bag }) {
  const credited =
    bag.credited_weight_lbs != null ? Number(bag.credited_weight_lbs) : resolveBagWeightLbs(bag);
  const tip = [
    `Credited Weight (PRE): ${fmtLbs(credited)}`,
    `Evidence PRE: ${fmtLbs(bag.evidence_pre_weight_lbs ?? bag.pre_weight_lbs)}`,
    `Evidence POST: ${fmtLbs(bag.evidence_post_weight_lbs)}`,
    `Revenue Weight (POST): ${fmtLbs(bag.output_weight_lbs ?? bag.authoritative_post_weight_lbs ?? bag.post_weight_lbs)}`,
  ].join("\n");
  if (credited != null) {
    return (
      <Tooltip title={<Box sx={{ whiteSpace: "pre-line" }}>{tip}</Box>} arrow placement="top">
        <Typography component="span" variant="body2" fontWeight={700}>
          {`${credited} lbs`}
        </Typography>
      </Tooltip>
    );
  }
  const debugReason = bag.weight_debug_reason;
  const label = "Missing PRE";
  if (!debugReason) {
    return (
      <Tooltip title={<Box sx={{ whiteSpace: "pre-line" }}>{tip}</Box>} arrow placement="top">
        <Typography component="span" variant="body2" color="warning.main" sx={{ fontWeight: 600 }}>
          {label}
        </Typography>
      </Tooltip>
    );
  }
  return (
    <Tooltip title={`${tip}\n${debugReason}`} arrow placement="top">
      <Typography component="span" variant="body2" color="warning.main" sx={{ fontWeight: 600 }}>
        {label}
      </Typography>
    </Tooltip>
  );
}

function normalizeProcessedBag(bag) {
  const completedLbs = resolveBagWeightLbs(bag);
  return {
    ...bag,
    completion_time: bag.completion_time || bag.processed_time || bag.processed_timestamp,
    completion_time_et: bag.completion_time_et || bag.processed_time_et,
    completion_signal: bag.completion_signal || bag.processed_signal,
    completed_lbs: completedLbs,
    weight_lbs: completedLbs,
  };
}

function BagActionBar({ bag, onReviewBag, onSendBagForReview, sendingReview }) {
  if (!onReviewBag && !onSendBagForReview) return null;
  const missingPre = bagHasMissingPre(bag);
  return (
    <Stack
      direction="row"
      spacing={0.75}
      flexWrap="wrap"
      useFlexGap
      sx={{ mt: 1 }}
      onClick={(e) => e.stopPropagation()}
    >
      {onReviewBag ? (
        <Button
          size="small"
          variant="contained"
          disabled={sendingReview}
          onClick={() => onReviewBag(bag)}
          data-testid="employee-bag-review"
        >
          Review
        </Button>
      ) : null}
      {onSendBagForReview ? (
        <Button
          size="small"
          variant="outlined"
          disabled={sendingReview}
          onClick={() => onSendBagForReview(bag)}
          data-testid="employee-bag-send-for-review"
        >
          {missingPre ? "Send Missing PRE for Review" : "Send for Review"}
        </Button>
      ) : null}
    </Stack>
  );
}

function BagMobileCard({
  bag,
  expanded,
  onToggle,
  referenceDateEt,
  statusLabel,
  onReviewBag,
  onSendBagForReview,
  sendingReview,
}) {
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
              <CopyableBagId
                bagId={bag.bag_id}
                sx={{ fontSize: "0.95rem", wordBreak: "break-all", color: "primary.main" }}
              />
              {statusLabel ? (
                <Chip label={statusLabel} size="small" sx={{ fontWeight: 700, fontSize: "0.7rem" }} />
              ) : null}
              {bagHasMissingPre(bag) ? (
                <Chip label="Missing PRE" size="small" color="warning" sx={{ fontWeight: 700, fontSize: "0.7rem" }} />
              ) : null}
            </Stack>
            <Typography variant="body2" color="text.secondary">
              {formatFriendlyEtWall(normalized.completion_time_et || normalized.completion_time)}
            </Typography>
          </Box>
          <Box sx={{ whiteSpace: "nowrap" }}>
            {resolveBagWeightLbs(bag) != null ? (
              <Typography variant="body2" fontWeight={700} component="span">
                {`${resolveBagWeightLbs(bag)} lbs`}
              </Typography>
            ) : (
              <WeightCell bag={bag} />
            )}
          </Box>
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
          <Typography variant="caption" display="block" sx={{ mb: 0.5, whiteSpace: "pre-line" }}>
            {`Credited Weight (PRE): ${fmtLbs(bag.credited_weight_lbs ?? resolveBagWeightLbs(bag))}\nEvidence PRE: ${fmtLbs(bag.evidence_pre_weight_lbs ?? bag.pre_weight_lbs)}\nEvidence POST: ${fmtLbs(bag.evidence_post_weight_lbs)}\nRevenue Weight (POST): ${fmtLbs(bag.output_weight_lbs ?? bag.authoritative_post_weight_lbs ?? bag.post_weight_lbs)}`}
          </Typography>
          <BagActionBar
            bag={bag}
            onReviewBag={onReviewBag}
            onSendBagForReview={onSendBagForReview}
            sendingReview={sendingReview}
          />
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
  onReviewBag,
  onSendBagForReview,
  sendingReview,
}) {
  const sortedBags = useMemo(
    () => [...(bags || [])].sort((a, b) => eventTs(a).localeCompare(eventTs(b))),
    [bags],
  );
  const expandedBag = sortedBags.find((b) => b.bag_id === expandedBagId);
  const showActions = Boolean(onReviewBag || onSendBagForReview);

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
              <TableCell sx={{ fontWeight: 700, py: 1.1 }} align="right">Credited Lbs (PRE)</TableCell>
              <TableCell sx={{ fontWeight: 700, py: 1.1 }}>Signal</TableCell>
              <TableCell sx={{ fontWeight: 700, py: 1.1 }}>Status</TableCell>
              {showActions ? <TableCell sx={{ fontWeight: 700, py: 1.1 }}>Actions</TableCell> : null}
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
                    <CopyableBagId bagId={bag.bag_id} />
                  </TableCell>
                  <TableCell sx={{ maxWidth: 180, wordBreak: "break-word" }}>{bag.customer_name || "—"}</TableCell>
                  <TableCell>{bag.service_type || bag.service_bucket || "—"}</TableCell>
                  <TableCell align="right">
                    <WeightCell bag={normalized} />
                  </TableCell>
                  <TableCell>{normalized.completion_signal || "—"}</TableCell>
                  <TableCell>{statusLabel || "—"}</TableCell>
                  {showActions ? (
                    <TableCell onClick={(e) => e.stopPropagation()} sx={{ whiteSpace: "nowrap" }}>
                      <Stack direction="row" spacing={0.5}>
                        {onReviewBag ? (
                          <Button
                            size="small"
                            variant="contained"
                            disabled={sendingReview}
                            onClick={() => onReviewBag(bag)}
                          >
                            Review
                          </Button>
                        ) : null}
                        {onSendBagForReview ? (
                          <Button
                            size="small"
                            variant="outlined"
                            disabled={sendingReview}
                            onClick={() => onSendBagForReview(bag)}
                          >
                            Send for Review
                          </Button>
                        ) : null}
                      </Stack>
                    </TableCell>
                  ) : null}
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </TableContainer>
      {expandedBag ? (
        <Box sx={{ mt: 1 }}>
          <Typography variant="caption" display="block" sx={{ mb: 0.5, whiteSpace: "pre-line" }}>
            {`Credited Weight (PRE): ${fmtLbs(expandedBag.credited_weight_lbs ?? resolveBagWeightLbs(expandedBag))}\nEvidence PRE: ${fmtLbs(expandedBag.evidence_pre_weight_lbs ?? expandedBag.pre_weight_lbs)}\nEvidence POST: ${fmtLbs(expandedBag.evidence_post_weight_lbs)}\nRevenue Weight (POST): ${fmtLbs(expandedBag.output_weight_lbs ?? expandedBag.authoritative_post_weight_lbs ?? expandedBag.post_weight_lbs)}`}
          </Typography>
          <BagActionBar
            bag={expandedBag}
            onReviewBag={onReviewBag}
            onSendBagForReview={onSendBagForReview}
            sendingReview={sendingReview}
          />
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
  onReviewBag,
  onSendBagForReview,
  sendingReview = false,
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
              onReviewBag={onReviewBag}
              onSendBagForReview={onSendBagForReview}
              sendingReview={sendingReview}
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
        onReviewBag={onReviewBag}
        onSendBagForReview={onSendBagForReview}
        sendingReview={sendingReview}
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
