import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  MenuItem,
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
import { Close, DeleteOutline, Image, Visibility } from "@mui/icons-material";
import {
  deleteOrder,
  deleteOrderTicket,
  getOrderTicket,
  getOrders,
  submitProcessedOrder,
  updateOrder,
  uploadOrderTicket,
} from "../api";

function normalizeCode(value) {
  return String(value || "").trim().toUpperCase();
}

function normalizeLogistics(r) {
  const v = normalizeCode(r?.logistics_status);
  if (v) return v;
  const s = normalizeCode(r?.status);
  if (["CHECKED_OUT", "SENT_TO_RINSE"].includes(s)) return "SENT_TO_RINSE";
  if (["FORCE_CHECKOUT", "FORCED_CHECKOUT"].includes(s)) return "FORCE_CHECKOUT";
  return "AT_WASHPRO";
}

function normalizeProcessing(r) {
  const v = normalizeCode(r?.processing_status);
  if (v) return v;
  const s = normalizeCode(r?.status);
  return s === "PROCESSED" ? "PROCESSED" : "PENDING";
}

async function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const out = String(reader.result || "");
      resolve(out.includes(",") ? out.split(",")[1] : out);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function inferMimeType(fileName) {
  const name = String(fileName || "").toLowerCase();
  if (name.endsWith(".png")) return "image/png";
  if (name.endsWith(".webp")) return "image/webp";
  if (name.endsWith(".gif")) return "image/gif";
  return "image/jpeg";
}

/**
 * After a batch is confirmed: edit/delete/submit/ticket actions for live staging orders on that batch date.
 */
export default function StagingOrderManagementTable({ batchDate, user, onOrdersChanged }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [submitDialogRow, setSubmitDialogRow] = useState(null);
  const [submitMeasure, setSubmitMeasure] = useState("");
  const [submitTicketId, setSubmitTicketId] = useState("");
  const [submitFile, setSubmitFile] = useState(null);
  const [submitPreview, setSubmitPreview] = useState("");
  const [ticketDialogRow, setTicketDialogRow] = useState(null);
  const [ticketFile, setTicketFile] = useState(null);
  const [ticketView, setTicketView] = useState(null);
  const [ticketViewLoading, setTicketViewLoading] = useState(false);
  const [editRow, setEditRow] = useState(null);
  const [notice, setNotice] = useState("");

  const roleCodes = (user?.roles || []).map((r) => String(r).toUpperCase());
  const isAdmin = roleCodes.includes("ADMIN");
  const userId = Number(user?.user_id || 0);

  const bd = String(batchDate || "").slice(0, 10);

  const load = useCallback(async () => {
    if (!bd) {
      setRows([]);
      return;
    }
    setLoading(true);
    try {
      const res = await getOrders({ include_all: true });
      const all = Array.isArray(res?.data) ? res.data : [];
      const scoped = all.filter((r) => {
        const d = String(r?.batch_date || r?.date_clean || "").slice(0, 10);
        if (d !== bd) return false;
        return normalizeLogistics(r) === "AT_WASHPRO";
      });
      setRows(scoped);
    } catch (e) {
      console.error(e);
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [bd]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!submitFile) {
      setSubmitPreview("");
      return;
    }
    const url = URL.createObjectURL(submitFile);
    setSubmitPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [submitFile]);

  const onSubmitOrder = async () => {
    if (!submitDialogRow) return;
    try {
      setSaving(true);
      const measureNum = Number(submitMeasure);
      if (!Number.isFinite(measureNum) || measureNum < 0) {
        setNotice("Enter valid weight/count.");
        return;
      }
      if (!submitFile) {
        setNotice("Upload ticket photo.");
        return;
      }
      const st = String(submitDialogRow.service_type || "").toUpperCase();
      if (st === "HD" && !Number.isInteger(measureNum)) {
        setNotice("HD count must be a whole number.");
        return;
      }
      const payload = { weight_num: measureNum };
      if (submitTicketId) payload.ticket_id = submitTicketId;
      payload.ticket_image_base64 = await fileToBase64(submitFile);
      payload.ticket_file_name = submitFile.name;
      await submitProcessedOrder(submitDialogRow.id, payload);
      setSubmitDialogRow(null);
      setSubmitMeasure("");
      setSubmitTicketId("");
      setSubmitFile(null);
      await load();
      onOrdersChanged?.();
    } catch (error) {
      console.error(error);
      setNotice(error?.response?.data?.error || "Failed to submit.");
    } finally {
      setSaving(false);
    }
  };

  const onAddTicket = async () => {
    if (!ticketDialogRow || !ticketFile) return;
    try {
      setSaving(true);
      await uploadOrderTicket(ticketDialogRow.id, {
        ticket_image_base64: await fileToBase64(ticketFile),
        ticket_file_name: ticketFile.name,
      });
      setTicketDialogRow(null);
      setTicketFile(null);
      await load();
      onOrdersChanged?.();
    } catch (error) {
      console.error(error);
      setNotice("Ticket upload failed.");
    } finally {
      setSaving(false);
    }
  };

  const onViewTicket = async (row) => {
    if (!row?.id) return;
    try {
      setTicketViewLoading(true);
      const res = await getOrderTicket(row.id);
      const data = res?.data || {};
      if (!data?.ticket_image_base64 && !data?.ticket_image_url) {
        setNotice("No ticket image found.");
        return;
      }
      setTicketView({
        order_id: row.id,
        name_clean: row.name_clean,
        ticket_file_name: data.ticket_file_name,
        src: data.ticket_image_url || `data:${inferMimeType(data.ticket_file_name)};base64,${data.ticket_image_base64}`,
      });
    } catch (error) {
      console.error(error);
      setNotice("Failed to load ticket image.");
    } finally {
      setTicketViewLoading(false);
    }
  };

  const formatMeasure = (r) => {
    const n = Number(r?.weight_num ?? 0);
    const hd = normalizeCode(r?.service_type) === "HD";
    return hd ? `${Math.round(n)} pcs` : `${n.toFixed(2)} lb`;
  };

  const sorted = useMemo(
    () => [...rows].sort((a, b) => Number(a?.id || 0) - Number(b?.id || 0)),
    [rows]
  );

  if (!bd) return null;

  return (
    <Paper sx={{ mt: 2, p: 2, borderRadius: 2 }}>
      <Typography sx={{ fontSize: 18, fontWeight: 600, mb: 0.5 }}>
        Live orders for this batch (staging)
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 1.5, fontSize: 14 }}>
        Submit processed bags, ticket photos, and corrections here after the batch is confirmed. Batch date: {bd}.
      </Typography>

      {loading ? (
        <Stack alignItems="center" sx={{ py: 2 }}>
          <CircularProgress size={24} />
        </Stack>
      ) : sorted.length === 0 ? (
        <Typography color="text.secondary">No staging orders for this batch date yet.</Typography>
      ) : (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>ID</TableCell>
              <TableCell>Name</TableCell>
              <TableCell>Service</TableCell>
              <TableCell>Weight</TableCell>
              <TableCell>Status</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {sorted.map((r) => {
              const pending = normalizeProcessing(r) === "PENDING";
              const mine =
                normalizeProcessing(r) === "PROCESSED" && (!userId || Number(r?.processed_by_user_id || 0) === userId);
              return (
                <TableRow key={r.id}>
                  <TableCell>{r.id}</TableCell>
                  <TableCell>{r.name_clean}</TableCell>
                  <TableCell>{r.service_type}</TableCell>
                  <TableCell>{formatMeasure(r)}</TableCell>
                  <TableCell>{pending ? "Pending" : mine ? "Processed (you)" : "Processed"}</TableCell>
                  <TableCell align="right">
                    <Stack direction="row" spacing={0.5} justifyContent="flex-end" flexWrap="wrap" useFlexGap>
                      {pending && (
                        <Button
                          size="small"
                          variant="contained"
                          onClick={() => {
                            setSubmitDialogRow(r);
                            setSubmitMeasure("");
                            setSubmitTicketId(String(r.ticket_id || ""));
                            setSubmitFile(null);
                          }}
                        >
                          Submit
                        </Button>
                      )}
                      {!pending && mine && (
                        <>
                          {Number(r?.has_ticket_image || 0) > 0 && (
                            <Button size="small" variant="outlined" startIcon={<Visibility />} onClick={() => onViewTicket(r)}>
                              View ticket
                            </Button>
                          )}
                          <Button size="small" variant="outlined" startIcon={<Image />} onClick={() => setTicketDialogRow(r)}>
                            {Number(r?.has_ticket_image || 0) > 0 ? "Replace ticket" : "Add ticket"}
                          </Button>
                          {Number(r?.has_ticket_image || 0) > 0 && (
                            <Button
                              size="small"
                              color="error"
                              variant="outlined"
                              startIcon={<DeleteOutline />}
                              onClick={async () => {
                                if (!window.confirm(`Delete ticket image for ${r.name_clean}?`)) return;
                                setSaving(true);
                                try {
                                  await deleteOrderTicket(r.id);
                                  await load();
                                  onOrdersChanged?.();
                                } finally {
                                  setSaving(false);
                                }
                              }}
                            >
                              Del ticket
                            </Button>
                          )}
                        </>
                      )}
                      {isAdmin && (
                        <>
                          <Button
                            size="small"
                            variant="outlined"
                            onClick={() =>
                              setEditRow({
                                id: r.id,
                                date_clean: String(r.date_clean || "").slice(0, 10),
                                name_clean: r.name_clean || "",
                                weight_num: r.weight_num ?? "",
                                service_type: r.service_type || "WF",
                              })
                            }
                          >
                            Edit
                          </Button>
                          <Button
                            size="small"
                            color="error"
                            variant="outlined"
                            onClick={async () => {
                              if (!window.confirm(`Delete staging order #${r.id}?`)) return;
                              setSaving(true);
                              try {
                                await deleteOrder(r.id);
                                await load();
                                onOrdersChanged?.();
                              } finally {
                                setSaving(false);
                              }
                            }}
                          >
                            Delete
                          </Button>
                        </>
                      )}
                    </Stack>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}

      <Dialog open={Boolean(submitDialogRow)} onClose={() => setSubmitDialogRow(null)} fullWidth maxWidth="xs">
        <DialogTitle>Submit processed</DialogTitle>
        <DialogContent dividers>
          {submitDialogRow && (
            <Stack spacing={1.1}>
              <Typography>{submitDialogRow.name_clean}</Typography>
              <TextField
                label={String(submitDialogRow.service_type || "").toUpperCase() === "HD" ? "Count" : "Weight"}
                type="number"
                value={submitMeasure}
                onChange={(e) => setSubmitMeasure(e.target.value)}
              />
              <Button variant="outlined" component="label">
                Upload ticket
                <input
                  hidden
                  type="file"
                  accept="image/*"
                  capture="environment"
                  onChange={(e) => setSubmitFile(e.target.files?.[0] || null)}
                />
              </Button>
              {submitPreview && (
                <Box sx={{ position: "relative", borderRadius: 1, overflow: "hidden" }}>
                  <Box component="img" src={submitPreview} alt="" sx={{ width: "100%", maxHeight: 220, objectFit: "contain" }} />
                  <IconButton size="small" onClick={() => setSubmitFile(null)} sx={{ position: "absolute", top: 4, right: 4, bgcolor: "#fff" }}>
                    <Close fontSize="small" />
                  </IconButton>
                </Box>
              )}
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSubmitDialogRow(null)}>Cancel</Button>
          <Button variant="contained" onClick={onSubmitOrder} disabled={saving || !submitMeasure || !submitFile}>
            Submit
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(ticketDialogRow)} onClose={() => setTicketDialogRow(null)} fullWidth maxWidth="xs">
        <DialogTitle>Ticket photo</DialogTitle>
        <DialogContent dividers>
          {ticketDialogRow && (
            <Stack spacing={1}>
              <Typography>{ticketDialogRow.name_clean}</Typography>
              <Button variant="outlined" component="label">
                {ticketFile ? ticketFile.name : "Select photo"}
                <input
                  hidden
                  type="file"
                  accept="image/*"
                  capture="environment"
                  onChange={(e) => setTicketFile(e.target.files?.[0] || null)}
                />
              </Button>
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setTicketDialogRow(null)}>Cancel</Button>
          <Button variant="contained" onClick={onAddTicket} disabled={!ticketFile || saving}>
            Save
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(ticketView)} onClose={() => setTicketView(null)} fullWidth maxWidth="sm">
        <DialogTitle>Ticket</DialogTitle>
        <DialogContent dividers>
          {ticketViewLoading ? (
            <CircularProgress size={24} />
          ) : (
            ticketView && (
              <Stack spacing={1}>
                <Typography>{ticketView.name_clean}</Typography>
                <Box component="img" src={ticketView.src} alt="" sx={{ width: "100%", borderRadius: 1 }} />
              </Stack>
            )
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setTicketView(null)}>Close</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(editRow)} onClose={() => setEditRow(null)} fullWidth maxWidth="sm">
        <DialogTitle>Edit staging order</DialogTitle>
        <DialogContent dividers>
          {editRow && (
            <Stack spacing={1.1}>
              <TextField
                label="Date"
                type="date"
                value={editRow.date_clean}
                InputLabelProps={{ shrink: true }}
                onChange={(e) => setEditRow((p) => ({ ...p, date_clean: e.target.value }))}
              />
              <TextField label="Name" value={editRow.name_clean} onChange={(e) => setEditRow((p) => ({ ...p, name_clean: e.target.value }))} />
              <TextField
                label="Weight / Count"
                type="number"
                value={editRow.weight_num}
                onChange={(e) => setEditRow((p) => ({ ...p, weight_num: e.target.value }))}
              />
              <TextField select label="Service" value={editRow.service_type} onChange={(e) => setEditRow((p) => ({ ...p, service_type: e.target.value }))}>
                <MenuItem value="WF">WF</MenuItem>
                <MenuItem value="HD">HD</MenuItem>
              </TextField>
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditRow(null)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={saving}
            onClick={async () => {
              if (!editRow) return;
              setSaving(true);
              try {
                await updateOrder(editRow.id, {
                  date_clean: editRow.date_clean,
                  name_clean: editRow.name_clean,
                  weight_num: Number(editRow.weight_num),
                  service_type: editRow.service_type,
                });
                setEditRow(null);
                await load();
                onOrdersChanged?.();
              } finally {
                setSaving(false);
              }
            }}
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(notice)} onClose={() => setNotice("")}>
        <DialogTitle>Notice</DialogTitle>
        <DialogContent>
          <Typography>{notice}</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setNotice("")}>OK</Button>
        </DialogActions>
      </Dialog>
    </Paper>
  );
}
