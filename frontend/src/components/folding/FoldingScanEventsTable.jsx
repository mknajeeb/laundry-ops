import {
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

export { formatRinseScanTime as formatScanTime, sortRinseScanEvents as sortScanEvents };

export default function FoldingScanEventsTable({ events }) {
  const sorted = sortScanEvents(events);
  if (!sorted.length) {
    return (
      <Typography variant="body2" color="text.secondary">
        No scan events.
      </Typography>
    );
  }
  return (
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>#</TableCell>
          <TableCell>Index</TableCell>
          <TableCell>Event</TableCell>
          <TableCell>Rack</TableCell>
          <TableCell>User</TableCell>
          <TableCell>Time</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {sorted.map((ev, idx) => (
          <TableRow key={ev.id ?? `${ev.scan_index}-${idx}`}>
            <TableCell>{idx + 1}</TableCell>
            <TableCell>{ev.scan_index ?? "—"}</TableCell>
            <TableCell>{scanEventPurpose(ev)}</TableCell>
            <TableCell>{ev.rack || "—"}</TableCell>
            <TableCell>{ev.user_name || "—"}</TableCell>
            <TableCell>{formatScanTime(ev)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
