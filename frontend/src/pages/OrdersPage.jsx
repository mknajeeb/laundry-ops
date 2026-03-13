import { useEffect, useMemo, useState, useDeferredValue } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  InputAdornment,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { Bolt, CheckCircle, Image, Refresh, Search } from "@mui/icons-material";
import {
  deleteOrder,
  getOrders,
  submitProcessedOrder,
  updateOrder,
  uploadOrderTicket,
} from "../api";

function parseAsLocalDate(value) {
  if (!value) return null;
  const raw = String(value).trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
    const [y, m, d] = raw.split("-").map(Number);
    return new Date(y, m - 1, d);
  }
  const dt = new Date(raw);
  if (Number.isNaN(dt.getTime())) return null;
  return new Date(dt.getUTCFullYear(), dt.getUTCMonth(), dt.getUTCDate());
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

function OrdersPage({ user }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);

  const [logisticsTab, setLogisticsTab] = useState("AT_WASHPRO");
  const [processingTab, setProcessingTab] = useState("QUEUE"); // QUEUE | PROCESSED

  const [submitDialogRow, setSubmitDialogRow] = useState(null);
  const [submitFile, setSubmitFile] = useState(null);
  const [submitConfirm, setSubmitConfirm] = useState("");

  const [ticketDialogRow, setTicketDialogRow] = useState(null);
  const [ticketFile, setTicketFile] = useState(null);

  const [editRow, setEditRow] = useState(null);
  const isAdmin = (user?.roles || []).map((r) => String(r).toUpperCase()).includes("ADMIN");

  const load = async () => {
    try {
      setLoading(true);
      const res = await getOrders({ include_all: true });
      setRows(Array.isArray(res.data) ? res.data : []);
    } catch (error) {
      console.error(error);
      setRows([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const normalizeLogistics = (r) => {
    const v = String(r?.logistics_status || "").toUpperCase();
    if (v) return v;
    const s = String(r?.status || "").toUpperCase();
    if (["CHECKED_OUT", "SENT_TO_RINSE"].includes(s)) return "SENT_TO_RINSE";
    if (["FORCE_CHECKOUT", "FORCED_CHECKOUT"].includes(s)) return "FORCE_CHECKOUT";
    return "AT_WASHPRO";
  };

  const normalizeProcessing = (r) => {
    const v = String(r?.processing_status || "").toUpperCase();
    if (v) return v;
    const s = String(r?.status || "").toUpperCase();
    return s === "PROCESSED" ? "PROCESSED" : "PENDING";
  };

  const isRush = (r) => String(r?.rush_type || "").toUpperCase() === "RUSH";
  const isHD = (r) => String(r?.service_type || "").toUpperCase() === "HD";
  const formatMeasure = (r) => {
    const n = Number(r?.weight_num ?? 0);
    return isHD(r) ? `${Math.round(n)} pcs` : `${n.toFixed(2)} lb`;
  };
  const formatDate = (value) => {
    const d = parseAsLocalDate(value);
    if (!d) return "-";
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  };

  const scopedRows = useMemo(() => {
    const q = deferredSearch.trim().toLowerCase();
    return rows.filter((r) => {
      const logisticsOk = logisticsTab === "ALL" || normalizeLogistics(r) === logisticsTab;
      const proc = normalizeProcessing(r);
      const processOk = processingTab === "QUEUE" ? proc === "PENDING" : proc === "PROCESSED";
      const byMe =
        processingTab !== "PROCESSED" ||
        !user?.user_id ||
        Number(r?.processed_by_user_id || 0) === Number(user.user_id);

      const searchOk =
        !q ||
        String(r?.name_clean || "").toLowerCase().includes(q) ||
        String(r?.id || "").includes(q) ||
        String(r?.service_type || "").toLowerCase().includes(q) ||
        String(r?.weight_num ?? "").toLowerCase().includes(q);

      return logisticsOk && processOk && byMe && searchOk;
    });
  }, [rows, logisticsTab, processingTab, deferredSearch, user?.user_id]);

  const counters = useMemo(() => {
    const base = rows.filter((r) => normalizeLogistics(r) === logisticsTab);
    const queue = base.filter((r) => normalizeProcessing(r) === "PENDING");
    const done = base.filter((r) => normalizeProcessing(r) === "PROCESSED");
    const rushQueue = queue.filter((r) => isRush(r)).length;
    const nonRushQueue = queue.length - rushQueue;
    return {
      queue: queue.length,
      done: done.length,
      rushQueue,
      nonRushQueue,
      visible: scopedRows.length,
    };
  }, [rows, scopedRows, logisticsTab]);

  const onSubmitOrder = async () => {
    if (!submitDialogRow) return;
    try {
      setSaving(true);
      const payload = {};
      if (submitFile) {
        payload.ticket_image_base64 = await fileToBase64(submitFile);
        payload.ticket_file_name = submitFile.name;
      }
      await submitProcessedOrder(submitDialogRow.id, payload);
      setSubmitConfirm(`Order #${submitDialogRow.id} submitted.`);
      setSubmitDialogRow(null);
      setSubmitFile(null);
      await load();
    } catch (error) {
      console.error(error);
      setSubmitConfirm("Failed to submit order.");
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
      setSubmitConfirm(`Ticket saved for #${ticketDialogRow.id}.`);
      setTicketDialogRow(null);
      setTicketFile(null);
      await load();
    } catch (error) {
      console.error(error);
      setSubmitConfirm("Failed to save ticket.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "#ffffff", px: { xs: 1, sm: 1.5 }, py: 1 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Typography sx={{ fontSize: 30, fontWeight: 500 }}>Orders</Typography>
        <Button size="small" variant="text" startIcon={<Refresh />} onClick={load} disabled={loading || saving}>
          Refresh
        </Button>
      </Stack>
      <Typography sx={{ color: "#6b7280", mt: 0.2 }}>Individual processing queue</Typography>

      <Stack direction="row" spacing={1} sx={{ mt: 1, overflowX: "auto", pb: 0.2 }}>
        {[
          { key: "AT_WASHPRO", label: "At Washpro" },
          { key: "SENT_TO_RINSE", label: "Sent to Rinse" },
        ].map((t) => (
          <Button
            key={t.key}
            onClick={() => setLogisticsTab(t.key)}
            sx={{
              textTransform: "none",
              borderRadius: 2,
              px: 1.4,
              py: 0.7,
              bgcolor: logisticsTab === t.key ? "#0f172a" : "#eef2f7",
              color: logisticsTab === t.key ? "#ffffff" : "#111827",
              opacity: counters.visible === 0 ? 0.45 : 1,
            }}
          >
            {t.label}
          </Button>
        ))}
      </Stack>

      <Stack direction="row" spacing={1} sx={{ mt: 0.8, overflowX: "auto", pb: 0.2 }}>
        <Chip
          label={`Queue ${counters.queue}`}
          color={processingTab === "QUEUE" ? "error" : "default"}
          onClick={() => setProcessingTab("QUEUE")}
          clickable
          sx={{ opacity: counters.queue === 0 ? 0.45 : 1 }}
        />
        <Chip
          label={`Processed ${counters.done}`}
          color={processingTab === "PROCESSED" ? "success" : "default"}
          onClick={() => setProcessingTab("PROCESSED")}
          clickable
          sx={{ opacity: counters.done === 0 ? 0.45 : 1 }}
        />
        <Chip icon={<Bolt />} label={`Rush ${counters.rushQueue}`} variant="outlined" />
        <Chip icon={<CheckCircle />} label={`Non-Rush ${counters.nonRushQueue}`} variant="outlined" />
        <Chip label={`Visible ${counters.visible}`} />
      </Stack>

      <Paper sx={{ mt: 1.1, p: 1.1, borderRadius: 2, border: "1px solid #e5e7eb" }}>
        <TextField
          fullWidth
          size="small"
          placeholder="Search name, id, service, weight/count"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <Search fontSize="small" />
              </InputAdornment>
            ),
          }}
        />
      </Paper>

      {loading ? (
        <Stack alignItems="center" justifyContent="center" sx={{ py: 8 }} spacing={1.1}>
          <CircularProgress size={26} />
          <Typography color="text.secondary">Loading...</Typography>
        </Stack>
      ) : scopedRows.length === 0 ? (
        <Paper sx={{ mt: 1.2, p: 2, borderRadius: 2, opacity: 0.55 }}>
          <Typography>No orders in this queue.</Typography>
        </Paper>
      ) : (
        <Stack spacing={1} sx={{ mt: 1.2 }}>
          {scopedRows.map((r) => {
            const rush = isRush(r);
            const hd = isHD(r);
            const pending = normalizeProcessing(r) === "PENDING";
            return (
              <Paper
                key={r.id}
                sx={{
                  p: 1.2,
                  borderRadius: 2,
                  bgcolor: hd ? "#0097b2" : "#0b1324",
                  border: hd ? "1px solid #48c8dc" : "1px solid #1f2d4a",
                  color: "#ffffff",
                }}
              >
                <Stack spacing={0.8}>
                  <Stack direction="row" alignItems="center" justifyContent="space-between">
                    <Stack direction="row" spacing={0.8} alignItems="center">
                      <Chip
                        size="small"
                        icon={rush ? <Bolt sx={{ fontSize: 16 }} /> : <CheckCircle sx={{ fontSize: 14 }} />}
                        label={rush ? "RUSH" : "NON-RUSH"}
                        sx={{
                          bgcolor: "#ffffff",
                          color: rush ? "#b91c1c" : "#0f172a",
                          height: 26,
                        }}
                      />
                      <Typography sx={{ fontSize: 20, fontWeight: 500 }}>{r.name_clean || "-"}</Typography>
                    </Stack>
                    <Chip size="small" label={pending ? "PENDING" : "PROCESSED"} sx={{ bgcolor: "#ffffff", color: "#111827" }} />
                  </Stack>

                  <Typography sx={{ opacity: 0.95, fontSize: 15 }}>
                    {formatDate(r.date_clean)} • {formatMeasure(r)}
                  </Typography>

                  <Stack direction="row" spacing={0.8}>
                    <Chip size="small" label={String(r.service_type || "").toUpperCase()} sx={{ bgcolor: "#ffffff", color: "#111827" }} />
                    <Chip size="small" label={`#${r.id}`} sx={{ bgcolor: "#ffffff", color: "#111827" }} />
                  </Stack>

                  <Divider sx={{ borderColor: "rgba(255,255,255,0.25)" }} />

                  <Stack direction="row" spacing={1}>
                    {processingTab === "QUEUE" && pending && (
                      <Button
                        variant="contained"
                        size="small"
                        onClick={() => setSubmitDialogRow(r)}
                        disabled={saving}
                        sx={{ bgcolor: "#ffffff", color: "#111827", textTransform: "none" }}
                      >
                        Submit
                      </Button>
                    )}
                    {processingTab === "PROCESSED" && (
                      <Button
                        variant="outlined"
                        size="small"
                        startIcon={<Image />}
                        onClick={() => setTicketDialogRow(r)}
                        sx={{ borderColor: "#ffffff", color: "#ffffff", textTransform: "none" }}
                      >
                        Add missed picture
                      </Button>
                    )}
                    {isAdmin && (
                      <>
                        <Button
                          variant="outlined"
                          size="small"
                          onClick={() =>
                            setEditRow({
                              id: r.id,
                              date_clean: String(r.date_clean || "").slice(0, 10),
                              name_clean: r.name_clean || "",
                              weight_num: r.weight_num ?? "",
                              service_type: r.service_type || "WF",
                            })
                          }
                          sx={{ borderColor: "#ffffff", color: "#ffffff", textTransform: "none" }}
                        >
                          Edit
                        </Button>
                        <Button
                          variant="outlined"
                          size="small"
                          color="error"
                          onClick={async () => {
                            if (!window.confirm(`Delete #${r.id}?`)) return;
                            await deleteOrder(r.id);
                            await load();
                          }}
                          sx={{ textTransform: "none" }}
                        >
                          Delete
                        </Button>
                      </>
                    )}
                  </Stack>
                </Stack>
              </Paper>
            );
          })}
        </Stack>
      )}

      <Dialog open={Boolean(submitDialogRow)} onClose={() => setSubmitDialogRow(null)} fullWidth maxWidth="xs">
        <DialogTitle>Submit Processed Order</DialogTitle>
        <DialogContent dividers>
          {submitDialogRow && (
            <Stack spacing={1.1}>
              <Typography sx={{ fontSize: 20 }}>{submitDialogRow.name_clean}</Typography>
              <Typography>{formatDate(submitDialogRow.date_clean)} • {formatMeasure(submitDialogRow)}</Typography>
              <Button variant="outlined" component="label" sx={{ textTransform: "none" }}>
                {submitFile ? submitFile.name : "Take / Upload Ticket Photo"}
                <input
                  hidden
                  type="file"
                  accept="image/*"
                  capture="environment"
                  onChange={(e) => setSubmitFile(e.target.files?.[0] || null)}
                />
              </Button>
              <Alert severity="info">You can submit without a picture and add it later.</Alert>
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSubmitDialogRow(null)}>Cancel</Button>
          <Button variant="contained" onClick={onSubmitOrder} disabled={saving}>
            Confirm Submit
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(ticketDialogRow)} onClose={() => setTicketDialogRow(null)} fullWidth maxWidth="xs">
        <DialogTitle>Add Ticket Picture</DialogTitle>
        <DialogContent dividers>
          {ticketDialogRow && (
            <Stack spacing={1.1}>
              <Typography sx={{ fontSize: 20 }}>{ticketDialogRow.name_clean}</Typography>
              <Button variant="outlined" component="label" sx={{ textTransform: "none" }}>
                {ticketFile ? ticketFile.name : "Select Ticket Photo"}
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
            Save Picture
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(editRow)} onClose={() => setEditRow(null)} fullWidth maxWidth="sm">
        <DialogTitle>Edit Order</DialogTitle>
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
              <TextField
                label="Name"
                value={editRow.name_clean}
                onChange={(e) => setEditRow((p) => ({ ...p, name_clean: e.target.value }))}
              />
              <TextField
                label="Weight / Count"
                type="number"
                value={editRow.weight_num}
                onChange={(e) => setEditRow((p) => ({ ...p, weight_num: e.target.value }))}
              />
              <TextField
                label="Service"
                select
                value={editRow.service_type}
                onChange={(e) => setEditRow((p) => ({ ...p, service_type: e.target.value }))}
              >
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
              } finally {
                setSaving(false);
              }
            }}
            disabled={saving}
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(submitConfirm)} onClose={() => setSubmitConfirm("")} maxWidth="xs" fullWidth>
        <DialogTitle>Confirmation</DialogTitle>
        <DialogContent dividers>
          <Typography>{submitConfirm}</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSubmitConfirm("")}>OK</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default OrdersPage;
