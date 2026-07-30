import { useMemo, useState } from "react";
import {
  Box,
  Dialog,
  DialogContent,
  DialogTitle,
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
import CloseIcon from "@mui/icons-material/Close";
import { formatDateTime } from "../utils/foldingFormat";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";

const SUMMARY_CARDS = [
  { key: "unique_bags", label: "Unique Bags", filter: null },
  { key: "sorted", label: "Sorted", filter: { type: "has", field: "sort_scan_et" } },
  { key: "washed", label: "Washed", filter: { type: "has", field: "wash_scan_et" } },
  { key: "dried", label: "Dried", filter: { type: "has", field: "dry_scan_et" } },
  { key: "ready_to_fold", label: "Ready to Fold", filter: { type: "has", field: "ready_to_fold_et" } },
  { key: "missing_sort", label: "Missing Sort", filter: { type: "code", code: "Missing Sort" } },
  { key: "missing_wash", label: "Missing Wash", filter: { type: "code", code: "Missing Wash" } },
  { key: "missing_dry", label: "Missing Dry", filter: { type: "code", code: "Missing Dry" } },
  {
    key: "sequence_exceptions",
    label: "Sequence Exceptions",
    filter: { type: "flag", field: "has_sequence_exception" },
  },
];

function SummaryCards({ summary, activeKey, onSelect }) {
  return (
    <Stack direction="row" flexWrap="wrap" gap={1} sx={{ mb: 2 }}>
      {SUMMARY_CARDS.map((card) => {
        const selected = activeKey === card.key;
        return (
          <Paper
            key={card.key}
            elevation={0}
            onClick={() => onSelect?.(card)}
            sx={{
              p: 1.25,
              minWidth: 120,
              cursor: "pointer",
              borderRadius: 2,
              border: "1px solid",
              borderColor: selected ? VEEWASH_DASHBOARD.primaryBlue : "divider",
              bgcolor: selected ? "rgba(25, 71, 149, 0.08)" : "#fff",
            }}
          >
            <Typography variant="caption" color="text.secondary" fontWeight={700}>
              {card.label}
            </Typography>
            <Typography variant="h6" fontWeight={800} color={VEEWASH_DASHBOARD.primaryBlue}>
              {summary?.[card.key] ?? 0}
            </Typography>
          </Paper>
        );
      })}
    </Stack>
  );
}

function TimelineDialog({ open, onClose, row }) {
  const timeline = row?.timeline || [];
  return (
    <Dialog open={open} onClose={onClose} maxWidth="lg" fullWidth>
      <DialogTitle sx={{ pr: 6, position: "relative" }}>
        Timeline — {row?.bag_id || "Bag"}
        <IconButton aria-label="Close" onClick={onClose} sx={{ position: "absolute", right: 8, top: 8 }}>
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers>
        {!timeline.length ? (
          <Typography variant="body2" color="text.secondary">
            No timeline evidence.
          </Typography>
        ) : (
          <Table size="small">
            <TableHead>
              <TableRow sx={{ bgcolor: "grey.50" }}>
                {[
                  "Stage",
                  "Event Time ET",
                  "Employee",
                  "Machine/Rack",
                  "Raw Event",
                  "Confidence",
                  "Source",
                  "Canonical",
                  "Exclusion Reason",
                ].map((h) => (
                  <TableCell key={h} sx={{ fontWeight: 700 }}>
                    {h}
                  </TableCell>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {timeline.map((ev, idx) => (
                <TableRow
                  key={`${ev.scan_event_id || idx}-${ev.event_time_et}`}
                  hover
                  sx={{ bgcolor: ev.canonical ? "rgba(25, 71, 149, 0.06)" : undefined }}
                >
                  <TableCell>{ev.stage || "—"}</TableCell>
                  <TableCell>{formatDateTime(ev.event_time_et)}</TableCell>
                  <TableCell>{ev.employee || "—"}</TableCell>
                  <TableCell>{ev.machine_rack || "—"}</TableCell>
                  <TableCell>{ev.raw_event || "—"}</TableCell>
                  <TableCell>{ev.confidence || "—"}</TableCell>
                  <TableCell>{ev.source || "—"}</TableCell>
                  <TableCell sx={{ fontWeight: ev.canonical ? 800 : 400 }}>
                    {ev.canonical ? "Yes" : "No"}
                  </TableCell>
                  <TableCell>{ev.exclusion_reason || "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </DialogContent>
    </Dialog>
  );
}

/**
 * Process Flow combined bag table + clickable summary cards.
 * Filter application is local to this panel via onCardFilter callback.
 */
export default function ProcessFlowChronologyPanel({
  sessions = [],
  summary = {},
  cardFilter = null,
  onCardFilterChange,
  cardsOnly = false,
  tableOnly = false,
}) {
  const [timelineRow, setTimelineRow] = useState(null);

  const visible = useMemo(() => {
    if (!cardFilter) return sessions;
    if (cardFilter.type === "has") {
      return sessions.filter((r) => r?.[cardFilter.field]);
    }
    if (cardFilter.type === "code") {
      return sessions.filter(
        (r) =>
          String(r.sequence_status || "").includes(cardFilter.code) ||
          (r.sequence_codes || []).includes(cardFilter.code),
      );
    }
    if (cardFilter.type === "flag") {
      return sessions.filter((r) => Boolean(r?.[cardFilter.field]));
    }
    return sessions;
  }, [sessions, cardFilter]);

  return (
    <>
      {!tableOnly ? (
        <SummaryCards
          summary={summary}
          activeKey={cardFilter?.cardKey || null}
          onSelect={(card) => {
            if (!card.filter) {
              onCardFilterChange?.(null);
              return;
            }
            const next = { ...card.filter, cardKey: card.key };
            onCardFilterChange?.(cardFilter?.cardKey === card.key ? null : next);
          }}
        />
      ) : null}

      {cardsOnly ? null : !visible.length ? (
        <Typography variant="body2" color="text.secondary" sx={{ py: 2 }}>
          No Process Flow bags for this selection.
        </Typography>
      ) : (
        <TableContainer component={Paper} elevation={0} sx={{ border: "1px solid", borderColor: "divider" }}>
          <Table size="small">
            <TableHead>
              <TableRow sx={{ bgcolor: VEEWASH_DASHBOARD.primaryBlue }}>
                {[
                  "Bag ID",
                  "Sort Employee",
                  "Sort Scan Time ET",
                  "Sort Machine/Rack",
                  "Wash Employee",
                  "Wash Scan Time ET",
                  "Washer",
                  "Dry Employee",
                  "Dry Scan Time ET",
                  "Dryer",
                  "Ready-to-Fold Time ET",
                  "Current Stage",
                  "Sequence Status",
                  "Confidence",
                  "View Timeline",
                ].map((h) => (
                  <TableCell key={h} sx={{ color: "#fff", fontWeight: 700, whiteSpace: "nowrap" }}>
                    {h}
                  </TableCell>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {visible.map((row) => (
                <TableRow key={row.bag_id} hover>
                  <TableCell sx={{ fontWeight: 700 }}>{row.bag_id}</TableCell>
                  <TableCell>{row.sort_employee || "—"}</TableCell>
                  <TableCell>{formatDateTime(row.sort_scan_et)}</TableCell>
                  <TableCell>{row.sort_machine_rack || "—"}</TableCell>
                  <TableCell>{row.wash_employee || "—"}</TableCell>
                  <TableCell>{formatDateTime(row.wash_scan_et)}</TableCell>
                  <TableCell>{row.washer || "—"}</TableCell>
                  <TableCell>{row.dry_employee || "—"}</TableCell>
                  <TableCell>{formatDateTime(row.dry_scan_et)}</TableCell>
                  <TableCell>{row.dryer || "—"}</TableCell>
                  <TableCell>
                    {formatDateTime(row.ready_to_fold_et)}
                    {row.ready_to_fold_is_calculated ? (
                      <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 0.5 }}>
                        (calc)
                      </Typography>
                    ) : null}
                  </TableCell>
                  <TableCell>{row.current_stage || "—"}</TableCell>
                  <TableCell>{row.sequence_status || "—"}</TableCell>
                  <TableCell>{row.confidence || "—"}</TableCell>
                  <TableCell>
                    <Box
                      component="button"
                      type="button"
                      onClick={() => setTimelineRow(row)}
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
                      View Timeline
                    </Box>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <TimelineDialog open={Boolean(timelineRow)} onClose={() => setTimelineRow(null)} row={timelineRow} />
    </>
  );
}
