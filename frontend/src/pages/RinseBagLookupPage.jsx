import { useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import { getRinseBagDetail, postRinseBagRecomputeCompletion } from "../api";

function scanEventPurpose(ev) {
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

function formatScanTime(ev) {
  const raw = String(ev?.time_scanned_raw ?? "").trim();
  const parsed = ev?.scanned_at_parsed;
  if (parsed) {
    const d = new Date(parsed);
    if (!Number.isNaN(d.getTime())) {
      return d.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
        hour: "numeric",
        minute: "2-digit",
      });
    }
    return String(parsed);
  }
  return raw || "—";
}

function sortScanEvents(events) {
  return [...(events || [])].sort((a, b) => {
    const ta = new Date(a.scanned_at_parsed || 0).getTime();
    const tb = new Date(b.scanned_at_parsed || 0).getTime();
    if (ta !== tb) return ta - tb;
    const sia = Number(a.scan_index);
    const sib = Number(b.scan_index);
    const ai = Number.isFinite(sia) ? sia : 0;
    const bi = Number.isFinite(sib) ? sib : 0;
    if (ai !== bi) return ai - bi;
    return (Number(a.id) || 0) - (Number(b.id) || 0);
  });
}

function RinseBagLookupPage() {
  const [bagId, setBagId] = useState("");
  const [detail, setDetail] = useState(null);
  const [message, setMessage] = useState({ type: "", text: "" });
  const [loading, setLoading] = useState(false);

  const load = async () => {
    const q = bagId.trim();
    if (!q) return;
    try {
      setLoading(true);
      setMessage({ type: "", text: "" });
      const res = await getRinseBagDetail(q);
      setDetail(res.data);
    } catch (e) {
      setDetail(null);
      setMessage({
        type: "error",
        text: e?.response?.data?.error || "Lookup failed",
      });
    } finally {
      setLoading(false);
    }
  };

  const recompute = async () => {
    const q = bagId.trim();
    if (!q) return;
    try {
      setLoading(true);
      const res = await postRinseBagRecomputeCompletion(q);
      setMessage({
        type: "success",
        text: `Recomputed: ${res.data?.before?.completion_status} → ${res.data?.after?.completion_status}`,
      });
      await load();
    } catch (e) {
      setMessage({
        type: "error",
        text: e?.response?.data?.error || "Recompute failed",
      });
    } finally {
      setLoading(false);
    }
  };

  const reg = detail?.registry || {};
  const scanEvents = useMemo(
    () => sortScanEvents(detail?.scan_events),
    [detail?.scan_events]
  );

  return (
    <Box sx={{ p: 2, maxWidth: 1280, mx: "auto" }}>
      <Typography variant="h5" sx={{ fontWeight: 600, mb: 2 }}>
        Rinse Bag ID lookup
      </Typography>
      <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
        <TextField
          size="small"
          label="Bag ID"
          value={bagId}
          onChange={(e) => setBagId(e.target.value)}
          sx={{ minWidth: 280 }}
        />
        <Button variant="contained" onClick={load} disabled={loading}>
          Search
        </Button>
        <Button variant="outlined" onClick={recompute} disabled={loading || !detail}>
          Recompute completion
        </Button>
      </Stack>
      {message.text && (
        <Alert severity={message.type === "error" ? "error" : "success"} sx={{ mb: 2 }}>
          {message.text}
        </Alert>
      )}
      {detail && (
        <Stack spacing={2}>
          <Paper sx={{ p: 2 }}>
            <Stack direction="row" spacing={1} alignItems="center">
              <Typography sx={{ fontWeight: 600 }}>{reg.bag_id}</Typography>
              <Chip
                label={reg.completion_status || "—"}
                color={reg.completion_status === "COMPLETED" ? "success" : "default"}
                size="small"
              />
            </Stack>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
              {reg.completion_reason}
              {reg.completed_at ? ` • ${reg.completed_at}` : ""}
              {reg.trigger_kind ? ` • trigger ${reg.trigger_kind}` : ""}
            </Typography>
          </Paper>
          {detail.staging_order && (
            <Paper sx={{ p: 2 }}>
              <Typography sx={{ fontWeight: 600, mb: 1 }}>Active staging</Typography>
              <Typography variant="body2">
                {detail.staging_order.name_clean} • {detail.staging_order.service_type} • id{" "}
                {detail.staging_order.id}
              </Typography>
            </Paper>
          )}
          <Paper sx={{ p: 2, overflowX: "auto" }}>
            <Typography sx={{ fontWeight: 600, mb: 1 }}>
              Scan events ({scanEvents.length})
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              Sorted by time, then scan index. Event / Purpose shows the Rinse workflow step.
            </Typography>
            <Table size="small" stickyHeader>
              <TableHead>
                <TableRow>
                  <TableCell sx={{ fontWeight: 600, whiteSpace: "nowrap" }}>Timeline #</TableCell>
                  <TableCell sx={{ fontWeight: 600, whiteSpace: "nowrap" }}>Scan Index</TableCell>
                  <TableCell sx={{ fontWeight: 600, minWidth: 140 }}>Event / Purpose</TableCell>
                  <TableCell sx={{ fontWeight: 600, minWidth: 120 }}>Rack</TableCell>
                  <TableCell sx={{ fontWeight: 600, minWidth: 120 }}>User</TableCell>
                  <TableCell sx={{ fontWeight: 600, whiteSpace: "nowrap" }}>Time</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {scanEvents.map((ev, idx) => (
                  <TableRow key={ev.id ?? `${idx}-${ev.scan_index}`}>
                    <TableCell>{idx + 1}</TableCell>
                    <TableCell>{ev.scan_index ?? "—"}</TableCell>
                    <TableCell sx={{ fontFamily: "monospace", fontSize: "0.85rem" }}>
                      {scanEventPurpose(ev)}
                    </TableCell>
                    <TableCell>{ev.rack || "—"}</TableCell>
                    <TableCell>{ev.user_name || "—"}</TableCell>
                    <TableCell sx={{ whiteSpace: "nowrap" }}>{formatScanTime(ev)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Paper>
        </Stack>
      )}
    </Box>
  );
}

export default RinseBagLookupPage;
