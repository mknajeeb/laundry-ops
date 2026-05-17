import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";

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

export function formatScanTime(ev) {
  const raw = String(ev?.time_scanned_raw ?? "").trim();
  const parsed = ev?.scanned_at_parsed;
  if (parsed) {
    const d = new Date(parsed);
    if (!Number.isNaN(d.getTime())) {
      return d.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      });
    }
    return String(parsed);
  }
  return raw || "—";
}

export function sortScanEvents(events) {
  return [...(events || [])].sort((a, b) => {
    const ta = new Date(a.scanned_at_parsed || 0).getTime();
    const tb = new Date(b.scanned_at_parsed || 0).getTime();
    if (ta !== tb) return ta - tb;
    const ai = Number.isFinite(Number(a.scan_index)) ? Number(a.scan_index) : 0;
    const bi = Number.isFinite(Number(b.scan_index)) ? Number(b.scan_index) : 0;
    if (ai !== bi) return ai - bi;
    return (Number(a.id) || 0) - (Number(b.id) || 0);
  });
}

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
