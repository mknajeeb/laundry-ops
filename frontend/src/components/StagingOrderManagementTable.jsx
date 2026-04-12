import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
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
import { DeleteOutline, Image, Visibility } from "@mui/icons-material";
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
 * After a batch is confirmed: ticket photo (auto-submits pending), view/replace/delete ticket, edit/delete for live staging orders on that batch date.
 */
export default function StagingOrderManagementTable({ batchDate, user, onOrdersChanged }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
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

  const submitPendingWithTicketPhoto = async (row, file) => {
    if (!row?.id || !file) return;
    try {
      setSaving(true);
      const st = String(row.service_type || "").toUpperCase();
      const raw = Number(row.weight_num ?? 0);
      const measureNum = st === "HD" ? Math.round(raw) : raw;
      if (!Number.isFinite(measureNum) || measureNum < 0) {
        setNotice("Order has invalid weight/count. Ask an admin to edit the order.");
        return;
      }
      if (st === "HD" && !Number.isInteger(measureNum)) {
        setNotice("HD count must be a whole number. Ask an admin to edit the order.");
        return;
      }
      const tid = String(row.ticket_id || "").trim();
      const payload = { weight_num: measureNum, ticket_image_base64: await fileToBase64(file), ticket_file_name: file.name };
      if (tid) payload.ticket_id = tid;
      await submitProcessedOrder(row.id, payload);
      await load();
      onOrdersChanged?.();
    } catch (error) {
      console.error(error);
      setNotice(error?.response?.data?.error || "Failed to record ticket.");
    } finally {
      setSaving(false);
    }
  };

  const uploadTicketPhotoForProcessedRow = async (row, file) => {
    if (!row?.id || !file) return;
    try {
      setSaving(true);
      await uploadOrderTicket(row.id, {
        ticket_image_base64: await fileToBase64(file),
        ticket_file_name: file.name,
      });
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
        Capture one ticket photo per pending bag to mark it processed (uses the batch weight/count). Replace ticket photos on processed rows as needed. Batch date: {bd}.
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
                        <>
                          <Button size="small" variant="contained" component="label" htmlFor={`staging-pending-ticket-${r.id}`} disabled={saving}>
                            Ticket photo
                          </Button>
                          <input
                            id={`staging-pending-ticket-${r.id}`}
                            hidden
                            type="file"
                            accept="image/*"
                            capture="environment"
                            onChange={(e) => {
                              const file = e.target.files?.[0] || null;
                              e.target.value = "";
                              if (file) submitPendingWithTicketPhoto(r, file);
                            }}
                          />
                        </>
                      )}
                      {!pending && mine && (
                        <>
                          {Number(r?.has_ticket_image || 0) > 0 && (
                            <Button size="small" variant="outlined" startIcon={<Visibility />} onClick={() => onViewTicket(r)}>
                              View ticket
                            </Button>
                          )}
                          <Button
                            size="small"
                            variant="outlined"
                            startIcon={<Image />}
                            component="label"
                            htmlFor={`staging-ticket-${r.id}`}
                            disabled={saving}
                          >
                            {Number(r?.has_ticket_image || 0) > 0 ? "Replace ticket" : "Add ticket"}
                          </Button>
                          <input
                            id={`staging-ticket-${r.id}`}
                            hidden
                            type="file"
                            accept="image/*"
                            capture="environment"
                            onChange={(e) => {
                              const file = e.target.files?.[0] || null;
                              e.target.value = "";
                              if (file) uploadTicketPhotoForProcessedRow(r, file);
                            }}
                          />
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
