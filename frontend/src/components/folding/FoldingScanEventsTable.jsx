import {
  Chip,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import {
  formatRinseScanTime,
  sortRinseScanEvents,
} from "../../utils/rinseTimeFormat";

const LAST_SCAN_SUFFIX_RE = /\s+Last Scan$/i;

export function scanEventPurpose(ev) {
  const direct = String(ev?.purpose ?? "").trim();
  if (direct) return direct;
  try {
    const raw =
      typeof ev?.raw_json === "string" ? JSON.parse(ev.raw_json) : ev?.raw_json;
    const fromRaw = String(raw?.Purpose ?? raw?.purpose ?? "").trim();
    if (fromRaw) return fromRaw;
  } catch {
    /* ignore */
  }
  return "—";
}

export function parseScanPurposeDisplay(ev) {
  const full = scanEventPurpose(ev);
  const isLastScan =
    LAST_SCAN_SUFFIX_RE.test(full)
    || String(ev?.last_scan || "").trim().toUpperCase() === "Y";
  const base = full.replace(LAST_SCAN_SUFFIX_RE, "").trim() || full;
  return { full, base, isLastScan };
}

function normalizeScanTimestamp(ev) {
  if (ev?.scanned_at_parsed) return String(ev.scanned_at_parsed).slice(0, 19);
  return String(ev?.time_scanned_raw || "").trim();
}

function normalizeRack(ev) {
  return String(ev?.rack || "").trim();
}

function normalizeUser(ev) {
  return String(ev?.user_name || "").trim();
}

/** Collapse cross-upload duplicates; keep one display row per logical scan. */
export function collapseScanEventsForDisplay(events) {
  const sorted = sortRinseScanEvents(events || []);
  const groups = new Map();
  const order = [];

  for (const ev of sorted) {
    const { base, isLastScan } = parseScanPurposeDisplay(ev);
    const key = [
      base.toLowerCase(),
      normalizeScanTimestamp(ev),
      normalizeRack(ev).toLowerCase(),
      normalizeUser(ev).toLowerCase(),
    ].join("|");
    let group = groups.get(key);
    if (!group) {
      group = {
        key,
        basePurpose: base,
        isLastScan,
        rack: normalizeRack(ev) || "—",
        user: normalizeUser(ev) || "—",
        time: ev,
        uploadCount: 0,
        rawRows: [],
        representativeId: ev?.id,
      };
      groups.set(key, group);
      order.push(key);
    }
    group.uploadCount += 1;
    group.rawRows.push(ev);
    if (isLastScan) group.isLastScan = true;
  }

  return order.map((k) => groups.get(k)).filter(Boolean);
}

export { formatRinseScanTime as formatScanTime, sortRinseScanEvents as sortScanEvents };

export default function FoldingScanEventsTable({
  events,
  collapseUploadDuplicates = false,
}) {
  const sorted = sortRinseScanEvents(events);
  if (!sorted.length) {
    return (
      <Typography variant="body2" color="text.secondary">
        No scan events.
      </Typography>
    );
  }

  const displayRows = collapseUploadDuplicates
    ? collapseScanEventsForDisplay(sorted)
    : sorted.map((ev, idx) => {
        const { base, isLastScan } = parseScanPurposeDisplay(ev);
        return {
          key: ev.id ?? `raw-${idx}`,
          basePurpose: base,
          isLastScan,
          rack: normalizeRack(ev) || "—",
          user: normalizeUser(ev) || "—",
          time: ev,
          uploadCount: 1,
          rawRows: [ev],
          representativeId: ev?.id,
        };
      });

  return (
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>#</TableCell>
          {!collapseUploadDuplicates ? <TableCell>Index</TableCell> : null}
          <TableCell>Event</TableCell>
          <TableCell>Rack</TableCell>
          <TableCell>User</TableCell>
          <TableCell>Time</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {displayRows.map((row, idx) => (
          <TableRow key={row.key ?? row.representativeId ?? idx}>
            <TableCell>{idx + 1}</TableCell>
            {!collapseUploadDuplicates ? (
              <TableCell>{row.time?.scan_index ?? "—"}</TableCell>
            ) : null}
            <TableCell>
              <Stack direction="row" spacing={0.5} alignItems="center" flexWrap="wrap" useFlexGap>
                <span>{row.basePurpose}</span>
                {row.isLastScan ? (
                  <Chip label="Last Scan" size="small" variant="outlined" sx={{ height: 20, fontSize: 10 }} />
                ) : null}
                {row.uploadCount > 1 ? (
                  <Chip
                    label={`×${row.uploadCount} uploads`}
                    size="small"
                    color="default"
                    sx={{ height: 20, fontSize: 10 }}
                  />
                ) : null}
              </Stack>
            </TableCell>
            <TableCell>{row.rack}</TableCell>
            <TableCell>{row.user}</TableCell>
            <TableCell>{formatRinseScanTime(row.time)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
