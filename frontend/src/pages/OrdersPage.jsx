import { useEffect, useMemo, useState, useDeferredValue } from "react";
import {
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import {
  Bolt,
  CheckCircle,
  Close,
  DeleteOutline,
  ExpandLess,
  ExpandMore,
  Image,
  Inventory2,
  Refresh,
  Visibility,
} from "@mui/icons-material";
import { useNavigate } from "react-router-dom";
import StandardScreenHeader from "../components/layout/StandardScreenHeader";
import OpsSearchBar from "../components/layout/OpsSearchBar";
import RushTabCountBar from "../components/layout/RushTabCountBar";
import IconPillButton from "../components/layout/IconPillButton";
import { formatSystemDateLong } from "../utils/formatDateLocal";
import {
  deleteOrderTicket,
  deleteOrder,
  getCurrentUploadBatch,
  getOrderTicket,
  getOrders,
  submitProcessedOrder,
  updateOrder,
  uploadOrderTicket,
} from "../api";

const ALPHAS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");
const WF_BG = "#141922";
const HD_BG = "#0a869d";

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

function inferMimeType(fileName) {
  const name = String(fileName || "").toLowerCase();
  if (name.endsWith(".png")) return "image/png";
  if (name.endsWith(".webp")) return "image/webp";
  if (name.endsWith(".gif")) return "image/gif";
  return "image/jpeg";
}

function normalizeCode(value) {
  return String(value || "").trim().toUpperCase();
}

function OrdersPage({ user }) {
  const navigate = useNavigate();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);

  const [rushFilter, setRushFilter] = useState("ALL"); // ALL | RUSH | NON-RUSH
  const [showProcessed, setShowProcessed] = useState(false);
  const [openAlpha, setOpenAlpha] = useState(null);

  const [submitDialogRow, setSubmitDialogRow] = useState(null);
  const [submitMeasure, setSubmitMeasure] = useState("");
  const [submitTicketId, setSubmitTicketId] = useState("");
  const [submitFile, setSubmitFile] = useState(null);
  const [submitPreview, setSubmitPreview] = useState("");
  const [ticketDialogRow, setTicketDialogRow] = useState(null);
  const [ticketFile, setTicketFile] = useState(null);
  const [ticketView, setTicketView] = useState(null);
  const [ticketViewLoading, setTicketViewLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [batchInfo, setBatchInfo] = useState(null);

  const [editRow, setEditRow] = useState(null);

  const roleCodes = (user?.roles || []).map((r) => String(r).toUpperCase());
  const isAdmin = roleCodes.includes("ADMIN");
  const userId = Number(user?.user_id || 0);

  const load = async () => {
    try {
      setLoading(true);
      const [ordersRes, batchRes] = await Promise.allSettled([
        getOrders({ include_all: true }),
        getCurrentUploadBatch(),
      ]);

      if (ordersRes.status === "fulfilled") {
        setRows(Array.isArray(ordersRes.value?.data) ? ordersRes.value.data : []);
      }

      if (batchRes.status === "fulfilled") {
        setBatchInfo(batchRes.value?.data || null);
      } else {
        setBatchInfo(null);
      }

      setNotice("");
    } catch (error) {
      console.error(error);
      setNotice(error?.response?.data?.error || "Failed to load orders.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const normalizeLogistics = (r) => {
    const v = normalizeCode(r?.logistics_status);
    if (v) return v;
    const s = normalizeCode(r?.status);
    if (["CHECKED_OUT", "SENT_TO_RINSE"].includes(s)) return "SENT_TO_RINSE";
    if (["FORCE_CHECKOUT", "FORCED_CHECKOUT"].includes(s)) return "FORCE_CHECKOUT";
    return "AT_WASHPRO";
  };

  const normalizeProcessing = (r) => {
    const v = normalizeCode(r?.processing_status);
    if (v) return v;
    const s = normalizeCode(r?.status);
    return s === "PROCESSED" ? "PROCESSED" : "PENDING";
  };

  const rushOf = (r) => normalizeCode(r?.rush_type) === "RUSH" ? "RUSH" : "NON-RUSH";
  const serviceOf = (r) => normalizeCode(r?.service_type);
  const isHD = (r) => serviceOf(r) === "HD";

  const formatMeasure = (r) => {
    const n = Number(r?.weight_num ?? 0);
    return isHD(r) ? `${Math.round(n)} pcs` : `${n.toFixed(2)} lb`;
  };

  const formatDate = (value) => {
    const d = parseAsLocalDate(value);
    if (!d) return "-";
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  };

  const formatBatchDayDate = (value) => {
    const d = parseAsLocalDate(value);
    if (!d) return "-";
    return d.toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric", year: "numeric" });
  };

  useEffect(() => {
    if (!submitFile) {
      setSubmitPreview("");
      return;
    }
    const url = URL.createObjectURL(submitFile);
    setSubmitPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [submitFile]);

  const visibleRows = useMemo(() => {
    const q = deferredSearch.trim().toLowerCase();

    return rows.filter((r) => {
      if (normalizeLogistics(r) !== "AT_WASHPRO") return false;

      const proc = normalizeProcessing(r);
      if (showProcessed) {
        if (proc !== "PROCESSED") return false;
        if (userId && Number(r?.processed_by_user_id || 0) !== userId) return false;
      } else if (proc !== "PENDING") {
        return false;
      }

      if (rushFilter !== "ALL" && rushOf(r) !== rushFilter) return false;

      if (!q) return true;
      const name = String(r?.name_clean || "").toLowerCase();
      const id = String(r?.id || "").toLowerCase();
      const service = String(r?.service_type || "").toLowerCase();
      const weight = String(r?.weight_num ?? "").toLowerCase();
      return (
        name.startsWith(q) ||
        id.startsWith(q) ||
        service.startsWith(q) ||
        weight.startsWith(q)
      );
    });
  }, [rows, deferredSearch, rushFilter, showProcessed, userId]);

  const grouped = useMemo(() => {
    const out = {};
    for (const a of ALPHAS) out[a] = [];
    for (const r of visibleRows) {
      const c = String(r?.name_clean || "").trim().charAt(0).toUpperCase();
      const k = /^[A-Z]$/.test(c) ? c : "A";
      out[k].push(r);
    }
    return out;
  }, [visibleRows]);

  const counts = useMemo(() => {
    const base = rows.filter((r) => normalizeLogistics(r) === "AT_WASHPRO");
    const pending = base.filter((r) => normalizeProcessing(r) === "PENDING");
    const mine = base.filter(
      (r) => normalizeProcessing(r) === "PROCESSED" && (!userId || Number(r?.processed_by_user_id || 0) === userId)
    );
    return {
      all: showProcessed ? mine.length : pending.length,
      rush: (showProcessed ? mine : pending).filter((r) => rushOf(r) === "RUSH").length,
      nonRush: (showProcessed ? mine : pending).filter((r) => rushOf(r) === "NON-RUSH").length,
    };
  }, [rows, showProcessed, userId]);

  const toggleAlpha = (alpha) => setOpenAlpha((prev) => (prev === alpha ? null : alpha));

  useEffect(() => {
    const q = deferredSearch.trim();
    if (!q || visibleRows.length === 0) return;
    const first = visibleRows[0];
    const c = String(first?.name_clean || "").trim().charAt(0).toUpperCase();
    const alpha = /^[A-Z]$/.test(c) ? c : "A";
    setOpenAlpha(alpha);
  }, [deferredSearch, visibleRows]);

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
      if (isHD(submitDialogRow) && !Number.isInteger(measureNum)) {
        setNotice("HD count must be a whole number.");
        return;
      }
      const payload = {};
      payload.weight_num = measureNum;
      if (submitTicketId) payload.ticket_id = submitTicketId;
      payload.ticket_image_base64 = await fileToBase64(submitFile);
      payload.ticket_file_name = submitFile.name;
      await submitProcessedOrder(submitDialogRow.id, payload);
      setSubmitDialogRow(null);
      setSubmitMeasure("");
      setSubmitTicketId("");
      setSubmitFile(null);
      await load();
    } catch (error) {
      console.error(error);
      const msg = error?.response?.data?.error || "Failed to submit.";
      setNotice(msg === "Forbidden" ? "Forbidden. Please log out and sign in again." : msg);
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

  const onDeleteTicket = async (row) => {
    if (!row?.id) return;
    if (!window.confirm(`Delete ticket image for ${row.name_clean}?`)) return;
    try {
      setSaving(true);
      await deleteOrderTicket(row.id);
      await load();
    } catch (error) {
      console.error(error);
      setNotice("Failed to delete ticket image.");
    } finally {
      setSaving(false);
    }
  };

  const activeBatchDate = batchInfo?.batch_date || rows[0]?.batch_date || null;
  const searchActive = deferredSearch.trim().length > 0;

  const openDryerFlow = (r) => {
    if (showProcessed) return;
    if (normalizeProcessing(r) !== "PENDING") return;
    const st = String(r.gaming_flow_status || "").toUpperCase();
    if (st === "COMPLETED") return;
    const lockUid = Number(r.gaming_locked_by_user_id || 0);
    if (st === "ACTIVE" && lockUid && lockUid !== userId) {
      setNotice("This order is in use by another team member.");
      return;
    }
    navigate(`/orders/${r.id}/dryer-flow`);
  };

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "#ffffff", px: { xs: 1, sm: 1.5 }, py: 1 }}>
      <StandardScreenHeader
        title="Rinse orders"
        dateLabel={formatSystemDateLong()}
        right={
          <>
            <IconPillButton
              title={showProcessed ? "Showing orders you folded" : "Show orders you folded"}
              icon={<Inventory2 />}
              label={showProcessed ? "Folded" : "Folded"}
              variant={showProcessed ? "contained" : "outlined"}
              onClick={() => setShowProcessed((p) => !p)}
            />
            <IconPillButton title="Refresh" icon={<Refresh />} label="" onClick={load} />
          </>
        }
      />
      <Typography sx={{ fontSize: 14, color: "#6b7280", fontWeight: 400, mt: -0.5, mb: 0.5 }}>
        Batch day: {formatBatchDayDate(activeBatchDate)}
      </Typography>

      <RushTabCountBar
        value={rushFilter}
        onChange={setRushFilter}
        tabs={[
          { key: "ALL", label: "All", count: counts.all },
          { key: "RUSH", label: "Rush", count: counts.rush, Icon: Bolt, accent: "#b91c1c" },
          { key: "NON-RUSH", label: "Non-Rush", count: counts.nonRush, Icon: CheckCircle, accent: "#0f766e" },
        ]}
      />

      <OpsSearchBar value={search} onChange={setSearch} />

      {loading ? (
        <Stack alignItems="center" justifyContent="center" sx={{ py: 8 }} spacing={1.1}>
          <CircularProgress size={26} />
          <Typography color="text.secondary">Loading...</Typography>
        </Stack>
      ) : (
        <Stack spacing={1} sx={{ mt: 1.2 }}>
          {ALPHAS.map((alpha) => {
            const list = grouped[alpha] || [];
            if (searchActive && list.length === 0) return null;
            const expanded = searchActive ? true : openAlpha === alpha;
            return (
              <Paper
                key={alpha}
                sx={{
                  borderRadius: 2,
                  border: "1px solid #e5e7eb",
                  overflow: "hidden",
                  opacity: list.length === 0 ? 0.36 : 1,
                }}
              >
                <Button
                  fullWidth
                  onClick={() => toggleAlpha(alpha)}
                  sx={{
                    px: 1.1,
                    py: 1,
                    justifyContent: "space-between",
                    textTransform: "none",
                    color: "#111827",
                    bgcolor: "#f8fafc",
                  }}
                >
                  <Stack direction="row" spacing={1.2} alignItems="center">
                    <Box
                      sx={{
                        width: 28,
                        height: 28,
                        borderRadius: "50%",
                        display: "grid",
                        placeItems: "center",
                        bgcolor: "#111827",
                        color: "#ffffff",
                        fontSize: 14,
                        fontWeight: 400,
                      }}
                    >
                      {alpha}
                    </Box>
                    <Typography sx={{ fontSize: 16, fontWeight: 400 }}>{list.length} bags</Typography>
                  </Stack>
                  {expanded ? <ExpandLess /> : <ExpandMore />}
                </Button>

                {expanded && (
                  <Box sx={{ p: 1 }}>
                    {list.length === 0 ? (
                      <Typography sx={{ color: "#6b7280", fontSize: 14 }}>No orders.</Typography>
                    ) : (
                      <Stack spacing={1}>
                        {list.map((r) => {
                          const rush = rushOf(r) === "RUSH";
                          const hd = isHD(r);
                          const pending = normalizeProcessing(r) === "PENDING";
                          const gameSt = String(r.gaming_flow_status || "").toUpperCase();
                          const lockUid = Number(r.gaming_locked_by_user_id || 0);
                          const lockedOther = gameSt === "ACTIVE" && lockUid && lockUid !== userId;
                          const lockedMe = gameSt === "ACTIVE" && lockUid === userId;
                          const gameDone = gameSt === "COMPLETED";
                          const cardCursor =
                            showProcessed || !pending || gameDone || lockedOther ? "default" : "pointer";
                          return (
                            <Paper
                              key={r.id}
                              sx={{
                                borderRadius: 2,
                                bgcolor: hd ? HD_BG : WF_BG,
                                color: "#ffffff",
                                border: hd ? "1px solid #44c3d6" : "1px solid #2b3342",
                                outline: lockedOther ? "3px solid #fb923c" : lockedMe ? "3px solid #facc15" : gameDone ? "3px solid #4ade80" : "none",
                                outlineOffset: 1,
                              }}
                            >
                              <Box
                                role={!showProcessed && pending && !gameDone && !lockedOther ? "button" : undefined}
                                onClick={() => openDryerFlow(r)}
                                sx={{
                                  p: 1.2,
                                  cursor: cardCursor,
                                  opacity: lockedOther ? 0.72 : 1,
                                }}
                              >
                                <Stack spacing={0.9}>
                                  <Stack direction="row" justifyContent="space-between" alignItems="center">
                                    <Stack direction="row" spacing={0.7} alignItems="center">
                                      {rush ? <Bolt sx={{ fontSize: 20, color: "#ffcb5b" }} /> : <CheckCircle sx={{ fontSize: 17, color: "#d1fae5" }} />}
                                      <Typography sx={{ fontSize: 13, letterSpacing: 0.5, opacity: 0.9, fontWeight: 400 }}>
                                        {rush ? "RUSH" : "NON-RUSH"}
                                      </Typography>
                                    </Stack>
                                    <Typography sx={{ fontSize: 13, opacity: 0.85, fontWeight: 400 }}>
                                      {pending ? "Pending" : "Processed"}
                                      {lockedOther ? " • In use" : lockedMe ? " • You" : gameDone ? " • Dryers OK" : ""}
                                    </Typography>
                                  </Stack>

                                  <Typography sx={{ fontSize: 38 > String(r?.name_clean || "").length ? 20 : 18, lineHeight: 1.15, fontWeight: 400 }}>
                                    {r.name_clean}
                                  </Typography>

                                  <Typography sx={{ fontSize: 16, opacity: 0.92, fontWeight: 400 }}>
                                    {formatDate(r.date_clean)} • {formatMeasure(r)}
                                  </Typography>
                                </Stack>
                              </Box>

                              <Box sx={{ px: 1.2, pb: 1.2, pt: 0 }} onClick={(e) => e.stopPropagation()}>
                                {showProcessed ? (
                                  <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                                    {Number(r?.has_ticket_image || 0) > 0 && (
                                      <Button
                                        size="small"
                                        variant="outlined"
                                        startIcon={<Visibility />}
                                        onClick={() => onViewTicket(r)}
                                        sx={{ textTransform: "none", borderColor: "#ffffff", color: "#ffffff", fontWeight: 400 }}
                                      >
                                        View picture
                                      </Button>
                                    )}
                                    <Button
                                      size="small"
                                      variant="outlined"
                                      startIcon={<Image />}
                                      onClick={() => setTicketDialogRow(r)}
                                      sx={{ textTransform: "none", borderColor: "#ffffff", color: "#ffffff", fontWeight: 400 }}
                                    >
                                      {Number(r?.has_ticket_image || 0) > 0 ? "Replace picture" : "Add picture"}
                                    </Button>
                                    {Number(r?.has_ticket_image || 0) > 0 && (
                                      <Button
                                        size="small"
                                        variant="outlined"
                                        color="error"
                                        startIcon={<DeleteOutline />}
                                        onClick={() => onDeleteTicket(r)}
                                        sx={{ textTransform: "none", fontWeight: 400 }}
                                      >
                                        Delete picture
                                      </Button>
                                    )}
                                  </Stack>
                                ) : (
                                  <Button
                                    size="medium"
                                    variant="contained"
                                    onClick={() => {
                                      setSubmitDialogRow(r);
                                      setSubmitMeasure("");
                                      setSubmitTicketId(String(r.ticket_id || ""));
                                      setSubmitFile(null);
                                    }}
                                    sx={{
                                      textTransform: "none",
                                      bgcolor: "#ffffff",
                                      color: "#111827",
                                      fontWeight: 600,
                                      borderRadius: 999,
                                      px: 2.5,
                                      py: 1,
                                    }}
                                  >
                                    Submit
                                  </Button>
                                )}
                              </Box>

                              {isAdmin && (
                                <Box sx={{ px: 1.2, pb: 1.2 }} onClick={(e) => e.stopPropagation()}>
                                  <Divider sx={{ borderColor: "rgba(255,255,255,0.2)", mb: 1 }} />
                                  <Stack direction="row" spacing={1}>
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
                                      sx={{ textTransform: "none", borderColor: "#ffffff", color: "#ffffff", fontWeight: 400 }}
                                    >
                                      Edit
                                    </Button>
                                    <Button
                                      size="small"
                                      variant="outlined"
                                      color="error"
                                      onClick={async () => {
                                        if (!window.confirm(`Delete #${r.id}?`)) return;
                                        await deleteOrder(r.id);
                                        await load();
                                      }}
                                      sx={{ textTransform: "none", fontWeight: 400 }}
                                    >
                                      Delete
                                    </Button>
                                  </Stack>
                                </Box>
                              )}
                            </Paper>
                          );
                        })}
                      </Stack>
                    )}
                  </Box>
                )}
              </Paper>
            );
          })}
        </Stack>
      )}

      <Dialog open={Boolean(submitDialogRow)} onClose={() => setSubmitDialogRow(null)} fullWidth maxWidth="xs">
        <DialogTitle sx={{ fontWeight: 400 }}>Submit</DialogTitle>
        <DialogContent dividers>
          {submitDialogRow && (
            <Stack spacing={1.1}>
              <TextField
                label={String(submitDialogRow.service_type || "").toUpperCase() === "HD" ? "Count" : "Weight"}
                type="number"
                value={submitMeasure}
                onChange={(e) => setSubmitMeasure(e.target.value)}
                autoFocus
              />
              <Button variant="outlined" component="label" sx={{ textTransform: "none", fontWeight: 400 }}>
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
                <Box sx={{ position: "relative", borderRadius: 1.5, overflow: "hidden", border: "1px solid #e5e7eb" }}>
                  <Box
                    component="img"
                    src={submitPreview}
                    alt="ticket preview"
                    sx={{ width: "100%", display: "block", maxHeight: 260, objectFit: "contain", bgcolor: "#111827" }}
                  />
                  <IconButton
                    size="small"
                    onClick={() => setSubmitFile(null)}
                    sx={{
                      position: "absolute",
                      top: 8,
                      right: 8,
                      bgcolor: "rgba(255,255,255,0.9)",
                      "&:hover": { bgcolor: "#ffffff" },
                    }}
                  >
                    <Close fontSize="small" />
                  </IconButton>
                </Box>
              )}
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSubmitDialogRow(null)} sx={{ fontWeight: 400 }}>Cancel</Button>
          <Button
            variant="contained"
            onClick={onSubmitOrder}
            disabled={saving || !submitMeasure || !submitFile}
            sx={{ fontWeight: 400 }}
          >
            Submit
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(ticketDialogRow)} onClose={() => setTicketDialogRow(null)} fullWidth maxWidth="xs">
        <DialogTitle sx={{ fontWeight: 400 }}>Add Ticket Picture</DialogTitle>
        <DialogContent dividers>
          {ticketDialogRow && (
            <Stack spacing={1.1}>
              <Typography sx={{ fontSize: 20, fontWeight: 400 }}>{ticketDialogRow.name_clean}</Typography>
              <Button variant="outlined" component="label" sx={{ textTransform: "none", fontWeight: 400 }}>
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
          <Button onClick={() => setTicketDialogRow(null)} sx={{ fontWeight: 400 }}>Cancel</Button>
          <Button variant="contained" onClick={onAddTicket} disabled={!ticketFile || saving} sx={{ fontWeight: 400 }}>
            Save Picture
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(ticketView)} onClose={() => setTicketView(null)} fullWidth maxWidth="sm">
        <DialogTitle sx={{ fontWeight: 400 }}>Ticket Picture</DialogTitle>
        <DialogContent dividers>
          {ticketViewLoading ? (
            <Stack alignItems="center" sx={{ py: 2 }}>
              <CircularProgress size={24} />
            </Stack>
          ) : (
            ticketView && (
              <Stack spacing={1.1}>
                <Typography sx={{ fontWeight: 400 }}>{ticketView.name_clean}</Typography>
                <Box
                  component="img"
                  alt="ticket"
                  src={ticketView.src}
                  sx={{ width: "100%", borderRadius: 1.5, border: "1px solid #e5e7eb" }}
                />
                <Typography sx={{ fontSize: 13, color: "#6b7280", fontWeight: 400 }}>
                  {ticketView.ticket_file_name || "ticket.jpg"}
                </Typography>
              </Stack>
            )
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setTicketView(null)} sx={{ fontWeight: 400 }}>Close</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(editRow)} onClose={() => setEditRow(null)} fullWidth maxWidth="sm">
        <DialogTitle sx={{ fontWeight: 400 }}>Edit Order</DialogTitle>
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
          <Button onClick={() => setEditRow(null)} sx={{ fontWeight: 400 }}>Cancel</Button>
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
            sx={{ fontWeight: 400 }}
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(notice)} onClose={() => setNotice("")} fullWidth maxWidth="xs">
        <DialogTitle sx={{ fontWeight: 400 }}>Confirmation</DialogTitle>
        <DialogContent dividers>
          <Typography sx={{ fontWeight: 400 }}>{notice}</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setNotice("")} sx={{ fontWeight: 400 }}>OK</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default OrdersPage;
