import { useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  CircularProgress,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import {
  getUploadConflicts,
  overrideUploadConflicts,
  uploadOrders,
} from "../api";

function UploadPage() {
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [batchId, setBatchId] = useState(null);
  const [conflicts, setConflicts] = useState([]);
  const [selectedIds, setSelectedIds] = useState([]);
  const [message, setMessage] = useState({ type: "info", text: "" });

  const uploadFile = async () => {
    if (!file) {
      setMessage({ type: "warning", text: "Please choose a file first." });
      return;
    }

    const formData = new FormData();
    formData.append("file", file);

    try {
      setLoading(true);
      setConflicts([]);
      setSelectedIds([]);

      const res = await uploadOrders(formData);
      const newBatchId = res?.data?.batch_id || null;
      setBatchId(newBatchId);

      setMessage({
        type: "success",
        text: `Uploaded. Inserted: ${res.data.rows_inserted}, Duplicates parked: ${res.data.conflicts}`,
      });

      if (newBatchId) {
        const conflictRes = await getUploadConflicts(newBatchId, "PENDING");
        setConflicts(Array.isArray(conflictRes.data) ? conflictRes.data : []);
      } else if (res.data.conflict_rows) {
        setConflicts(res.data.conflict_rows);
      }
    } catch (err) {
      console.error(err);

      const msg =
        err?.response?.data?.message ||
        err?.response?.data?.error ||
        err?.message ||
        "Upload failed";

      setMessage({ type: "error", text: msg });
    } finally {
      setLoading(false);
    }
  };

  const toggleConflict = (id) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const overrideSelected = async () => {
    if (!selectedIds.length) {
      setMessage({ type: "warning", text: "Select at least one duplicate row." });
      return;
    }

    try {
      setLoading(true);
      const res = await overrideUploadConflicts(selectedIds, "admin");

      setMessage({
        type: "success",
        text: `Override complete. Added ${res.data.overridden} row(s) to staging.`,
      });

      if (batchId) {
        const conflictRes = await getUploadConflicts(batchId, "PENDING");
        setConflicts(Array.isArray(conflictRes.data) ? conflictRes.data : []);
      } else {
        setConflicts((prev) => prev.filter((row) => !selectedIds.includes(row.id)));
      }

      setSelectedIds([]);
    } catch (error) {
      console.error(error);
      setMessage({
        type: "error",
        text: error?.response?.data?.error || "Override failed.",
      });
    } finally {
      setLoading(false);
    }
  };

  const selectAll = () => {
    setSelectedIds(conflicts.map((row) => row.id).filter(Boolean));
  };

  return (
    <Box className="page">
      <Typography sx={{ fontSize: 28, fontWeight: 900 }}>Upload Orders</Typography>

      {message.text && (
        <Alert severity={message.type} sx={{ mt: 1.2 }}>
          {message.text}
        </Alert>
      )}

      <Paper sx={{ mt: 1.2, p: 2, borderRadius: 2 }}>
        <input
          type="file"
          onChange={(e) => setFile(e.target.files?.[0] || null)}
        />

        <Stack direction="row" spacing={1} sx={{ mt: 1.4 }}>
          <Button
            variant="contained"
            onClick={uploadFile}
            disabled={loading}
          >
            {loading ? "Uploading..." : "Upload Orders"}
          </Button>

          {loading && <CircularProgress size={22} />}
        </Stack>
      </Paper>

      {conflicts.length > 0 && (
        <Paper sx={{ mt: 1.4, p: 2, borderRadius: 2 }}>
          <Typography sx={{ fontSize: 20, fontWeight: 800, mb: 1 }}>
            Duplicate Queue (Review / Override)
          </Typography>

          <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
            <Button variant="outlined" size="small" onClick={selectAll}>
              Select All
            </Button>
            <Button
              variant="contained"
              size="small"
              disabled={!selectedIds.length || loading}
              onClick={overrideSelected}
            >
              Override Selected ({selectedIds.length})
            </Button>
          </Stack>

          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell></TableCell>
                <TableCell>Name</TableCell>
                <TableCell>Weight/Count</TableCell>
                <TableCell>Service</TableCell>
                <TableCell>Date</TableCell>
                <TableCell>Reason</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {conflicts.map((row, i) => (
                <TableRow key={row.id || i}>
                  <TableCell>
                    {row.id ? (
                      <Checkbox
                        checked={selectedIds.includes(row.id)}
                        onChange={() => toggleConflict(row.id)}
                      />
                    ) : null}
                  </TableCell>
                  <TableCell>{row.name_clean || row.name}</TableCell>
                  <TableCell>{row.weight_num ?? row.weight}</TableCell>
                  <TableCell>{row.service_type || row.service}</TableCell>
                  <TableCell>{String(row.date_clean || row.date || "")}</TableCell>
                  <TableCell>{row.reason || row.action_needed}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Paper>
      )}
    </Box>
  );
}

export default UploadPage;
