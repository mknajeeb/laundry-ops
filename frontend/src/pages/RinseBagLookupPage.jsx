import { useState } from "react";
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

  return (
    <Box sx={{ p: 2, maxWidth: 1100, mx: "auto" }}>
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
          <Paper sx={{ p: 2 }}>
            <Typography sx={{ fontWeight: 600, mb: 1 }}>
              Scan events ({detail.scan_events?.length || 0})
            </Typography>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>#</TableCell>
                  <TableCell>Rack</TableCell>
                  <TableCell>User</TableCell>
                  <TableCell>Time</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {(detail.scan_events || []).map((ev) => (
                  <TableRow key={ev.id}>
                    <TableCell>{ev.scan_index}</TableCell>
                    <TableCell>{ev.rack}</TableCell>
                    <TableCell>{ev.user_name}</TableCell>
                    <TableCell>{ev.time_scanned_raw || ev.scanned_at_parsed}</TableCell>
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
